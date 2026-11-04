from typing import TypedDict

from .schemas import (
    Assignment,
    ConsolidatedFinding,
    EvidenceGap,
    InvestigatorCapability,
    InvocationRecord,
    ModularityAssessment,
    RawInvocation,
    Route,
)


class ModularityState(TypedDict):
    assessment_id: str
    repository_id: str
    snapshot_hash: str
    scope: list[str]
    investigator_registry: list[InvestigatorCapability]
    rounds_completed: int
    max_rounds: int
    budgets: dict
    pending_assignments: list[Assignment]
    completed_assignments: list[str]
    invocation_status: dict[str, str]
    investigation_results: list[InvocationRecord]
    execution_records: list[RawInvocation]
    collected_count: int
    initial_plan: list[Assignment]
    consolidated_findings: list[ConsolidatedFinding]
    material_gaps: list[EvidenceGap]
    actionable_followups: list[EvidenceGap]
    resolved_gap_ids: list[str]
    withdrawn_finding_refs: list[str]
    summary: str
    next_route: Route
    termination_reason: str
    messages: list
    result: ModularityAssessment
