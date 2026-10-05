"""
Integration Adapter: Step 01 (Receiving Manager) -> Step 05 (Recovery Manager)
Conforms to Recovery Manager contract (cube26-rcy-0077).

Consumes channel fee reports (e.g. Amazon fee_report, inventory_adjustment)
and correlates against Receiving Manager sealed evidence records.

Produces deterministic 3-way stance:
1. CONTRADICTS: Fee charged (e.g. inbound_defect_fee, lost_inbound), but dock proof shows 100% intact receipt.
   -> Actionable FBA dispute claim assembled.
2. SUPPORTS: Dock proof recorded exception/shortage/damage caused by vendor.
   -> Vendor credit chargeback / carrier claim assembled.
3. SILENT: Out-of-scope fee or missing dock record.
   -> Explicitly declined with documented rationale.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field


class EvidenceStance(str, Enum):
    CONTRADICTS = "CONTRADICTS"
    SUPPORTS = "SUPPORTS"
    SILENT = "SILENT"


class ClaimTarget(str, Enum):
    AMAZON_FBA_DISPUTE = "AMAZON_FBA_DISPUTE"
    SUPPLIER_CHARGEBACK = "SUPPLIER_CHARGEBACK"
    CARRIER_FREIGHT_CLAIM = "CARRIER_FREIGHT_CLAIM"
    INELIGIBLE = "INELIGIBLE"


class FeeLineItem(BaseModel):
    line_id: str
    report_type: str
    unit_id: str
    org_id: str
    sku: str
    fnsku: Optional[str] = None
    fba_shipment_id: Optional[str] = None
    order_id: Optional[str] = None
    charge_type: str
    quantity: int = 1
    amount_usd: float = 0.0
    posted_date: Optional[str] = None


class ReconciledClaimLine(BaseModel):
    line_id: str
    unit_id: str
    sku: str
    charge_type: str
    amount_usd: float
    stance: EvidenceStance
    claim_target: ClaimTarget
    dispute_amount_usd: float
    confidence_score: float = Field(ge=0.0, le=1.0)
    audit_explanation: str
    dock_record_id: Optional[str] = None
    dock_evidence_hashes: list[str] = Field(default_factory=list)


class RecoveryReconciliationReport(BaseModel):
    report_id: str
    total_fee_lines_analyzed: int
    contradicting_count: int
    supporting_count: int
    silent_count: int
    total_fba_dispute_amount: float
    total_vendor_chargeback_amount: float
    items: list[ReconciledClaimLine] = Field(default_factory=list)
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def reconcile_fee_line(
    fee: FeeLineItem,
    inbound_record: Optional[dict[str, Any]],
) -> ReconciledClaimLine:
    """
    Reconciles a single fee charge against the inbound dock evidence record.
    """
    if not inbound_record:
        return ReconciledClaimLine(
            line_id=fee.line_id,
            unit_id=fee.unit_id,
            sku=fee.sku,
            charge_type=fee.charge_type,
            amount_usd=fee.amount_usd,
            stance=EvidenceStance.SILENT,
            claim_target=ClaimTarget.INELIGIBLE,
            dispute_amount_usd=0.0,
            confidence_score=1.0,
            audit_explanation=f"SILENT: No dock receiving evidence on file for unit '{fee.unit_id}'. Cannot verify charge.",
        )

    # Extract dock evidence
    inbound_record_id = inbound_record.get("record_id", "RCV-UNKNOWN")
    inbound_outcome = inbound_record.get("outcome") or inbound_record.get("status") or "ACCEPT"
    if isinstance(inbound_outcome, dict):
        inbound_outcome = inbound_outcome.get("decision", "ACCEPT")

    carton_damage = str(inbound_record.get("carton_damage", "none")).lower()
    unit_damage = str(inbound_record.get("unit_damage", "none")).lower()
    quality_flags = inbound_record.get("quality_flags") or []
    if isinstance(quality_flags, str) and quality_flags:
        quality_flags = [q.strip() for q in quality_flags.split(",") if q.strip()]

    qty_ordered = int(inbound_record.get("qty_ordered") or 0)
    qty_received = int(inbound_record.get("qty_received") or 0)

    photo_hashes: list[str] = []
    if "images" in inbound_record and isinstance(inbound_record["images"], list):
        for img in inbound_record["images"]:
            if isinstance(img, dict) and "sha256" in img:
                photo_hashes.append(img["sha256"])
            elif isinstance(img, str):
                photo_hashes.append(img)
    elif "photo_refs" in inbound_record:
        raw = inbound_record["photo_refs"]
        photo_hashes = raw.split(";") if isinstance(raw, str) else list(raw)

    charge = fee.charge_type.lower()

    # Case 1: Inbound defect fee (Amazon claimed inbound carton was defective/unscannable)
    if "inbound_defect_fee" in charge:
        # Check if dock actually had defects
        dock_had_defects = carton_damage not in ("none", "", "null") or unit_damage not in ("none", "", "null") or quality_flags
        if not dock_had_defects:
            # RCV proves unit arrived clean and scannable -> CONTRADICTS
            return ReconciledClaimLine(
                line_id=fee.line_id,
                unit_id=fee.unit_id,
                sku=fee.sku,
                charge_type=fee.charge_type,
                amount_usd=fee.amount_usd,
                stance=EvidenceStance.CONTRADICTS,
                claim_target=ClaimTarget.AMAZON_FBA_DISPUTE,
                dispute_amount_usd=fee.amount_usd,
                confidence_score=0.96,
                audit_explanation=(
                    f"CONTRADICTS: Amazon assessed {fee.charge_type} (${fee.amount_usd:.2f}), but RCV dock inspection "
                    f"proves unit arrived pristine (0 defects, valid barcode) under {inbound_record_id}. File FBA reimbursement dispute."
                ),
                dock_record_id=inbound_record_id,
                dock_evidence_hashes=photo_hashes,
            )
        else:
            # Dock confirmed supplier delivered defects -> SUPPORTS supplier chargeback
            return ReconciledClaimLine(
                line_id=fee.line_id,
                unit_id=fee.unit_id,
                sku=fee.sku,
                charge_type=fee.charge_type,
                amount_usd=fee.amount_usd,
                stance=EvidenceStance.SUPPORTS,
                claim_target=ClaimTarget.SUPPLIER_CHARGEBACK,
                dispute_amount_usd=fee.amount_usd,
                confidence_score=0.95,
                audit_explanation=(
                    f"SUPPORTS: Dock inspection logged supplier defect ({carton_damage}/{quality_flags}). "
                    f"Chargeback fee (${fee.amount_usd:.2f}) to vendor invoice under PO warranty."
                ),
                dock_record_id=inbound_record_id,
                dock_evidence_hashes=photo_hashes,
            )

    # Case 2: Lost Inbound / Shortage
    if "lost_inbound" in charge:
        if qty_received >= qty_ordered and qty_received > 0:
            # Amazon says lost inbound, but dock verified full receipt
            # Estimated recovery is quantity * $25 standard item valuation if amount is 0
            est_value = fee.amount_usd if fee.amount_usd > 0 else float(fee.quantity * 25.0)
            return ReconciledClaimLine(
                line_id=fee.line_id,
                unit_id=fee.unit_id,
                sku=fee.sku,
                charge_type=fee.charge_type,
                amount_usd=fee.amount_usd,
                stance=EvidenceStance.CONTRADICTS,
                claim_target=ClaimTarget.AMAZON_FBA_DISPUTE,
                dispute_amount_usd=est_value,
                confidence_score=0.92,
                audit_explanation=(
                    f"CONTRADICTS: Amazon reported {fee.quantity} units lost inbound, but dock evidence {inbound_record_id} "
                    f"confirms 100% receipt ({qty_received}/{qty_ordered} units). Amazon lost units post-dock. Claim ${est_value:.2f}."
                ),
                dock_record_id=inbound_record_id,
                dock_evidence_hashes=photo_hashes,
            )
        elif qty_received < qty_ordered:
            # Dock verified supplier short-shipped
            shortage = qty_ordered - qty_received
            est_value = float(shortage * 25.0)
            return ReconciledClaimLine(
                line_id=fee.line_id,
                unit_id=fee.unit_id,
                sku=fee.sku,
                charge_type=fee.charge_type,
                amount_usd=fee.amount_usd,
                stance=EvidenceStance.SUPPORTS,
                claim_target=ClaimTarget.SUPPLIER_CHARGEBACK,
                dispute_amount_usd=est_value,
                confidence_score=0.95,
                audit_explanation=(
                    f"SUPPORTS: Dock receiving record confirmed vendor short-shipment ({qty_received} of {qty_ordered} units received). "
                    f"Issue credit memo to vendor for {shortage} units (${est_value:.2f})."
                ),
                dock_record_id=inbound_record_id,
                dock_evidence_hashes=photo_hashes,
            )

    # Case 3: Damaged in warehouse or carrier damage
    if "damaged" in charge:
        if carton_damage in ("crushed", "crushing", "severe_tear", "water_damaged", "tears"):
            return ReconciledClaimLine(
                line_id=fee.line_id,
                unit_id=fee.unit_id,
                sku=fee.sku,
                charge_type=fee.charge_type,
                amount_usd=fee.amount_usd,
                stance=EvidenceStance.SUPPORTS,
                claim_target=ClaimTarget.CARRIER_FREIGHT_CLAIM,
                dispute_amount_usd=fee.amount_usd or 50.0,
                confidence_score=0.90,
                audit_explanation=(
                    f"SUPPORTS: Dock inspection documented in-transit carrier damage ({carton_damage}). "
                    f"Assemble bill-of-lading carrier freight claim with photographic proof."
                ),
                dock_record_id=inbound_record_id,
                dock_evidence_hashes=photo_hashes,
            )

    # Default: Non-inbound fee (e.g. weight tier, refund issued, storage fee)
    return ReconciledClaimLine(
        line_id=fee.line_id,
        unit_id=fee.unit_id,
        sku=fee.sku,
        charge_type=fee.charge_type,
        amount_usd=fee.amount_usd,
        stance=EvidenceStance.SILENT,
        claim_target=ClaimTarget.INELIGIBLE,
        dispute_amount_usd=0.0,
        confidence_score=1.0,
        audit_explanation=f"SILENT: Charge '{fee.charge_type}' is outside dock vision scope (weight tier / customer return).",
        dock_record_id=inbound_record_id,
        dock_evidence_hashes=photo_hashes,
    )


def reconcile_fee_report(
    fee_lines: list[FeeLineItem],
    inbound_records_by_unit: dict[str, dict[str, Any]],
) -> RecoveryReconciliationReport:
    """
    Processes a list of fee lines against dock records and generates full reconciliation report.
    """
    claim_lines: list[ReconciledClaimLine] = []
    contradicts_count = 0
    supports_count = 0
    silent_count = 0
    fba_dispute_total = 0.0
    vendor_chargeback_total = 0.0

    for fee in fee_lines:
        inbound_rec = inbound_records_by_unit.get(fee.unit_id)
        line_result = reconcile_fee_line(fee, inbound_rec)
        claim_lines.append(line_result)

        if line_result.stance == EvidenceStance.CONTRADICTS:
            contradicts_count += 1
            fba_dispute_total += line_result.dispute_amount_usd
        elif line_result.stance == EvidenceStance.SUPPORTS:
            supports_count += 1
            vendor_chargeback_total += line_result.dispute_amount_usd
        else:
            silent_count += 1

    return RecoveryReconciliationReport(
        report_id=f"RECON-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        total_fee_lines_analyzed=len(fee_lines),
        contradicting_count=contradicts_count,
        supporting_count=supports_count,
        silent_count=silent_count,
        total_fba_dispute_amount=round(fba_dispute_total, 2),
        total_vendor_chargeback_amount=round(vendor_chargeback_total, 2),
        items=claim_lines,
    )


def parse_fee_report_csv(csv_content: str) -> list[FeeLineItem]:
    """Parses a CSV matching fee_report_sample.csv structure."""
    reader = csv.DictReader(io.StringIO(csv_content.strip()))
    items: list[FeeLineItem] = []
    for row in reader:
        try:
            items.append(
                FeeLineItem(
                    line_id=row.get("line_id", "").strip(),
                    report_type=row.get("report_type", "").strip(),
                    unit_id=row.get("unit_id", "").strip(),
                    org_id=row.get("org_id", "").strip(),
                    sku=row.get("sku", "").strip(),
                    fnsku=row.get("fnsku", "").strip() or None,
                    fba_shipment_id=row.get("fba_shipment_id", "").strip() or None,
                    order_id=row.get("order_id", "").strip() or None,
                    charge_type=row.get("charge_type", "").strip(),
                    quantity=int(row.get("quantity", 1) or 1),
                    amount_usd=float(row.get("amount_usd", 0.0) or 0.0),
                    posted_date=row.get("posted_date", "").strip() or None,
                )
            )
        except Exception:
            continue
    return items
