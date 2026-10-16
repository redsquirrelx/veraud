"""General manager outputs and maintainability-specific hierarchy contracts."""

from typing import Any, Literal, get_args

from pydantic import Field, SerializeAsAny, field_validator

from ..maintainability.manager.config import MaintainabilityConfig
from . import coordinator as shared
from .base import (
    AuditResult,
    Contract,
    EvidenceReference,
    ScopedAuditRequest,
    TargetContext,
)
from .coordinator import (
    ReusabilityAssessment,
    ReusabilityRequest,  # noqa: F401 - compatibility export
)
from .investigator import DependencyImpactResult, ResponsibilityResult

# Data-only lookup used to restore nested modularity result types without importing agent registries.
_MODULARITY_RESULTS = {
    "architecture_boundary": AuditResult,
    "responsibility": ResponsibilityResult,
    "dependency_impact": DependencyImpactResult,
}

# Maintainability dimensions with implemented coordinators; unsupported requested names are reported in scope.
Dimension = Literal["modularity", "reusability"]


# Manager input: combines common scope/context with requested dimensions, depth and per-dimension targets.
# MaintainabilityManagerAgent.run() normalizes the scope; the validator deduplicates dimension names.
class MaintainabilityRequest(ScopedAuditRequest, TargetContext):
    objective: str = "Audit the requested maintainability dimensions using source-backed subordinate assessments."
    dimensions: list[str] = Field(default_factory=lambda: ["modularity", "reusability"], min_length=1, max_length=12)
    depth: Literal["bounded", "thorough"] = "bounded"
    dimension_targets: dict[Dimension, list[str]] = Field(default_factory=dict)

    @field_validator("dimensions")
    @classmethod
    def normalize_dimensions(cls, values):
        values = list(dict.fromkeys(v.strip().casefold() for v in values))
        if any(not v for v in values):
            raise ValueError("Dimension names must be nonempty")
        return values


# Coordinator assignment: adds assignment/attempt identity, requested evidence and explicit success criteria.
# The manager creates it in plan_audit or follow-up planning when delegating to a dimension coordinator.
class AuditAssignment(shared.DelegationAssignment[Dimension]):
    assignment_id: str
    attempt: int = Field(ge=1)
    requested_evidence: list[str]
    success_criteria: list[str]


# Manager-side adapter for a modularity assessment: restores concrete investigator results/findings from JSON.
# Used while validating nested coordinator responses so specialized fields survive report round trips.
class NestedModularityAssessment(shared.ModularityAssessment):
    @field_validator("consolidated_findings", mode="before")
    @classmethod
    def restore_contributions(cls, values):
        restored = []
        for value in values:
            if isinstance(value, dict):
                contributions = []
                for contribution in value["contributions"]:
                    result_type = _MODULARITY_RESULTS.get(contribution["investigator_id"])
                    if result_type is None:
                        raise ValueError("Unknown modularity investigator")
                    finding_type = get_args(result_type.model_fields["findings"].annotation)[0]
                    contributions.append(contribution | {"finding": finding_type.model_validate(contribution["finding"])})
                value = value | {"contributions": contributions}
            restored.append(value)
        return restored

    @field_validator("invocations", mode="before")
    @classmethod
    def restore_investigator_types(cls, values):
        restored = []
        for value in values:
            if isinstance(value, dict) and value.get("result") is not None:
                result_type = _MODULARITY_RESULTS.get(value["assignment"]["investigator_id"])
                if result_type is None:
                    raise ValueError("Unknown modularity investigator")
                value = value | {"result": result_type.model_validate(value["result"])}
            restored.append(value)
        return restored


# Collected coordinator execution: combines a typed assessment with evidence sufficiency and coverage issues.
# The manager builds it in collect_assessments after validating the delegated result and its provenance.
class CoordinatorAssessment(shared.AgentInvocation[
    AuditAssignment, SerializeAsAny[ReusabilityAssessment | NestedModularityAssessment],
]):
    evidence_sufficient: bool = False
    coverage_issues: list[str] = Field(default_factory=list)


# Raw coordinator response: associates an unvalidated value or failure with the manager's assignment.
# Passed from delegation to collect_assessments before conversion into CoordinatorAssessment.
class RawAssessment(shared.RawAgentInvocation[AuditAssignment]):
    """Unvalidated coordinator response associated with a manager assignment."""


# Resolved audit scope: separates requested, assessable and unsupported dimensions within a repository snapshot.
# Created by the manager's analyze_audit_scope step and retained in the final report.
class ScopeAssessment(Contract):
    repository_id: str
    commit: str | None
    snapshot_hash: str
    requested: list[str]
    assessable: list[Dimension]
    unsupported: list[str]
    targets: list[str]
    depth: str


