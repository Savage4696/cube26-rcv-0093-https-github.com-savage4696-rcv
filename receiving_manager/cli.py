from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from pathlib import Path

import uvicorn
from pydantic import TypeAdapter

from .config import load_settings
from .evidence import EvidenceStore
from .models import AIReview, CatalogItem, InspectionReport, Observations, PurchaseOrder, Verdict
from .scenarios import evaluate, load_catalog, load_scenarios
from .service import UploadedPhoto, run_inspection
from .vision import get_provider, get_reviewer, make_budget, make_cache


def print_report(report: InspectionReport) -> None:
    print(f"PO {report.po_number} / SKU {report.sku}  [inspection {report.inspection_id}]")
    for c in report.checks:
        if c.verdict == Verdict.NOT_APPLICABLE:
            continue
        conf = f" conf={c.confidence:.2f}" if c.confidence is not None else ""
        print(
            f"  {c.check:<17} {c.verdict.value:<9} expected={c.expected!s:<12} "
            f"observed={c.observed!s}{conf}"
        )
        print(f"  {'':<17} {c.reason}")
    print(f"  DECISION: {report.decision.value} - {report.decision_reason}")
    for w in report.warnings:
        print(f"  warning: {w}")


def print_review(review: AIReview) -> None:
    cost = "cached" if review.cached else f"${review.cost_usd:.4f}"
    print(f"  AI REVIEW ({review.model}, {cost}): {review.summary}")
    for c in review.concerns:
        print(f"    concern: {c.description}")
    for a in review.recommended_actions:
        print(f"    action: {a}")
    if review.supplier_claim_draft:
        print(f"    supplier claim draft: {review.supplier_claim_draft}")


def cmd_inspect(args: argparse.Namespace) -> int:
    settings = load_settings()
    po = PurchaseOrder.model_validate_json(Path(args.po).read_text())
    catalog = (
        TypeAdapter(list[CatalogItem]).validate_json(Path(args.catalog).read_text())
        if args.catalog
        else []
    )
    obs = (
        Observations.model_validate_json(Path(args.observations).read_text())
        if args.observations
        else None
    )
    uploads = [
        UploadedPhoto(
            Path(p).name, mimetypes.guess_type(p)[0] or "image/jpeg", Path(p).read_bytes()
        )
        for p in args.photos
    ]
    budget, cache = make_budget(settings), make_cache(settings)
    record = run_inspection(
        po,
        catalog,
        uploads,
        EvidenceStore(settings.data_dir),
        get_provider(settings, budget, cache),
        args.threshold or settings.confidence_threshold,
        sku=args.sku,
        observations=obs,
        reviewer=None if args.no_review else get_reviewer(settings, budget, cache),
    )
    if args.json:
        print(record.model_dump_json(indent=2))
    else:
        print_report(record.report)
        if record.ai_review:
            print_review(record.ai_review)
        print(f"  model cost: ${record.llm_cost_usd:.4f}")
        print(
            f"Evidence record: {settings.data_dir}/inspections/{record.report.inspection_id}/"
            "evidence.json"
        )
    return 0


def cmd_scenarios(args: argparse.Namespace) -> int:
    catalog = load_catalog()
    failures = total = 0
    for s in load_scenarios():
        if args.name and s.name != args.name:
            continue
        total += 1
        report, mismatches = evaluate(s, catalog, args.threshold)
        failures += bool(mismatches)
        print(
            f"=== {s.name}: {s.title}  (expected {s.expected.decision}) "
            f"{'MISMATCH: ' + '; '.join(mismatches) if mismatches else 'OK'}"
        )
        if args.json:
            print(json.dumps(report.model_dump(mode="json"), indent=2))
        else:
            print_report(report)
        print()
    print(f"{total - failures}/{total} scenarios match their expected outcome")
    return 1 if failures else 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    results_path = Path(__file__).resolve().parent.parent / "data" / "eval_50" / "eval_results.json"
    if args.run or not results_path.exists():
        from scripts.run_held_out_evaluation import run_evaluation
        summary = run_evaluation(limit=args.limit)
    else:
        summary = json.loads(results_path.read_text())
        print("=== Loaded Latest 50-Unit Vision Evaluation Results ===")
        print(f"Overall Accuracy: {summary['accuracy_percent']} ({summary['total_units']})")
        print(f"Human Evaluator Agreement (Cohen's Kappa): {summary['human_evaluator_kappa']}")
        print(f"Agent vs. Consensus Agreement (Cohen's Kappa): {summary['agent_consensus_kappa']}")
        print(f"UNCERTAIN Rate: {summary['uncertain_rate_percent']} ({summary['uncertain_count']} units)")
        print(f"Total API Cost: ${summary['total_cost_usd']:.4f} (Avg ${summary['avg_cost_per_unit_usd']:.4f}/unit)")
        print(f"Avg Latency: {summary['avg_latency_ms']} ms/unit")
    if args.json:
        print(json.dumps(summary, indent=2))
    return 0


