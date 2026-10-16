"""Context-qualified adaptation constraints on the shared investigator contracts."""

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from .....runtimes.investigation.schemas import (
    AuditRequest,
    AuditResult,
    CandidateFinding,
    Contract,
    Criterion,
    Evaluation,
    EvidenceReference,
    Finding,
)
from .config import ComponentAdaptabilityConfig  # noqa: F401 - compatibility export

ConstraintType = Literal[
    "infrastructure", "environment", "global_state", "framework", "configuration",
    "side_effects", "interface", "dependency_injection", "platform", "data_schema",
]
Conclusion = Literal["verified_obstacle", "context_dependent_risk", "mitigated", "unknown"]
ToolName = Literal[
    "list_files", "find_symbols", "list_relationships", "get_source_excerpt",
    "search_repository_text", "get_evidence", "get_infrastructure",
]


class InspectRoute(StrEnum):
    USE_TOOLS = "use_tools"
    VALIDATE = "validate"


class ValidationRoute(StrEnum):
    INSPECT = "inspect"
    FINALIZE = "finalize"
    LIMITED_FINALIZE = "limited_finalize"


class InspectionToolRequest(Contract):
    name: ToolName
    arguments_json: str = Field(min_length=2, max_length=4000)


class InspectionDecision(Contract):
    action: InspectRoute
    tool_requests: list[InspectionToolRequest] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def consistent_action(self):
        if (self.action == InspectRoute.USE_TOOLS) != bool(self.tool_requests):
            raise ValueError("use_tools requires requests; validate forbids requests")
        return self


class ComponentAdaptabilityRequest(AuditRequest):
    objective: str = "Which constraints make a component difficult to reuse in another context?"
    targets: list[str] = Field(default_factory=list, max_length=20)
    component_ids: list[str] = Field(default_factory=list, max_length=20)
    target_context: str | None = Field(default=None, min_length=1, max_length=6000)
    criteria: list[Criterion] = Field(default_factory=lambda: [Criterion(
        id="component-adaptability", origin="design_principle",
        description="Investigate concrete context-specific adaptation obstacles and existing mitigating seams.",
        provenance="Reusability investigation lens; dependencies are not automatically defects or normative violations.",
    )], max_length=40)

    @model_validator(mode="after")
    def meaningful_context(self):
        if self.target_context is not None and not self.target_context.strip():
            raise ValueError("target_context must be meaningful or null")
        return self


class DiscoverySignal(Contract):
    constraint_type: ConstraintType
    line: int
    rule: str


class ComponentTarget(Contract):
    component_id: str
    file_id: str
    path: str
    symbol: str | None
    start_line: int
    end_line: int
    signals: list[DiscoverySignal]


class UsageInspection(Contract):
    caller_id: str
    relationship_id: str
    evidence_ids: list[str] = Field(max_length=16)
    instantiation_configuration: str = Field(min_length=1, max_length=2000)


class ConstraintAssessment(Contract):
    id: str
    component_id: str
    hypothesis_id: str
    constraint_type: ConstraintType
    constraint_key: str = Field(min_length=1, max_length=160)
    conclusion: Conclusion
    assessed_context: str = Field(min_length=1, max_length=6000)
    context_basis: Literal["explicit", "plausible"]
    observed_facts: list[str] = Field(min_length=1, max_length=12)
    adaptation_impact: str = Field(min_length=1, max_length=2500)
    adaptation_effort: str = Field(min_length=1, max_length=2000)
    assumptions: list[str] = Field(default_factory=list, max_length=16)
    supporting_evidence_ids: list[str] = Field(default_factory=list, max_length=32)
    counterevidence_ids: list[str] = Field(default_factory=list, max_length=24)
    usage: list[UsageInspection] = Field(default_factory=list, max_length=8)
    seam_analysis: str = Field(min_length=1, max_length=2500)
    seam_evidence_ids: list[str] = Field(default_factory=list, max_length=24)
    counterevidence_analysis: str = Field(min_length=1, max_length=2500)
    unknowns: list[str] = Field(default_factory=list, max_length=16)
    mitigation_options: list[str] = Field(default_factory=list, max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class AdaptabilityCandidate(CandidateFinding):
    assessment_ids: list[str] = Field(min_length=1, max_length=16)
    constraint_type: ConstraintType
    classification: Literal["verified_obstacle", "context_dependent_risk"]


class AdaptabilityEvaluation(Evaluation):
    candidates: list[AdaptabilityCandidate]
    constraint_assessments: list[ConstraintAssessment] = Field(max_length=40)
    cleared_components: list[str] = Field(default_factory=list, max_length=20)
    coverage_rationale: str = Field(min_length=1, max_length=3000)
    can_investigate_further: bool = True
    continuation_reason: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def explain_blocker(self):
        if not self.can_investigate_further and not self.continuation_reason.strip():
            raise ValueError("An unverifiable investigation needs a concrete blocker")
        return self


class ExaminedConstraint(ConstraintAssessment):
    component: ComponentTarget | None
    evidence: list[EvidenceReference]
    validation_issues: list[str]
    validation_status: Literal["source_backed", "insufficient_evidence"]


class AdaptabilityFinding(Finding):
    assessment_ids: list[str]
    constraint_type: ConstraintType
    classification: Literal["verified_obstacle", "context_dependent_risk"]
    stable_id: str = ""
    duplicate_of: str | None = None
    assessed_context: str = ""
    adaptation_impact: str = ""
    adaptation_effort: str = ""
    assumptions: list[str] = Field(default_factory=list)
    mitigation_options: list[str] = Field(default_factory=list)


class AdaptabilityCoverage(Contract):
    selected_components: list[ComponentTarget]
    eligible_components: int
    omitted_components: int
    scanned_files: int
    omitted_scan_files: int
    scan_truncated_paths: list[str]
    inspected_paths: list[str] = Field(default_factory=list)
    unassessed_components: list[str] = Field(default_factory=list)
    exhaustive: bool = False


class ToolActivity(Contract):
    call_id: str
    tool: str
    status: str
    seconds: float
    cache_hit: bool


class ComponentAdaptabilityResult(AuditResult):
    investigator: Literal["ComponentAdaptabilityAgent"] = "ComponentAdaptabilityAgent"
    quality_attribute: Literal["reusability"] = "reusability"
    status: Literal["completed", "partial", "failed"] = "partial"
    target_context: str | None = None
    findings: list[AdaptabilityFinding]
    examined_constraints: list[ExaminedConstraint] = Field(default_factory=list)
    coverage: AdaptabilityCoverage | None = None
    summary: str = ""
    tool_failures: list[str] = Field(default_factory=list)
    execution_trace: list[str] = Field(default_factory=list)
    node_durations_seconds: dict[str, float] = Field(default_factory=dict)
    tool_activity: list[ToolActivity] = Field(default_factory=list)