# Manager-level gap: records missing coverage, contradictions or failures, with references and blocking status.
# Maintained during synthesis/follow-up decisions and included as unresolved_gaps in the final report.
class CoverageGap(Contract):
    id: str
    coordinator: Dimension | None
    kind: Literal["missing_coverage", "contradiction", "quality", "unsupported", "synthesis_failure"]
    question: str
    targets: list[str] = Field(default_factory=list, max_length=12)
    finding_refs: list[str] = Field(default_factory=list, max_length=12)
    evidence_refs: list[str] = Field(default_factory=list, max_length=12)
    blocking: bool = True


# Cross-assessment relationship: links findings by overlap, trade-off or contradiction with a rationale.
# Proposed in manager synthesis and retained with resolution status to explain interactions between dimensions.
class AssessmentLink(Contract):
    kind: Literal["overlap", "tradeoff", "contradiction"]
    finding_refs: list[str] = Field(min_length=2, max_length=12)
    rationale: str = Field(min_length=1, max_length=2000)
    status: Literal["observed", "unresolved", "resolved"] = "observed"


# Manager-level resolution proposal: cites the coordinator invocation and evidence supporting closure of a gap.
# Returned in AssessmentSynthesis and checked by the host before marking a coverage gap as resolved.
class GapResolution(Contract):
    gap_id: str
    invocation_id: str
    evidence_refs: list[str] = Field(min_length=1, max_length=12)
    rationale: str = Field(min_length=1, max_length=2000)


# Manager synthesis draft: combines an overall summary, cross-assessment links, gaps and resolution proposals.
# The model returns it in synthesize_assessments; the manager validates references before updating state.
class AssessmentSynthesis(Contract):
    summary: str = Field(max_length=3000)
    links: list[AssessmentLink] = Field(default_factory=list, max_length=24)
    gaps: list[CoverageGap] = Field(default_factory=list, max_length=16)
    resolutions: list[GapResolution] = Field(default_factory=list, max_length=16)


# Coverage/routing decision: records sufficiency, covered/required dimensions and actionable follow-up gaps.
# Calculated by the manager after synthesis; yes finalizes the audit and no routes to follow-up planning.
class CoverageDecision(Contract):
    route: Literal["yes", "no"]
    sufficient: bool
    reason: str
    covered: list[Dimension]
    required: list[Dimension]
    actionable_gap_ids: list[str]
    can_follow_up: bool


# Manager round history: preserves the draft, coverage decision and gap state for one synthesis round.
# Accumulated in synthesis_history so the final report explains why delegation continued or stopped.
class SynthesisRound(Contract):
    round: int
    draft: AssessmentSynthesis | None
    decision: CoverageDecision
    gaps: list[CoverageGap] = Field(default_factory=list)


# General manager output: parameterizes scope, coverage, child assessments, links, gaps, limits and history.
# Retains indexed findings/evidence and accounting; concrete managers bind the hierarchy-specific types.
class ManagerResult[
    ScopeT: Contract,
    CoverageT: Contract,
    AssignmentT: Contract,
    AssessmentT: Contract,
    LinkT: Contract,
    GapT: Contract,
    LimitsT: Contract,
    RoundT: Contract,
](Contract):
    """Manager result envelope, parameterized by its scope and subordinate contracts."""

    assessment_id: str
    repository_id: str
    commit: str | None
    snapshot_hash: str
    objective: str
    targets: list[str]
    status: Literal["complete", "partial", "failed"]
    termination_reason: str
    scope: ScopeT
    coverage: CoverageT
    initial_plan: list[AssignmentT]
    assessments: list[AssessmentT]
    findings: dict[str, dict[str, Any]]
    evidence: dict[str, EvidenceReference]
    links: list[LinkT]
    unresolved_gaps: list[GapT]
    resolved_gap_ids: list[str]
    summary: str
    limitations: list[str]
    consumption: shared.Consumption
    limits: LimitsT
    rounds_completed: int
    duration_seconds: float
    node_transitions: list[str]
    synthesis_history: list[RoundT]
    ignored_responses: list[str]


# Final maintainability report: binds the manager envelope to modularity/reusability scope and assessments.
# finalize_audit returns it from MaintainabilityManagerAgent.run(), preserving provenance and partial failures.
class MaintainabilityReport(ManagerResult[
    ScopeAssessment, CoverageDecision, AuditAssignment, CoordinatorAssessment,
    AssessmentLink, CoverageGap, MaintainabilityConfig, SynthesisRound,
]):
    investigator: Literal["MaintainabilityManagerAgent"] = "MaintainabilityManagerAgent"
    quality_attribute: Literal["maintainability"] = "maintainability"
