from typing import TypedDict

from .schemas import (
    AssessmentLink,
    AuditAssignment,
    CoordinatorAssessment,
    CoverageDecision,
    CoverageGap,
    MaintainabilityReport,
    RawAssessment,
    ScopeAssessment,
    SynthesisRound,
)


class MaintainabilityManagerState(TypedDict):
    assessment_id: str
    repository_id: str
    snapshot_hash: str
    scope: ScopeAssessment
    initial_plan: list[AuditAssignment]
    pending_assignments: list[AuditAssignment]
    execution_records: list[RawAssessment]
    investigation_results: list[CoordinatorAssessment]
    rounds_completed: int
    material_gaps: list[CoverageGap]
    resolved_gap_ids: list[str]
    actionable_followups: list[CoverageGap]
    decision: CoverageDecision
    synthesis_history: list[SynthesisRound]
    summary: str
    links: list[AssessmentLink]
    ignored_responses: list[str]
    issued_assignments: list[AuditAssignment]
    result: MaintainabilityReport
