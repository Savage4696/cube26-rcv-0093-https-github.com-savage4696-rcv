from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Optional

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import TypeAdapter, ValidationError

from .integrations import (
    CrossPodIntegrationService,
    PackDetectedItem,
    PackOrderItem,
    PackVerificationResult,
    PrepWorkOrder,
    RecoveryReconciliationReport,
    ReturnAssessmentQuery,
    ReturnCorrelationResult,
    cross_pod_service,
)

from . import definitions
from .config import load_settings
from .evidence import EvidenceStore, verify
from .models import (
    CatalogItem,
    Decision,
    EvidenceRecord,
    Observations,
    PurchaseOrder,
    SupplierStats,
)
from .scenarios import SCENARIO_DIR, evaluate, load_catalog, load_scenarios
from .service import UploadedPhoto, run_inspection
from .vision import get_provider, get_reviewer, make_budget, make_cache

STATIC_DIR = Path(__file__).parent / "static"
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

settings = load_settings()
store = EvidenceStore(settings.data_dir)
budget = make_budget(settings)
cache = make_cache(settings)
provider = get_provider(settings, budget, cache)
reviewer = get_reviewer(settings, budget, cache)
app = FastAPI(title="Receiving Manager")
catalog_adapter = TypeAdapter(list[CatalogItem])
NO_PHOTOS = File(default=[])


def reload_ai_services(custom_key: str | None = None) -> None:
    """Reloads or overrides AI provider & reviewer at runtime (e.g. from UI or Vercel header)."""
    global settings, budget, cache, provider, reviewer
    import os

    if custom_key and custom_key.strip():
        os.environ["OPENROUTER_API_KEY"] = custom_key.strip()
        os.environ["RM_VISION_PROVIDER"] = "openrouter"
        if "RM_REASONING" not in os.environ:
            os.environ["RM_REASONING"] = "on"

    settings = load_settings()
    budget = make_budget(settings)
    cache = make_cache(settings)
    provider = get_provider(settings, budget, cache)
    reviewer = get_reviewer(settings, budget, cache)


def _parse(model, raw: str, field: str):
    try:
        if isinstance(model, TypeAdapter):
            return model.validate_json(raw)
        return model.model_validate_json(raw)
    except (ValidationError, json.JSONDecodeError) as exc:
        raise HTTPException(422, f"Invalid {field}: {exc}") from exc


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health(request: Request) -> dict:
    header_key = request.headers.get("x-openrouter-key")
    if not provider and header_key:
        reload_ai_services(header_key)
    return {
        "status": "ok",
        "vision_provider": provider.name if provider else None,
        "reasoning_model": reviewer.model if reviewer else None,
        "confidence_threshold": settings.confidence_threshold,
    }


@app.post("/api/config/key")
def configure_api_key(payload: dict = Body(...)) -> dict:
    key = payload.get("openrouter_api_key") or payload.get("api_key")
    if not key or not key.strip():
        raise HTTPException(400, "API key cannot be empty")
    reload_ai_services(key.strip())
    return {
        "status": "configured",
        "vision_provider": provider.name if provider else None,
        "reasoning_model": reviewer.model if reviewer else None,
        "confidence_threshold": settings.confidence_threshold,
    }


@app.get("/api/budget")
def budget_status() -> dict:
    return budget.status()


@app.get("/api/definitions")
def get_definitions() -> dict:
    return definitions.as_dict()


