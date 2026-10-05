"""
Unified Cross-Pod Service orchestrating:
- Stage 01: Receiving Manager (RCV)
- Stage 02: Prep Manager (PRP) [cube26-prp-0153]
- Stage 04: Returns Manager (RTM) [cube-04-returns-manager]
- Stage 05: Recovery Manager (RCY) [cube26-rcy-0077]
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Optional

from receiving_manager.integrations.prep import (
    PrepWorkOrder,
    create_prep_dispatch,
)
from receiving_manager.integrations.returns import (
    ReturnAssessmentQuery,
    ReturnCorrelationResult,
    correlate_return_with_inbound,
)
from receiving_manager.integrations.recovery import (
    RecoveryReconciliationReport,
    parse_fee_report_csv,
    reconcile_fee_report,
)


class CrossPodIntegrationService:
    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or Path(__file__).resolve().parent.parent.parent / "data"
        self._receiving_cache: dict[str, dict[str, Any]] = {}
        self._fee_sample_path = self.data_dir / "fee_report_sample.csv"
        self._receiving_sample_path = self.data_dir / "receiving_sample.csv"
        self._load_receiving_cache()

    def _load_receiving_cache(self) -> None:
        """Loads canonical receiving records by unit_id from data/receiving_sample.csv."""
        if not self._receiving_sample_path.exists():
            return

        try:
            with open(self._receiving_sample_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    uid = row.get("unit_id")
                    if uid:
                        self._receiving_cache[uid.strip()] = row
        except Exception:
            pass

    def get_unit_inbound_record(self, unit_id: str) -> Optional[dict[str, Any]]:
        """Retrieves raw or enriched inbound dock evidence for a given unit."""
        return self._receiving_cache.get(unit_id.strip())

    def dispatch_to_prep(
        self,
        unit_id: str,
        custom_sku: Optional[str] = None,
        custom_org_id: Optional[str] = "org_demo_alpha",
    ) -> PrepWorkOrder:
        """Generates a Prep Manager work order from an inbound unit record."""
        rec = self.get_unit_inbound_record(unit_id) or {}
        sku = custom_sku or rec.get("sku", "SKU-UNKNOWN")
        org_id = rec.get("org_id", custom_org_id)
        record_id = rec.get("record_id", f"RCV-{unit_id}")
        captured_at = rec.get("captured_at", "")
        title = rec.get("product_title", "")
        po_num = rec.get("po_number", "")
        carton_damage = rec.get("carton_damage", "none")
        unit_damage = rec.get("unit_damage", "none")
        flags = rec.get("quality_flags", "")
        flag_list = [f.strip() for f in flags.split(",") if f.strip()] if isinstance(flags, str) else []
        photo_refs = rec.get("photo_refs", "").split(";") if rec.get("photo_refs") else []

        return create_prep_dispatch(
            unit_id=unit_id,
            organization_id=org_id,
            sku=sku,
            inbound_record_id=record_id,
            inbound_outcome="ACCEPT" if carton_damage == "none" else "EXCEPTION",
            inbound_captured_at=captured_at,
            product_title=title,
            po_number=po_num,
            carton_damage=carton_damage,
            unit_damage=unit_damage,
            quality_flags=flag_list,
            photo_hashes=photo_refs,
        )

    def correlate_customer_return(
        self,
        query: ReturnAssessmentQuery,
    ) -> ReturnCorrelationResult:
        """Cross-checks an incoming customer return against historical dock evidence."""
        inbound_record = self.get_unit_inbound_record(query.unit_id)
        return correlate_return_with_inbound(query, inbound_record)

    def reconcile_recovery_claims(
        self,
        fee_report_csv_text: Optional[str] = None,
    ) -> RecoveryReconciliationReport:
        """Reconciles fee reports against dock evidence records."""
        if fee_report_csv_text:
            fee_lines = parse_fee_report_csv(fee_report_csv_text)
        elif self._fee_sample_path.exists():
            with open(self._fee_sample_path, "r", encoding="utf-8") as f:
                fee_lines = parse_fee_report_csv(f.read())
        else:
            fee_lines = []

        return reconcile_fee_report(fee_lines, self._receiving_cache)

    def get_ecosystem_status(self) -> dict[str, Any]:
        """Provides status and connectivity metadata for all 5 CUBE pods."""
        return {
            "hub": "CUBE 2026 Inbound Receiving Manager (Stage 01)",
            "evidence_contract_version": "1.1",
            "active_pods": {
                "RCV": {
                    "stage": "01",
                    "name": "Receiving Manager",
                    "repo": "Savage4696/RCV",
                    "status": "ACTIVE_PRIMARY",
                    "role": "Dock visual inspection, PO matching, sealed SHA-256 evidence generation",
                },
                "PRP": {
                    "stage": "02",
                    "name": "Prep Manager",
                    "repo": "maithripagidi3284-coder/cube26-prp-0153",
                    "status": "INTEGRATED_HANDOFF",
                    "role": "Downstream compliance: polybagging, suffocation warnings, FNSKU re-labeling, re-boxing",
                },
                "RTM": {
                    "stage": "04",
                    "name": "Returns Manager",
                    "repo": "jeevanreddy29/cube-04-returns-manager",
                    "status": "INTEGRATED_PROVENANCE",
                    "role": "Customer return grading, switch fraud detection, dock-vs-return defect liability",
                },
                "RCY": {
                    "stage": "05",
                    "name": "Recovery Manager",
                    "repo": "pia-21/cube26-rcy-0077",
                    "status": "INTEGRATED_CLAIMS",
                    "role": "Fee contradiction matching, FBA reimbursement disputes, vendor chargeback credit memos",
                },
            },
            "cached_inbound_units": len(self._receiving_cache),
            "fee_sample_available": self._fee_sample_path.exists(),
        }


# Global singleton instance
cross_pod_service = CrossPodIntegrationService()
