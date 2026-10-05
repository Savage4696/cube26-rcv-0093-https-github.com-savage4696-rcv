"""
Cross-Pod Integrations Package.
Connects Stage 01 (Receiving) with:
- Stage 02: Prep Manager (cube26-prp-0153)
- Stage 04: Returns Manager (cube-04-returns-manager)
- Stage 05: Recovery Manager (cube26-rcy-0077)
"""
from receiving_manager.integrations.prep import (
    PrepRequirement,
    PrepWorkOrder,
    create_prep_dispatch,
    derive_prep_requirements,
)
from receiving_manager.integrations.pack import (
    PackDetectedItem,
    PackOrderItem,
    PackVerdict,
    PackVerificationIssue,
    PackVerificationResult,
    create_pack_manifest_from_inbound,
    verify_outbound_pack,
)
from receiving_manager.integrations.returns import (
    LiabilityAssignment,
    ReturnAssessmentQuery,
    ReturnCorrelationResult,
    ReturnCorrelationStatus,
    correlate_return_with_inbound,
)
from receiving_manager.integrations.recovery import (
    ClaimTarget,
    EvidenceStance,
    FeeLineItem,
    ReconciledClaimLine,
    RecoveryReconciliationReport,
    parse_fee_report_csv,
    reconcile_fee_line,
    reconcile_fee_report,
)
from receiving_manager.integrations.service import (
    CrossPodIntegrationService,
    cross_pod_service,
)

__all__ = [
    "PrepRequirement",
    "PrepWorkOrder",
    "create_prep_dispatch",
    "derive_prep_requirements",
    "PackVerdict",
    "PackOrderItem",
    "PackDetectedItem",
    "PackVerificationIssue",
    "PackVerificationResult",
    "create_pack_manifest_from_inbound",
    "verify_outbound_pack",
    "LiabilityAssignment",
    "ReturnAssessmentQuery",
    "ReturnCorrelationResult",
    "ReturnCorrelationStatus",
    "correlate_return_with_inbound",
    "ClaimTarget",
    "EvidenceStance",
    "FeeLineItem",
    "ReconciledClaimLine",
    "RecoveryReconciliationReport",
    "parse_fee_report_csv",
    "reconcile_fee_line",
    "reconcile_fee_report",
    "CrossPodIntegrationService",
    "cross_pod_service",
]