@app.get("/api/stats")
def warehouse_stats() -> dict:
    """Aggregate live warehouse dock metrics, acceptance rates, and cross-pod dispute values."""
    records = store.list_records()
    total = len(records)
    accepts = sum(1 for r in records if r.report.decision == Decision.ACCEPT)
    exceptions = sum(1 for r in records if r.report.decision == Decision.EXCEPTION)
    uncertains = sum(1 for r in records if r.report.decision == Decision.UNCERTAIN)
    accept_rate = round((accepts / total) * 100.0, 1) if total > 0 else 0.0
    exception_rate = round((exceptions / total) * 100.0, 1) if total > 0 else 0.0
    avg_risk = round(sum(r.report.risk_score for r in records) / total, 1) if total > 0 else 0.0

    try:
        recovery_report = cross_pod_service.reconcile_recovery_fees()
        disputed_fba_fees = sum(c.amount for c in recovery_report.claims if c.category == "fba_reimbursement")
        vendor_chargebacks = sum(c.amount for c in recovery_report.claims if c.category == "vendor_chargeback")
    except Exception:
        disputed_fba_fees = 0.0
        vendor_chargebacks = 0.0

    return {
        "total_inspections": total,
        "accept_count": accepts,
        "exception_count": exceptions,
        "uncertain_count": uncertains,
        "accept_rate": accept_rate,
        "exception_rate": exception_rate,
        "avg_risk_score": avg_risk,
        "disputed_fba_amount": round(disputed_fba_fees, 2),
        "vendor_chargeback_amount": round(vendor_chargebacks, 2),
        "total_dispute_potential": round(disputed_fba_fees + vendor_chargebacks, 2),
        "active_pods": 5,
        "tamper_evident_records": total,
    }


@app.get("/api/benchmark")
def benchmark() -> dict:
    """Run the 24 deterministic rules regression scenarios (pure business logic, offline, 0-cost)."""
    catalog = load_catalog()
    rows = []
    for s in load_scenarios():
        report, mismatches = evaluate(s, catalog, settings.confidence_threshold)
        rows.append(
            {
                "name": s.name,
                "title": s.title,
                "expected_decision": s.expected.decision,
                "decision": report.decision.value,
                "verdicts": {c.check: c.verdict.value for c in report.checks},
                "issue_codes": sorted({i.code for i in report.issues}),
                "mismatches": mismatches,
                "passed": not mismatches,
            }
        )
    return {
        "suite": "rules_regression",
        "description": "24 deterministic business logic regression scenarios",
        "total": len(rows),
        "passed": sum(r["passed"] for r in rows),
        "results": rows,
    }


@app.get("/api/evaluation")
def evaluation_metrics() -> dict:
    """Retrieve official 50-unit held-out vision model evaluation metrics (Cohen's Kappa, FP/FN)."""
    results_path = Path(__file__).resolve().parent.parent / "data" / "eval_50" / "eval_results.json"
    if not results_path.exists():
        return {
            "status": "pending",
            "message": "Held-out evaluation running or not yet executed.",
        }
    return json.loads(results_path.read_text())


@app.get("/api/evaluation/photos/{unit_id}/{photo_id}")
def evaluation_photo(unit_id: str, photo_id: str) -> FileResponse:
    base = Path(__file__).resolve().parent.parent / "data" / "eval_50" / "photos"
    path = base / unit_id / f"{photo_id}.png"
    if not path.exists():
        raise HTTPException(404, "Evaluation photo not found")
    return FileResponse(path, media_type="image/png")


@app.get("/api/scenarios/{name}/photos/{photo_id}")
def scenario_photo(name: str, photo_id: str) -> FileResponse:
    names = {s.name for s in load_scenarios()}
    path = SCENARIO_DIR / "photos" / name / f"{photo_id}.png"
    if name not in names or not path.resolve().is_relative_to(SCENARIO_DIR) or not path.exists():
        raise HTTPException(404, "Sample photo not found")
    return FileResponse(path, media_type="image/png")


@app.get("/api/scenarios")
def scenarios() -> dict:
    return {
        "catalog": [c.model_dump() for c in load_catalog()],
        "scenarios": [s.model_dump(mode="json") for s in load_scenarios()],
    }