def cmd_integrate(args: argparse.Namespace) -> int:
    from receiving_manager.integrations import ReturnAssessmentQuery, cross_pod_service

    pod = (args.pod or "status").lower()

    if pod == "status":
        info = cross_pod_service.get_ecosystem_status()
        print("=== CUBE 2026 Cross-Pod Ecosystem Status ===")
        print(f"Hub: {info['hub']} (Contract v{info['evidence_contract_version']})")
        print(f"Inbound units indexed: {info['cached_inbound_units']}")
        print("\nConnected Managers:")
        for code, details in info["active_pods"].items():
            print(f"  [{code}] Stage {details['stage']}: {details['name']} ({details['repo']})")
            print(f"        Role: {details['role']}")
            print(f"        Status: {details['status']}")
        return 0

    if pod == "prep":
        unit = args.unit or "UNIT-0005"
        wo = cross_pod_service.dispatch_to_prep(unit_id=unit, custom_sku=args.sku)
        print(f"=== Stage 02: Prep Manager Work Order ({wo.work_order_id}) ===")
        print(f"Unit: {wo.unit_id} | SKU: {wo.sku} | Priority: {wo.priority.value}")
        print(f"Inbound Origin: {wo.inbound_record_id} ({wo.inbound_outcome})")
        print(f"Recommended Rulebook: {wo.recommended_rulebook}")
        print(f"Required Prep Operations ({len(wo.required_prep)}):")
        for req in wo.required_prep:
            print(f"  • {req.value}")
        print(f"Operator Notes: {wo.operator_notes}")
        if args.json:
            print(json.dumps(wo.model_dump(mode="json"), indent=2))
        return 0

    if pod == "returns":
        unit = args.unit or "UNIT-0010"
        query = ReturnAssessmentQuery(
            unit_id=unit,
            returned_sku=args.sku or "SKU-CANDLE-3",
            return_observed_state=args.state or "opened_unused",
        )
        res = cross_pod_service.correlate_customer_return(query)
        print(f"=== Stage 04: Returns Manager Cross-Check ({unit}) ===")
        print(f"Provenance Status: {res.correlation_status.value}")
        print(f"Assigned Liability: {res.liability.value}")
        print(f"Fraud Risk Score: {res.fraud_risk_score:.2f}")
        print(f"Dock Reference: {res.inbound_record_id or 'NONE'} ({res.inbound_sku or 'N/A'})")
        print(f"Findings: {res.evidence_comparison_notes}")
        if args.json:
            print(json.dumps(res.model_dump(mode="json"), indent=2))
        return 0

    if pod == "recovery":
        csv_text = None
        if args.fee_csv:
            csv_text = Path(args.fee_csv).read_text(encoding="utf-8")
        report = cross_pod_service.reconcile_recovery_claims(csv_text)
        print(f"=== Stage 05: Recovery Manager Dispute Reconciliation ({report.report_id}) ===")
        print(f"Total Fee Lines Analyzed: {report.total_fee_lines_analyzed}")
        print(f"Contradicting Charges (FBA Disputes): {report.contradicting_count} (${report.total_fba_dispute_amount:.2f})")
        print(f"Supporting Charges (Vendor Chargebacks): {report.supporting_count} (${report.total_vendor_chargeback_amount:.2f})")
        print(f"Silent Charges: {report.silent_count}")
        print("\nTop Actionable Claims:")
        for line in [i for i in report.items if i.stance.value != "SILENT"][:8]:
            print(f"  • [{line.stance.value}] {line.line_id} ({line.unit_id} / {line.sku}): ${line.dispute_amount_usd:.2f} -> {line.claim_target.value}")
            print(f"    Reason: {line.audit_explanation}")
        if args.json:
            print(json.dumps(report.model_dump(mode="json"), indent=2))
        return 0

    print(f"Unknown pod: {pod}. Use one of: status, prep, returns, recovery")
    return 1


def cmd_serve(args: argparse.Namespace) -> int:
    uvicorn.run("receiving_manager.api:app", host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="receiving-manager")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("inspect", help="Inspect a shipment from photos")
    p.add_argument("--po", required=True, help="Purchase order JSON file")
    p.add_argument("--catalog", help="Catalogue JSON file (list of items)")
    p.add_argument("--sku", help="PO line SKU to inspect (default: first line)")
    p.add_argument("--observations", help="Precomputed observations JSON (skips vision model)")
    p.add_argument("--threshold", type=float, help="Confidence threshold override")
    p.add_argument("--json", action="store_true", help="Print full evidence record as JSON")
    p.add_argument("--no-review", action="store_true", help="Skip the reasoning-model review")
    p.add_argument("photos", nargs="*", help="Photo files")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("scenarios", help="Run the bundled test scenarios (Deterministic Rules Regression)")
    p.add_argument("name", nargs="?", help="Run a single scenario")
    p.add_argument("--threshold", type=float, default=0.7)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_scenarios)

    p = sub.add_parser("evaluate", help="Run the 50-unit held-out vision model evaluation suite")
    p.add_argument("--run", action="store_true", help="Force re-running vision model on held-out units")
    p.add_argument("--limit", type=int, help="Limit number of units evaluated")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("integrate", help="Cross-Pod ecosystem integrations (Prep, Returns, Recovery)")
    p.add_argument("--pod", choices=["status", "prep", "returns", "recovery"], default="status", help="Pod to interact with")
    p.add_argument("--unit", help="Unit ID (e.g. UNIT-0005)")
    p.add_argument("--sku", help="SKU identifier")
    p.add_argument("--state", help="Observed return state (e.g. opened_unused, damaged)")
    p.add_argument("--fee-csv", help="Custom fee report CSV path for Recovery reconciliation")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_integrate)

    p = sub.add_parser("serve", help="Run the web app")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
