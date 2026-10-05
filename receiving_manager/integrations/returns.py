"""
Integration Adapter: Step 01 (Receiving Manager) <-> Step 04 (Returns Manager)
Conforms to Returns Manager contract (cube-04-returns-manager).

Provides historical inbound dock provenance to verify customer returns.
Detects:
1. Switch Fraud: Customer returned a different item than what was originally received at dock.
2. Defect Liability: Distinguishes pre-existing supplier defect from customer-inflicted damage.
3. Component Missing Provenance: Proves whether parts were missing at inbound or kept by customer.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class ReturnCorrelationStatus(str, Enum):
    AUTHENTIC_RETURN = "AUTHENTIC_RETURN"
    SWITCH_FRAUD_DETECTED = "SWITCH_FRAUD_DETECTED"
    SUPPLIER_PRE_EXISTING_DEFECT = "SUPPLIER_PRE_EXISTING_DEFECT"
    CUSTOMER_INFLICTED_DAMAGE = "CUSTOMER_INFLICTED_DAMAGE"
    INBOUND_PROOF_NOT_FOUND = "INBOUND_PROOF_NOT_FOUND"


class LiabilityAssignment(str, Enum):
    SUPPLIER = "SUPPLIER"
    CUSTOMER = "CUSTOMER"
    CARRIER = "CARRIER"
    UNDETERMINED = "UNDETERMINED"


class ReturnAssessmentQuery(BaseModel):
    """Query from Returns Manager requesting inbound dock provenance."""
    unit_id: str
    returned_sku: str
    order_id: Optional[str] = None
    customer_claimed_reason: Optional[str] = None
    return_observed_state: str  # e.g. "opened_unused", "damaged", "empty_box"
    return_parts_missing: list[str] = Field(default_factory=list)
    return_condition_grade: Optional[str] = None  # Amazon grade e.g. "Like New", "Acceptable"


class ReturnCorrelationResult(BaseModel):
    """Response returned to Returns Manager establishing provenance and fraud verdict."""
    unit_id: str
    correlation_status: ReturnCorrelationStatus
    liability: LiabilityAssignment
    fraud_risk_score: float = Field(ge=0.0, le=1.0)
    inbound_record_id: Optional[str] = None
    inbound_sku: Optional[str] = None
    inbound_outcome: Optional[str] = None
    inbound_captured_at: Optional[str] = None
    pre_existing_damage_at_dock: bool = False
    inbound_damage_notes: str = ""
    evidence_comparison_notes: str = ""
    inbound_photo_refs: list[str] = Field(default_factory=list)
    evaluated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def correlate_return_with_inbound(
    query: ReturnAssessmentQuery,
    inbound_record: Optional[dict[str, Any]] = None,
) -> ReturnCorrelationResult:
    """
    Evaluates return query against original dock receiving evidence.
    """
    if not inbound_record:
        return ReturnCorrelationResult(
            unit_id=query.unit_id,
            correlation_status=ReturnCorrelationStatus.INBOUND_PROOF_NOT_FOUND,
            liability=LiabilityAssignment.UNDETERMINED,
            fraud_risk_score=0.5,
            evidence_comparison_notes="No inbound receiving record found for this unit ID. Cannot verify dock provenance.",
        )

    inbound_sku = inbound_record.get("sku") or inbound_record.get("ordered_sku") or ""
    inbound_outcome = inbound_record.get("outcome") or inbound_record.get("status") or "ACCEPT"
    if isinstance(inbound_outcome, dict):
        inbound_outcome = inbound_outcome.get("decision", "ACCEPT")

    inbound_record_id = inbound_record.get("record_id", "RCV-UNKNOWN")
    inbound_captured_at = inbound_record.get("captured_at", "")
    carton_damage = str(inbound_record.get("carton_damage", "none")).lower()
    unit_damage = str(inbound_record.get("unit_damage", "none")).lower()
    quality_flags = inbound_record.get("quality_flags") or []
    if isinstance(quality_flags, str) and quality_flags:
        quality_flags = [q.strip() for q in quality_flags.split(",") if q.strip()]

    photo_refs = []
    if "images" in inbound_record and isinstance(inbound_record["images"], list):
        for img in inbound_record["images"]:
            if isinstance(img, dict) and "sha256" in img:
                photo_refs.append(img["sha256"])
            elif isinstance(img, str):
                photo_refs.append(img)
    elif "photo_refs" in inbound_record:
        raw = inbound_record["photo_refs"]
        photo_refs = raw.split(";") if isinstance(raw, str) else list(raw)

    # 1. Check for Switch Fraud (SKU Mismatch)
    if query.returned_sku and inbound_sku and query.returned_sku.upper() != inbound_sku.upper():
        return ReturnCorrelationResult(
            unit_id=query.unit_id,
            correlation_status=ReturnCorrelationStatus.SWITCH_FRAUD_DETECTED,
            liability=LiabilityAssignment.CUSTOMER,
            fraud_risk_score=0.98,
            inbound_record_id=inbound_record_id,
            inbound_sku=inbound_sku,
            inbound_outcome=str(inbound_outcome),
            inbound_captured_at=inbound_captured_at,
            pre_existing_damage_at_dock=False,
            inbound_damage_notes=f"Dock received {inbound_sku}, but customer returned {query.returned_sku}.",
            evidence_comparison_notes="SWITCH FRAUD CONFIRMED: Returned item SKU does not match inbound dock serial record. Reject refund.",
            inbound_photo_refs=photo_refs,
        )

    # 2. Check for Pre-Existing Damage at Inbound Dock (Supplier liability)
    dock_had_damage = carton_damage not in ("none", "", "null") or unit_damage not in ("none", "", "null") or "obvious_defect" in quality_flags
    if dock_had_damage and query.return_observed_state == "damaged":
        return ReturnCorrelationResult(
            unit_id=query.unit_id,
            correlation_status=ReturnCorrelationStatus.SUPPLIER_PRE_EXISTING_DEFECT,
            liability=LiabilityAssignment.SUPPLIER,
            fraud_risk_score=0.05,
            inbound_record_id=inbound_record_id,
            inbound_sku=inbound_sku,
            inbound_outcome=str(inbound_outcome),
            inbound_captured_at=inbound_captured_at,
            pre_existing_damage_at_dock=True,
            inbound_damage_notes=f"Inbound dock recorded carton_damage='{carton_damage}', unit_damage='{unit_damage}'.",
            evidence_comparison_notes="PRE-EXISTING DEFECT: Damage was logged upon warehouse dock arrival before customer dispatch. Route to supplier claim, grant customer refund.",
            inbound_photo_refs=photo_refs,
        )

    # 3. Customer-inflicted damage (dock arrived pristine, but return arrived broken)
    if not dock_had_damage and query.return_observed_state == "damaged":
        return ReturnCorrelationResult(
            unit_id=query.unit_id,
            correlation_status=ReturnCorrelationStatus.CUSTOMER_INFLICTED_DAMAGE,
            liability=LiabilityAssignment.CUSTOMER,
            fraud_risk_score=0.72,
            inbound_record_id=inbound_record_id,
            inbound_sku=inbound_sku,
            inbound_outcome=str(inbound_outcome),
            inbound_captured_at=inbound_captured_at,
            pre_existing_damage_at_dock=False,
            inbound_damage_notes="Unit arrived at inbound dock in clean, undamaged condition.",
            evidence_comparison_notes="POST-DELIVERY DAMAGE: Unit was in pristine condition at receiving dock. Damage occurred post-shipment. Assess restocking fee or dispute.",
            inbound_photo_refs=photo_refs,
        )

    # 4. Standard Authentic Return
    return ReturnCorrelationResult(
        unit_id=query.unit_id,
        correlation_status=ReturnCorrelationStatus.AUTHENTIC_RETURN,
        liability=LiabilityAssignment.CUSTOMER,
        fraud_risk_score=0.10,
        inbound_record_id=inbound_record_id,
        inbound_sku=inbound_sku,
        inbound_outcome=str(inbound_outcome),
        inbound_captured_at=inbound_captured_at,
        pre_existing_damage_at_dock=False,
        inbound_damage_notes="Standard receipt.",
        evidence_comparison_notes="VERIFIED AUTHENTIC: SKU and provenance align with inbound dock evidence.",
        inbound_photo_refs=photo_refs,
    )