@app.post("/api/inspections")
async def create_inspection(
    request: Request,
    purchase_order: str = Form(...),
    catalog: str = Form("[]"),
    sku: str | None = Form(None),
    observations: str | None = Form(None),
    ai_review: bool = Form(True),
    threshold: float | None = Form(None),
    openrouter_api_key: str | None = Form(None),
    photos: list[UploadFile] = NO_PHOTOS,
) -> EvidenceRecord:
    key = openrouter_api_key or request.headers.get("x-openrouter-key")
    if not provider and key:
        reload_ai_services(key)

    po = _parse(PurchaseOrder, purchase_order, "purchase_order")
    cat = _parse(catalog_adapter, catalog, "catalog")
    obs = _parse(Observations, observations, "observations") if observations else None
    conf_threshold = threshold if threshold is not None else settings.confidence_threshold
    uploads = []
    for f in photos:
        if f.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(415, f"Unsupported photo type for {f.filename}: {f.content_type}")
        uploads.append(UploadedPhoto(f.filename or "photo", f.content_type, await f.read()))
    try:
        return run_inspection(
            po,
            cat,
            uploads,
            store,
            provider,
            conf_threshold,
            sku=sku or None,
            observations=obs,
            reviewer=reviewer if ai_review else None,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/inspections")
def list_inspections() -> list[dict]:
    return [
        {
            "inspection_id": r.report.inspection_id,
            "created_at": r.report.created_at,
            "po_number": r.report.po_number,
            "supplier": r.purchase_order.supplier,
            "sku": r.report.sku,
            "decision": r.report.decision,
            "risk_score": r.report.risk_score,
            "risk_level": r.report.risk_level,
        }
        for r in store.list_records()
    ]


@app.get("/api/suppliers/stats")
def supplier_stats() -> list[SupplierStats]:
    records = store.list_records()
    by_supplier: dict[str, list[EvidenceRecord]] = {}
    for r in records:
        supp = r.purchase_order.supplier or "Unknown Supplier"
        by_supplier.setdefault(supp, []).append(r)

    stats = []
    from collections import Counter

    for supp, list_recs in by_supplier.items():
        total = len(list_recs)
        accepts = sum(1 for r in list_recs if r.report.decision == Decision.ACCEPT)
        exceptions = sum(1 for r in list_recs if r.report.decision == Decision.EXCEPTION)
        uncertains = sum(1 for r in list_recs if r.report.decision == Decision.UNCERTAIN)
        acc_rate = round((accepts / total) * 100.0, 1) if total > 0 else 0.0
        avg_risk = (
            round(sum(r.report.risk_score for r in list_recs) / total, 1) if total > 0 else 0.0
        )

        all_issues = [issue.code for r in list_recs for issue in r.report.issues]
        common = [code for code, _ in Counter(all_issues).most_common(5)]

        stats.append(
            SupplierStats(
                supplier=supp,
                total_inspections=total,
                accept_count=accepts,
                exception_count=exceptions,
                uncertain_count=uncertains,
                accept_rate=acc_rate,
                avg_risk_score=avg_risk,
                common_issues=common,
            )
        )
    return sorted(stats, key=lambda s: s.total_inspections, reverse=True)


@app.get("/api/inspections/export")
def export_inspections(fmt: str = "json") -> Response:
    records = store.list_records()
    if fmt == "csv":
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(
            [
                "Inspection ID",
                "Created At",
                "PO Number",
                "Supplier",
                "SKU",
                "Decision",
                "Risk Score",
                "Risk Level",
                "Observation Source",
                "Record SHA-256",
            ]
        )
        for r in records:
            writer.writerow(
                [
                    r.report.inspection_id,
                    r.report.created_at.isoformat(),
                    r.report.po_number,
                    r.purchase_order.supplier,
                    r.report.sku,
                    r.report.decision.value,
                    r.report.risk_score,
                    r.report.risk_level,
                    r.observation_source,
                    r.record_sha256 or "",
                ]
            )
        return Response(
            content=out.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=rcv_inspections_export.csv"},
        )
    else:
        content = json.dumps([r.model_dump(mode="json") for r in records], indent=2)
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=rcv_inspections_export.json"},
        )


