"""
Integration Adapter: Step 01 (Receiving Manager) -> Step 02 (Prep Manager)
Conforms to Prep Manager contract (cube26-prp-0153).

Translates inbound receiving observations into a prep work-order dispatch.
When receiving identifies damaged packaging, loose soft goods, liquids, or unlabelled units,
RCV generates a PrepDispatchInstruction instructing Prep Manager what rules and checks to apply.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class PrepRequirement(str, Enum):
    POLYBAG = "POLYBAG"
    SUFFOCATION_LABEL = "SUFFOCATION_WARNING_LABEL"
    FNSKU_RELABEL = "FNSKU_RELABELING"
    BUBBLE_WRAP = "BUBBLE_WRAP"
    TAPING_SEAL = "TAPING_AND_SEALING"
    REBOX = "REBOX_DAMAGED_CARTON"
    BARCODE_COVER = "COVER_MANUFACTURER_BARCODE"


class PrepDispatchPriority(str, Enum):
    ROUTINE = "ROUTINE"
    EXPEDITE = "EXPEDITE"
    HOLD_FOR_REVIEW = "HOLD_FOR_REVIEW"


class PrepWorkOrder(BaseModel):
    """Payload dispatched from Receiving (Stage 01) to Prep Manager (Stage 02)."""
    work_order_id: str
    unit_id: str
    organization_id: str
    sku: str
    po_number: Optional[str] = None
    inbound_record_id: str
    inbound_outcome: str
    inbound_captured_at: str
    required_prep: list[PrepRequirement]
    recommended_rulebook: str
    priority: PrepDispatchPriority
    operator_notes: str
    inbound_evidence_refs: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def derive_prep_requirements(
    sku: str,
    product_title: Optional[str] = None,
    carton_damage: str = "none",
    unit_damage: str = "none",
    quality_flags: Optional[list[str]] = None,
    spec_components: Optional[str] = None,
) -> tuple[list[PrepRequirement], str, PrepDispatchPriority, str]:
    """
    Deterministically deduces downstream prep requirements from inbound physical condition.
    """
    flags = quality_flags or []
    reqs: list[PrepRequirement] = []
    notes: list[str] = []
    priority = PrepDispatchPriority.ROUTINE
    title = (product_title or "").lower()
    sku_upper = sku.upper()

    # Rule 1: Damaged packaging needs rebox or taping
    if carton_damage in ("crushed", "crushing", "severe_tear", "punctured", "tears") or "damaged_carton" in flags:
        reqs.append(PrepRequirement.REBOX)
        reqs.append(PrepRequirement.TAPING_SEAL)
        notes.append("Inbound carton transit damage detected at dock; re-boxing or reinforced taping required before storage.")
        priority = PrepDispatchPriority.EXPEDITE

    # Rule 2: Soft goods, apparel, towels need polybagging + suffocation warning
    if any(k in title for k in ("towel", "cloth", "apparel", "shirt", "cotton", "leash")) or "TOWEL" in sku_upper or "LEASH" in sku_upper:
        if PrepRequirement.POLYBAG not in reqs:
            reqs.append(PrepRequirement.POLYBAG)
        if PrepRequirement.SUFFOCATION_LABEL not in reqs:
            reqs.append(PrepRequirement.SUFFOCATION_LABEL)
        notes.append("Loose textile/soft product requires transparent polybag with compliant suffocation warning.")

    # Rule 3: Fragile / glass / liquid needs bubble wrap and barcode covering
    if any(k in title for k in ("bottle", "candle", "lamp", "mug", "glass", "serum")) or any(k in sku_upper for k in ("BOTTLE", "CANDLE", "LAMP", "MUG", "SERUM")):
        if PrepRequirement.BUBBLE_WRAP not in reqs:
            reqs.append(PrepRequirement.BUBBLE_WRAP)
        if PrepRequirement.BARCODE_COVER not in reqs:
            reqs.append(PrepRequirement.BARCODE_COVER)
        notes.append("Breakable / liquid container requires protective cushioning and manufacturer barcode masking.")

    # Rule 4: Wrong or unreadable barcode at dock requires FNSKU relabeling
    if "wrong_barcode" in flags or "illegible_barcode" in flags or "wrong_colour" in flags:
        if PrepRequirement.FNSKU_RELABEL not in reqs:
            reqs.append(PrepRequirement.FNSKU_RELABEL)
        notes.append("Dock scan discrepancy requires FNSKU over-labelling.")
        priority = PrepDispatchPriority.HOLD_FOR_REVIEW

    # Default fallback if nothing triggered
    if not reqs:
        reqs.append(PrepRequirement.FNSKU_RELABEL)
        notes.append("Standard FBA receiving prep: apply unit FNSKU barcode.")

    rulebook = "standard_apparel_v1" if PrepRequirement.POLYBAG in reqs else "standard_hardlines_v1"
    if PrepRequirement.REBOX in reqs:
        rulebook = "exception_rebox_v1"

    return reqs, rulebook, priority, " | ".join(notes)


def create_prep_dispatch(
    unit_id: str,
    organization_id: str,
    sku: str,
    inbound_record_id: str,
    inbound_outcome: str,
    inbound_captured_at: str,
    product_title: Optional[str] = None,
    po_number: Optional[str] = None,
    carton_damage: str = "none",
    unit_damage: str = "none",
    quality_flags: Optional[list[str]] = None,
    photo_hashes: Optional[list[str]] = None,
) -> PrepWorkOrder:
    """
    Creates an official work-order dispatch packet to be handed off to Prep Manager.
    """
    reqs, rulebook, priority, notes = derive_prep_requirements(
        sku=sku,
        product_title=product_title,
        carton_damage=carton_damage,
        unit_damage=unit_damage,
        quality_flags=quality_flags,
    )
    
    return PrepWorkOrder(
        work_order_id=f"WO-PRP-{unit_id}",
        unit_id=unit_id,
        organization_id=organization_id,
        sku=sku,
        po_number=po_number,
        inbound_record_id=inbound_record_id,
        inbound_outcome=inbound_outcome,
        inbound_captured_at=inbound_captured_at,
        required_prep=reqs,
        recommended_rulebook=rulebook,
        priority=priority,
        operator_notes=notes,
        inbound_evidence_refs=photo_hashes or [],
    )
