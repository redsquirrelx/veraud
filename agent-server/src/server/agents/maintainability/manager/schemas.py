"""Typed manager specializations of the established coordinator contracts."""

from typing import Any, Literal, get_args

from pydantic import Field, SerializeAsAny, field_validator

from ....runtimes.investigation.schemas import (
    Contract,
    EvidenceReference,
)
from ..modularity.coordinator import schemas as shared
from ..modularity.coordinator.registry import INVESTIGATORS as MODULARITY_INVESTIGATORS
from ..reusability.coordinator.schemas import ReusabilityAssessment, ReusabilityRequest
from .config import MaintainabilityConfig

Dimension = Literal["modularity", "reusability"]


class MaintainabilityRequest(ReusabilityRequest):
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


class AuditAssignment(shared.Assignment):
    investigator_id: Dimension
    assignment_id: str
    attempt: int = Field(ge=1)
    requested_evidence: list[str]
    success_criteria: list[str]


class NestedModularityAssessment(shared.ModularityAssessment):
    @field_validator("consolidated_findings", mode="before")
    @classmethod
    def restore_contributions(cls, values):
        restored = []
        for value in values:
            if isinstance(value, dict):
                contributions = []
                for contribution in value["contributions"]:
                    spec = MODULARITY_INVESTIGATORS.get(contribution["investigator_id"])
                    if spec is None:
                        raise ValueError("Unknown modularity investigator")
                    finding_type = get_args(spec.result_class.model_fields["findings"].annotation)[0]
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
                spec = MODULARITY_INVESTIGATORS.get(value["assignment"]["investigator_id"])
                if spec is None:
                    raise ValueError("Unknown modularity investigator")
                value = value | {"result": spec.result_class.model_validate(value["result"])}
            restored.append(value)
        return restored


class CoordinatorAssessment(shared.InvocationRecord):
    assignment: AuditAssignment
    result: SerializeAsAny[ReusabilityAssessment | NestedModularityAssessment] | None = None
    evidence_sufficient: bool = False
    coverage_issues: list[str] = Field(default_factory=list)


class RawAssessment(shared.RawInvocation):
    assignment: AuditAssignment


class ScopeAssessment(Contract):
    repository_id: str
    commit: str | None
    snapshot_hash: str
    requested: list[str]
    assessable: list[Dimension]
    unsupported: list[str]
    targets: list[str]
    depth: str


class CoverageGap(Contract):
    id: str
    coordinator: Dimension | None
    kind: Literal["missing_coverage", "contradiction", "quality", "unsupported", "synthesis_failure"]
    question: str
    targets: list[str] = Field(default_factory=list, max_length=12)
    finding_refs: list[str] = Field(default_factory=list, max_length=12)
    evidence_refs: list[str] = Field(default_factory=list, max_length=12)
    blocking: bool = True


class AssessmentLink(Contract):
    kind: Literal["overlap", "tradeoff", "contradiction"]
    finding_refs: list[str] = Field(min_length=2, max_length=12)
    rationale: str = Field(min_length=1, max_length=2000)
    status: Literal["observed", "unresolved", "resolved"] = "observed"


class GapResolution(Contract):
    gap_id: str
    invocation_id: str
    evidence_refs: list[str] = Field(min_length=1, max_length=12)
    rationale: str = Field(min_length=1, max_length=2000)


class AssessmentSynthesis(Contract):
    summary: str = Field(max_length=3000)
    links: list[AssessmentLink] = Field(default_factory=list, max_length=24)
    gaps: list[CoverageGap] = Field(default_factory=list, max_length=16)
    resolutions: list[GapResolution] = Field(default_factory=list, max_length=16)


class CoverageDecision(Contract):
    route: Literal["yes", "no"]
    sufficient: bool
    reason: str
    covered: list[Dimension]
    required: list[Dimension]
    actionable_gap_ids: list[str]
    can_follow_up: bool


class SynthesisRound(Contract):
    round: int
    draft: AssessmentSynthesis | None
    decision: CoverageDecision
    gaps: list[CoverageGap] = Field(default_factory=list)


class MaintainabilityReport(Contract):
    investigator: Literal["MaintainabilityManagerAgent"] = "MaintainabilityManagerAgent"
    quality_attribute: Literal["maintainability"] = "maintainability"
    assessment_id: str
    repository_id: str
    commit: str | None
    snapshot_hash: str
    objective: str
    targets: list[str]
    status: Literal["complete", "partial", "failed"]
    termination_reason: str
    scope: ScopeAssessment
    coverage: CoverageDecision
    initial_plan: list[AuditAssignment]
    assessments: list[CoordinatorAssessment]
    findings: dict[str, dict[str, Any]]
    evidence: dict[str, EvidenceReference]
    links: list[AssessmentLink]
    unresolved_gaps: list[CoverageGap]
    resolved_gap_ids: list[str]
    summary: str
    limitations: list[str]
    consumption: shared.Consumption
    limits: MaintainabilityConfig
    rounds_completed: int
    duration_seconds: float
    node_transitions: list[str]
    synthesis_history: list[SynthesisRound]
    ignored_responses: list[str]
