"""Canonical contracts for this maintainability participant."""

from enum import StrEnum
from typing import ClassVar, Literal

from pydantic import Field, model_validator
from pydantic_core import PydanticCustomError

from server.contracts.audit import (
    AuditRequest,
    AuditResult,
    CandidateFinding,
    Contract,
    Criterion,
    Evaluation,
    EvidenceReference,
    Finding,
    Hypothesis,
    InvestigationPlan,
    Review,
    TargetContext,
)

ConstraintType = Literal[
    "infrastructure", "environment", "global_state", "framework", "configuration",
    "side_effects", "interface", "dependency_injection", "platform", "data_schema",
]

Conclusion = Literal["verified_obstacle", "context_dependent_risk", "mitigated", "unknown"]

ToolName = Literal[
    "list_files", "find_symbols", "list_relationships", "get_source_excerpt",
    "search_repository_text", "get_evidence", "get_infrastructure",
]

class AdaptabilityInspectRoute(StrEnum):
    USE_TOOLS = "use_tools"
    VALIDATE = "validate"

class AdaptabilityValidationRoute(StrEnum):
    INSPECT = "inspect"
    FINALIZE = "finalize"
    LIMITED_FINALIZE = "limited_finalize"

class InspectionToolRequest(Contract):
    name: ToolName
    arguments_json: str = Field(min_length=2, max_length=4000)

class InspectionDecision(Contract):
    action: AdaptabilityInspectRoute
    tool_requests: list[InspectionToolRequest] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def consistent_action(self):
        if (self.action == AdaptabilityInspectRoute.USE_TOOLS) != bool(self.tool_requests):
            raise ValueError("use_tools requires requests; validate forbids requests")
        return self

class ComponentAdaptabilityRequest(AuditRequest, TargetContext):
    objective: str = "Which constraints make a component difficult to reuse in another context?"
    targets: list[str] = Field(default_factory=list, max_length=20)
    component_ids: list[str] = Field(default_factory=list, max_length=20)
    criteria: list[Criterion] = Field(default_factory=lambda: [Criterion(
        id="component-adaptability", origin="design_principle",
        description="Investigate concrete context-specific adaptation obstacles and existing mitigating seams.",
        provenance="Reusability investigation lens; dependencies are not automatically defects or normative violations.",
    )], max_length=40)

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
    source_role: Literal["implementation", "fixture", "configuration", "auxiliary"] = "implementation"

class AdaptabilityHypothesis(Hypothesis):
    component_ids: list[str] = Field(default_factory=list, max_length=20,
        description="Exact selected component IDs committed to the original question.")

class AdaptabilityPlan(InvestigationPlan):
    hypotheses: list[AdaptabilityHypothesis]

class AdaptabilityHypothesisReview(Contract):
    hypothesis_id: str
    assessment_ids: list[str] = Field(default_factory=list)
    checked_evidence_ids: list[str] = Field(default_factory=list)
    scope_supported: bool = False
    resolution: Literal["confirmed", "discarded", "inconclusive"] = "inconclusive"
    contract_and_fixture_claims_supported: bool = False
    rationale: str = Field(min_length=1)
    unverified_claims: list[str] = Field(default_factory=list)

class AdaptationClaimReview(Contract):
    assessment_id: str
    checked_evidence_ids: list[str] = Field(default_factory=list)
    required_change: str = ""
    existing_seams: str = ""
    why_seams_insufficient: str = ""
    target_mismatch_supported: bool = False
    input_normalization_suffices: bool | None = None
    change_scope: Literal["content_only", "input_normalization", "component_logic", "unknown"] = "unknown"
    qualified_impact: str = Field(default="", max_length=2500,
        description="Local, context-qualified adaptation consequence; do not infer impossibility or complete rewrites from domain-specific content.")
    qualified_recommendation: str = Field(default="", max_length=2500)

class AdaptabilityReview(Review):
    hypotheses: list[AdaptabilityHypothesisReview] = Field(default_factory=list)
    adaptation_checks: list[AdaptationClaimReview] = Field(default_factory=list)

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
    schema_dependency_basis: Literal["input_contract", "fixed_domain_schema", "fixture_only", "unknown"] = "unknown"
    schema_adaptation_analysis: str = Field(default="", max_length=2500,
        description="For data_schema, distinguish input shape from fixed domain values and explain why existing parameters/mappings do not suffice for the assessed context.")
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
    split_from: str | None = None
    assessment_ids: list[str] = Field(min_length=1, max_length=16)
    constraint_type: ConstraintType
    classification: Literal["verified_obstacle", "context_dependent_risk"]

class AdaptabilityEvaluation(Evaluation):
    validation_feedback: ClassVar[dict[str, str]] = Evaluation.validation_feedback | {
        "investigation_blocker_required": "When can_investigate_further is false, continuation_reason must explain a concrete blocker. If more evidence can be obtained, use can_investigate_further=true and describe the missing information instead. Do not invent a blocker or claim sufficient evidence to pass validation.",
    }
    candidates: list[AdaptabilityCandidate]
    constraint_assessments: list[ConstraintAssessment] = Field(max_length=40)
    cleared_components: list[str] = Field(default_factory=list, max_length=20)
    coverage_rationale: str = Field(min_length=1, max_length=3000)
    can_investigate_further: bool = True
    continuation_reason: str = Field(default="", max_length=2000)
    continuation_blocker: Literal["none", "external_context", "unavailable_source", "dynamic_behavior"] = "none"

    @model_validator(mode="after")
    def explain_blocker(self):
        if not self.can_investigate_further and not self.continuation_reason.strip():
            raise PydanticCustomError("investigation_blocker_required",
                self.validation_feedback["investigation_blocker_required"])
        return self

class ExaminedConstraint(ConstraintAssessment):
    component: ComponentTarget | None
    evidence: list[EvidenceReference]
    validation_issues: list[str]
    validation_status: Literal["source_backed", "insufficient_evidence"]

class AdaptabilityFinding(Finding):
    split_from: str | None = None
    validation_issues: list[str] = Field(default_factory=list)
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
    planned_components: list[str] = Field(default_factory=list)
    unplanned_components: list[str] = Field(default_factory=list)
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
    candidate_split_history: dict[str, AdaptabilityCandidate] = Field(default_factory=dict)
    plan: AdaptabilityPlan | None
    critical_review: AdaptabilityReview | None = None
    hypothesis_validation_issues: dict[str, list[str]] = Field(default_factory=dict)
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

from .config import ComponentAdaptabilityConfig

__all__ = ['AdaptabilityCandidate', 'AdaptabilityCoverage', 'AdaptabilityEvaluation', 'AdaptabilityFinding', 'AdaptabilityPlan', 'AdaptabilityReview', 'AuditRequest', 'AuditResult', 'CandidateFinding', 'ComponentAdaptabilityConfig', 'ComponentAdaptabilityRequest', 'ComponentAdaptabilityResult', 'ComponentTarget', 'Conclusion', 'ConstraintAssessment', 'ConstraintType', 'Contract', 'Criterion', 'DiscoverySignal', 'Evaluation', 'EvidenceReference', 'ExaminedConstraint', 'Finding', 'InspectRoute', 'InspectionDecision', 'InspectionToolRequest', 'ToolActivity', 'ToolName', 'UsageInspection', 'ValidationRoute']

InspectRoute = AdaptabilityInspectRoute
ValidationRoute = AdaptabilityValidationRoute
