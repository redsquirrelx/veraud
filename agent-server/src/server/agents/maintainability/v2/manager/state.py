"""Linear audit state retaining original receipts and deterministic projections."""

from typing import TypedDict

from server.contracts.audit import Consumption

from .schemas import (
    AssessmentSynthesis,
    AuditIssue,
    AuditPlan,
    AuditResult,
    CollectedAssessment,
    CoordinatorCapability,
    CoordinatorExecutionRecord,
    MaintainabilityRequest,
)


class MaintainabilityManagerState(TypedDict, total=False):
    request: MaintainabilityRequest
    repository_id: str
    commit: str | None
    snapshot_hash: str
    coordinator_catalog: list[CoordinatorCapability]
    plan: AuditPlan | None
    limitations: list[str]
    termination_reason: str
    consumption: Consumption
    coordinator_results: list[CoordinatorExecutionRecord]
    delegation_status: str
    assessments: list[CollectedAssessment]
    synthesis: AssessmentSynthesis
    result: AuditResult
    node_transitions: list[str]
    collection_issues: list[AuditIssue]
