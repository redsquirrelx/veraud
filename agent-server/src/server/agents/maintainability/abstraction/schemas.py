"""Reusability contracts extending the existing source-backed investigator protocol."""

from typing import Literal

from pydantic import Field

from ...modularity_runtime.schemas import (
    AuditRequest,
    AuditResult,
    CandidateFinding,
    Contract,
    Criterion,
    Evaluation,
    EvidenceReference,
    Finding,
    InvestigationConfig,
)

Category = Literal["useful_abstraction", "unnecessary_abstraction", "coupling", "missed_reuse"]
Basis = Literal["usage_evidence", "structure_only", "metrics_only", "names_only"]


class AbstractionRequest(AuditRequest):
    objective: str = "Do abstractions facilitate reuse, or introduce unnecessary complexity and coupling?"
    targets: list[str] = Field(default_factory=list, max_length=20)
    criteria: list[Criterion] = Field(default_factory=lambda: [Criterion(
        id="abstraction-reuse", origin="design_principle",
        description="Assess concrete reuse benefits, variation, coupling and indirection costs, not abstraction counts.",
        provenance="Reusability investigation lens, not an ISO compliance rule or a numerical design threshold.",
    )], max_length=40)


class AbstractionConfig(InvestigationConfig):
    max_candidates: int = Field(default=12, ge=1, le=40)
    max_participants_per_assessment: int = Field(default=12, ge=1, le=24)


class AbstractionCandidateTarget(Contract):
    component_id: str
    path: str
    symbol_name: str | None
    kind: str
    start_line: int | None
    end_line: int | None
    relationship_ids: list[str]


class Participant(Contract):
    component_id: str
    role: Literal["consumer", "implementation", "delegate", "contract", "duplicate", "composition", "test"]
    relationship_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list, max_length=16)
    usage_explanation: str = Field(min_length=1, max_length=2000)


class AbstractionAssessment(Contract):
    id: str
    hypothesis_id: str
    declaration_id: str
    conclusion: Literal["useful_abstraction", "unnecessary_abstraction", "coupling", "missed_reuse", "justified_boundary", "inconclusive"]
    participants: list[Participant] = Field(default_factory=list, max_length=24)
    observed_facts: list[str] = Field(min_length=1, max_length=16)
    supporting_evidence_ids: list[str] = Field(default_factory=list, max_length=32)
    counterevidence_ids: list[str] = Field(default_factory=list, max_length=16)
    variation_points: str = Field(default="", max_length=2000)
    reuse_benefit: str = Field(default="", max_length=2000)
    indirection_cost: str = Field(default="", max_length=2000)
    coupling_consequence: str = Field(default="", max_length=2000)
    duplication_comparison: str = Field(default="", max_length=2000)
    boundary_justification: str = Field(default="", max_length=2000)
    counterevidence_analysis: str = Field(min_length=1, max_length=3000)
    proportional_alternative: str = Field(default="", max_length=2000)
    uncertainty: Literal["low", "medium", "high"]
    limitations: list[str] = Field(default_factory=list, max_length=16)


class AbstractionCandidate(CandidateFinding):
    category: Category
    assessment_ids: list[str] = Field(min_length=1, max_length=12)
    basis: Basis


class AbstractionEvaluation(Evaluation):
    candidates: list[AbstractionCandidate]
    abstraction_assessments: list[AbstractionAssessment] = Field(max_length=40)


class ComponentReference(Contract):
    id: str
    file_id: str
    path: str
    symbol_name: str | None


class InspectedParticipant(Participant):
    component: ComponentReference
    evidence: list[EvidenceReference]
    validation_issues: list[str]


class InvestigatedAbstraction(AbstractionAssessment):
    declaration: ComponentReference | None
    participants: list[InspectedParticipant]
    evidence: list[EvidenceReference]
    validation_status: Literal["source_backed", "insufficient_evidence"]
    validation_issues: list[str]


class AbstractionFinding(Finding):
    category: Category
    assessment_ids: list[str]
    basis: Basis
    duplicate_of: str | None = None


class AbstractionCoverage(Contract):
    targets: list[str] = Field(default_factory=list)
    selected_candidates: list[AbstractionCandidateTarget] = Field(default_factory=list)
    candidate_count: int = 0
    omitted_candidates: int = 0
    inspected_paths: list[str] = Field(default_factory=list)
    assessed_declarations: list[str] = Field(default_factory=list)
    unassessed_candidates: list[str] = Field(default_factory=list)
    exhaustive: bool = False


class AbstractionResult(AuditResult):
    findings: list[AbstractionFinding]
    investigator: Literal["AbstractionAgent"] = "AbstractionAgent"
    quality_attribute: Literal["reusability"] = "reusability"
    status: Literal["completed", "partial", "failed"] = "partial"
    abstractions_investigated: list[InvestigatedAbstraction] = Field(default_factory=list)
    coverage: AbstractionCoverage = Field(default_factory=AbstractionCoverage)
    inconclusive_investigations: list[str] = Field(default_factory=list)
    tool_failures: list[str] = Field(default_factory=list)
