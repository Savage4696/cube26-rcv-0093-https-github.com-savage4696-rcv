"""
Integration Adapter: Step 01 (Receiving Manager) -> Step 03 (Pack Manager)
Conforms to Pack Manager contract (cube26-pck-0168-varalakshmikonjeti).

Provides inbound packaging hierarchy, component bill-of-materials (BOM),
and pre-seal verification to outbound packing stations.
Prevents shipping wrong items, incomplete kits, or wrong quantities to buyers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class PackVerdict(str, Enum):
    SEAL = "seal"
    STOP_AND_FIX = "stop_and_fix"
    UNCERTAIN = "uncertain"


class PackOrderItem(BaseModel):
    sku: str
    quantity: int = Field(ge=1)
    description: Optional[str] = None
    expected_components: list[str] = Field(default_factory=list)


class PackDetectedItem(BaseModel):
    sku: str
    quantity: int = Field(ge=0)
    evidence: str


class PackVerificationIssue(BaseModel):
    type: Literal[
        "missing_item",
        "wrong_item",
        "extra_item",
        "quantity_mismatch",
        "uncertain",
    ]
    sku: Optional[str] = None
    expected_quantity: Optional[int] = None
    detected_quantity: Optional[int] = None
    evidence: str


class PackVerificationResult(BaseModel):
    """Canonical result conforming to cube26-pck-0168 schemas."""
    verdict: PackVerdict
    unit_id: Optional[str] = None
    inbound_record_id: Optional[str] = None
    expected_items: list[PackOrderItem]
    detected_items: list[PackDetectedItem]
    issues: list[PackVerificationIssue] = Field(default_factory=list)
    audit_notes: str = ""
    evaluated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def create_pack_manifest_from_inbound(
    inbound_record: dict[str, Any],
) -> list[PackOrderItem]:
    """
    Extracts the expected pack order items and component BOM from an inbound receiving record.
    """
    sku = inbound_record.get("sku") or "SKU-UNKNOWN"
    title = inbound_record.get("product_title") or ""
    qty = int(inbound_record.get("units_per_carton_counted") or inbound_record.get("units_per_carton_ordered") or 1)
    components_raw = inbound_record.get("spec_components") or ""

    components = []
    if isinstance(components_raw, str) and components_raw:
        components = [c.strip() for c in components_raw.split(";") if c.strip()]
    elif isinstance(components_raw, list):
        components = components_raw

    return [
        PackOrderItem(
            sku=sku,
            quantity=max(1, qty),
            description=title,
            expected_components=components,
        )
    ]


def verify_outbound_pack(
    expected_items: list[PackOrderItem],
    detected_items: list[PackDetectedItem],
    unit_id: Optional[str] = None,
    inbound_record_id: Optional[str] = None,
) -> PackVerificationResult:
    """
    Evaluates detected items in an open box before sealing against expected order lines.
    Replicates the deterministic verification engine of cube26-pck-0168.
    """
    issues: list[PackVerificationIssue] = []

    expected_map: dict[str, int] = {item.sku.upper(): item.quantity for item in expected_items}
    detected_map: dict[str, int] = {}
    detected_evidence: dict[str, str] = {}

    for d in detected_items:
        key = d.sku.upper()
        detected_map[key] = detected_map.get(key, 0) + d.quantity
        detected_evidence[key] = d.evidence

    # Check for missing items and quantity mismatches
    for sku, exp_qty in expected_map.items():
        det_qty = detected_map.get(sku, 0)
        if det_qty == 0:
            issues.append(
                PackVerificationIssue(
                    type="missing_item",
                    sku=sku,
                    expected_quantity=exp_qty,
                    detected_quantity=0,
                    evidence=f"Expected {exp_qty} of {sku} in outbound carton, but item was not detected in pre-seal photo.",
                )
            )
        elif det_qty != exp_qty:
            issues.append(
                PackVerificationIssue(
                    type="quantity_mismatch",
                    sku=sku,
                    expected_quantity=exp_qty,
                    detected_quantity=det_qty,
                    evidence=f"Quantity mismatch for {sku}: expected {exp_qty}, detected {det_qty}.",
                )
            )

    # Check for unexpected or wrong items in the box
    for sku, det_qty in detected_map.items():
        if sku not in expected_map:
            issues.append(
                PackVerificationIssue(
                    type="wrong_item",
                    sku=sku,
                    expected_quantity=0,
                    detected_quantity=det_qty,
                    evidence=f"Unexpected item {sku} detected in carton ({det_qty} units). Possible picker pick-bin mix-up.",
                )
            )

    # Final verdict
    if not issues:
        verdict = PackVerdict.SEAL
        audit = "VERIFICATION PASS: All items and quantities matched order specifications. Safe to apply carton tape and seal."
    else:
        verdict = PackVerdict.STOP_AND_FIX
        audit = f"STOP AND FIX: {len(issues)} issue(s) detected before carton seal. Halt conveyor and correct contents."

    return PackVerificationResult(
        verdict=verdict,
        unit_id=unit_id,
        inbound_record_id=inbound_record_id,
        expected_items=expected_items,
        detected_items=detected_items,
        issues=issues,
        audit_notes=audit,
    )