def _load(inspection_id: str) -> EvidenceRecord:
    try:
        record = store.load_record(inspection_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if record is None:
        raise HTTPException(404, "Inspection not found")
    return record


@app.get("/api/inspections/{inspection_id}")
def get_inspection(inspection_id: str) -> EvidenceRecord:
    return _load(inspection_id)


@app.get("/api/inspections/{inspection_id}/verify")
def verify_inspection(inspection_id: str) -> dict:
    record = _load(inspection_id)
    return {
        "inspection_id": inspection_id,
        "record_sha256": record.record_sha256,
        "valid": verify(record),
    }


@app.get("/api/inspections/{inspection_id}/photos/{photo_id}")
def get_photo(inspection_id: str, photo_id: str) -> FileResponse:
    record = _load(inspection_id)
    photo = next((p for p in record.photos if p.photo_id == photo_id), None)
    if photo is None or not photo.stored_path or not Path(photo.stored_path).exists():
        raise HTTPException(404, "Photo not found")
    return FileResponse(photo.stored_path, media_type=photo.content_type)


# ---------------------------------------------------------------------------
# Cross-Pod Ecosystem Integrations (PRP · RTM · RCY)
# ---------------------------------------------------------------------------

@app.get("/api/integrations/status")
def get_ecosystem_status() -> dict:
    return cross_pod_service.get_ecosystem_status()


@app.post("/api/integrations/prep/dispatch")
def dispatch_prep(
    unit_id: str = Form(...),
    sku: Optional[str] = Form(None),
    org_id: Optional[str] = Form("org_demo_alpha"),
) -> PrepWorkOrder:
    return cross_pod_service.dispatch_to_prep(unit_id=unit_id, custom_sku=sku, custom_org_id=org_id)


@app.get("/api/integrations/pack/manifest/{unit_id}")
def get_pack_manifest(unit_id: str) -> list[PackOrderItem]:
    return cross_pod_service.get_pack_manifest(unit_id)


@app.post("/api/integrations/pack/verify")
def verify_pack_endpoint(
    unit_id: str = Form(...),
    detected_sku: str = Form(...),
    detected_qty: int = Form(...),
    evidence: str = Form("Verified pre-seal overhead photo"),
) -> PackVerificationResult:
    detected = [PackDetectedItem(sku=detected_sku, quantity=detected_qty, evidence=evidence)]
    return cross_pod_service.verify_outbound_pack_for_unit(unit_id=unit_id, detected_items=detected)


@app.post("/api/integrations/returns/correlate")
def correlate_return(query: ReturnAssessmentQuery) -> ReturnCorrelationResult:
    return cross_pod_service.correlate_customer_return(query)


@app.get("/api/integrations/returns/correlate/{unit_id}")
def correlate_return_quick(
    unit_id: str,
    returned_sku: Optional[str] = None,
    state: str = "damaged",
) -> ReturnCorrelationResult:
    rec = cross_pod_service.get_unit_inbound_record(unit_id) or {}
    sku = returned_sku or rec.get("sku", "SKU-UNKNOWN")
    query = ReturnAssessmentQuery(
        unit_id=unit_id,
        returned_sku=sku,
        return_observed_state=state,
    )
    return cross_pod_service.correlate_customer_return(query)


@app.get("/api/integrations/recovery/reconcile")
def reconcile_recovery_sample() -> RecoveryReconciliationReport:
    return cross_pod_service.reconcile_recovery_claims()


@app.post("/api/integrations/recovery/reconcile")
def reconcile_recovery_custom(
    fee_csv: str = Body(..., media_type="text/plain"),
) -> RecoveryReconciliationReport:
    return cross_pod_service.reconcile_recovery_claims(fee_csv)
