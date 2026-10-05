from __future__ import annotations

from fastapi.testclient import TestClient

from receiving_manager.api import app
from receiving_manager.integrations import (
    ClaimTarget,
    EvidenceStance,
    LiabilityAssignment,
    PrepRequirement,
    ReturnAssessmentQuery,
    ReturnCorrelationStatus,
    correlate_return_with_inbound,
    create_prep_dispatch,
    derive_prep_requirements,
    parse_fee_report_csv,
    reconcile_fee_report,
)


def test_prep_integration_derives_correct_requirements():
    # Damaged carton triggers rebox and taping
    reqs, rulebook, priority, notes = derive_prep_requirements(
        sku="SKU-PUZZLE-500",
        product_title="Jigsaw Puzzle",
        carton_damage="crushed",
    )
    assert PrepRequirement.REBOX in reqs
    assert PrepRequirement.TAPING_SEAL in reqs
    assert priority.value == "EXPEDITE"

    # Apparel / towel triggers polybag and suffocation warning
    reqs2, rulebook2, priority2, notes2 = derive_prep_requirements(
        sku="SKU-TOWEL-BLU",
        product_title="Cotton Bath Towel",
        carton_damage="none",
    )
    assert PrepRequirement.POLYBAG in reqs2
    assert PrepRequirement.SUFFOCATION_LABEL in reqs2

    # Breakables / bottles trigger bubble wrap
    reqs3, rulebook3, priority3, notes3 = derive_prep_requirements(
        sku="SKU-BOTTLE-750",
        product_title="Steel Water Bottle",
        carton_damage="none",
    )
    assert PrepRequirement.BUBBLE_WRAP in reqs3


def test_prep_dispatch_creation():
    dispatch = create_prep_dispatch(
        unit_id="UNIT-0005",
        organization_id="org_demo_alpha",
        sku="SKU-LEASH-6FT",
        inbound_record_id="RCV-0005",
        inbound_outcome="EXCEPTION",
        inbound_captured_at="2026-06-09T07:54:00Z",
        product_title="Nylon Dog Leash",
        carton_damage="tears",
    )
    assert dispatch.unit_id == "UNIT-0005"
    assert PrepRequirement.REBOX in dispatch.required_prep
    assert PrepRequirement.POLYBAG in dispatch.required_prep
    assert dispatch.priority.value == "EXPEDITE"


def test_returns_integration_detects_switch_fraud():
    inbound_rec = {
        "record_id": "RCV-0010",
        "sku": "SKU-LAMP-LED",
        "carton_damage": "none",
        "unit_damage": "none",
    }
    query = ReturnAssessmentQuery(
        unit_id="UNIT-0010",
        returned_sku="SKU-CANDLE-3",  # Mismatched SKU
        return_observed_state="opened_unused",
    )
    res = correlate_return_with_inbound(query, inbound_rec)
    assert res.correlation_status == ReturnCorrelationStatus.SWITCH_FRAUD_DETECTED
    assert res.liability == LiabilityAssignment.CUSTOMER
    assert res.fraud_risk_score >= 0.9


def test_returns_integration_detects_pre_existing_damage():
    inbound_rec = {
        "record_id": "RCV-0003",
        "sku": "SKU-PUZZLE-500",
        "carton_damage": "crushing",
        "unit_damage": "uncertain",
    }
    query = ReturnAssessmentQuery(
        unit_id="UNIT-0003",
        returned_sku="SKU-PUZZLE-500",
        return_observed_state="damaged",
    )
    res = correlate_return_with_inbound(query, inbound_rec)
    assert res.correlation_status == ReturnCorrelationStatus.SUPPLIER_PRE_EXISTING_DEFECT
    assert res.liability == LiabilityAssignment.SUPPLIER
    assert res.pre_existing_damage_at_dock is True


def test_recovery_reconciliation():
    sample_csv = """line_id,report_type,unit_id,org_id,sku,fnsku,fba_shipment_id,order_id,charge_type,quantity,amount_usd,posted_date
FEE-0014-1,fee_report,UNIT-0014,org_demo_alpha,SKU-LAMP-LED,X0014,FBA-100,,inbound_defect_fee,1,2.00,2026-07-18
FEE-0003-1,inventory_adjustment,UNIT-0003,org_demo_bravo,SKU-PUZZLE-500,X0003,FBA-100,,lost_inbound,4,0.00,2026-06-14
FEE-9999-1,fee_report,UNIT-9999,org_demo_alpha,SKU-UNKNOWN,,,ORD-999,fulfilment_fee_weight_tier,1,4.50,2026-06-20
"""
    fees = parse_fee_report_csv(sample_csv)
    assert len(fees) == 3

    dock_records = {
        "UNIT-0014": {
            "record_id": "RCV-0014",
            "sku": "SKU-LAMP-LED",
            "carton_damage": "none",
            "unit_damage": "none",
            "quality_flags": "",
            "qty_ordered": 24,
            "qty_received": 24,
        },
        "UNIT-0003": {
            "record_id": "RCV-0003",
            "sku": "SKU-PUZZLE-500",
            "carton_damage": "crushing",
            "unit_damage": "none",
            "quality_flags": "",
            "qty_ordered": 48,
            "qty_received": 44,  # short 4 units
        }
    }

    report = reconcile_fee_report(fees, dock_records)
    assert report.total_fee_lines_analyzed == 3
    assert report.contradicting_count >= 1
    assert report.supporting_count >= 1
    assert report.silent_count == 1

    # Check the contradiction on UNIT-0014
    fba_line = next(i for i in report.items if i.line_id == "FEE-0014-1")
    assert fba_line.stance == EvidenceStance.CONTRADICTS
    assert fba_line.claim_target == ClaimTarget.AMAZON_FBA_DISPUTE
    assert fba_line.dispute_amount_usd == 2.00

    # Check vendor support on UNIT-0003
    sup_line = next(i for i in report.items if i.line_id == "FEE-0003-1")
    assert sup_line.stance == EvidenceStance.SUPPORTS
    assert sup_line.claim_target == ClaimTarget.SUPPLIER_CHARGEBACK


def test_api_integrations_endpoints():
    client = TestClient(app)

    # 1. Ecosystem status
    res = client.get("/api/integrations/status")
    assert res.status_code == 200
    data = res.json()
    assert "active_pods" in data
    assert "PRP" in data["active_pods"]
    assert "RTM" in data["active_pods"]
    assert "RCY" in data["active_pods"]

    # 2. Prep dispatch
    res = client.post("/api/integrations/prep/dispatch", data={"unit_id": "UNIT-0005"})
    assert res.status_code == 200
    pdata = res.json()
    assert pdata["unit_id"] == "UNIT-0005"
    assert "required_prep" in pdata

    # 3. Returns correlation
    res = client.get("/api/integrations/returns/correlate/UNIT-0003")
    assert res.status_code == 200
    rdata = res.json()
    assert rdata["unit_id"] == "UNIT-0003"
    assert "correlation_status" in rdata

    # 4. Recovery reconciliation
    res = client.get("/api/integrations/recovery/reconcile")
    assert res.status_code == 200
    recdata = res.json()
    assert recdata["total_fee_lines_analyzed"] > 0
    assert recdata["contradicting_count"] > 0
