"""Canonical analysability contracts; existing project representations are inputs, not proof."""

from typing import Literal

from pydantic import Field

from server.contracts.audit import (
    AuditRequest,
    AuditResult,
    CandidateFinding,
    Contract,
    Criterion,
    Evaluation,
    EvidenceReference,
    Finding,
    FindingReview,
    Hypothesis,
    InvestigationPlan,
    Review,
)
from server.project_analysis.project_architecture.schemas import ArchitectureResult
from server.project_analysis.project_orientation.schemas import OrientationResult
from server.project_analysis.project_semantic_validation.schemas import (
    SemanticValidationResult,
)


def comprehension_criteria():
    return [Criterion(id=identifier, description=description, origin="design_principle",
        provenance="Analysability investigation lens, not a normative ISO rule or a complexity threshold.")
        for identifier, description in (
            ("comprehension-purpose", "Can observed responsibilities be explained without conflicting interpretations?"),
            ("comprehension-behavior", "Can inputs, decisions, outputs and side effects be reconstructed from inspected code?"),
            ("comprehension-interactions", "Are relevant state, collaborator contracts and implicit conventions understandable?"),
            ("comprehension-mixed-responsibilities", "Does intertwined behavior demonstrably obscure a concrete component responsibility?"),
        )]


class ProjectRepresentations(Contract):
    orientation: OrientationResult | None = None
    architecture: ArchitectureResult | None = None
    semantic_validation: SemanticValidationResult | None = None


class CodeComprehensionRequest(AuditRequest):
    objective: str = "Can component responsibilities and behavior be understood without excessive ambiguity?"
    criteria: list[Criterion] = Field(default_factory=comprehension_criteria, max_length=40)
    targets: list[str] = Field(default_factory=list, max_length=40,
        description="Exact accessible file paths, file IDs or symbol IDs. Empty selects a bounded sample.")
    representations: ProjectRepresentations | None = None


class ComprehensionHypothesis(Hypothesis):
    component_ids: list[str] = Field(min_length=1, max_length=40)


class CodeComprehensionPlan(InvestigationPlan):
    hypotheses: list[ComprehensionHypothesis]


class InspectedParticipant(Contract):
    component_id: str
    observed_behavior: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(min_length=1)


class ComprehensionAssessment(Contract):
    id: str
    hypothesis_id: str
    component_id: str
    responsibility: str = Field(min_length=1, max_length=2000)
    observed_behavior: str = Field(min_length=1, max_length=3000)
    comprehension_question: str = Field(min_length=1, max_length=1000)
    difficulty: str = Field(max_length=2000)
    comprehension_impact: str = Field(max_length=2000)
    alternative_explanation: str = Field(min_length=1, max_length=2000)
    counterevidence_analysis: str = Field(min_length=1, max_length=2000)
    conclusion: Literal["clear", "problematic", "inconclusive"]
    basis: Literal["behavioral", "names_only", "metrics_only", "structure_only"]
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    counterevidence_ids: list[str] = Field(default_factory=list)
    participants: list[InspectedParticipant] = Field(default_factory=list, max_length=20)
    limitations: list[str] = Field(default_factory=list)


class CodeComprehensionCandidate(CandidateFinding):
    assessment_ids: list[str] = Field(min_length=1)


class CodeComprehensionEvaluation(Evaluation):
    hypotheses: list[ComprehensionHypothesis]
    candidates: list[CodeComprehensionCandidate]
    comprehension_assessments: list[ComprehensionAssessment] = Field(default_factory=list)


class ComprehensionFindingReview(FindingReview):
    scope_supported: bool = False
    checked_evidence_ids: list[str] = Field(default_factory=list)
    unverified_claims: list[str] = Field(default_factory=list)


class ComprehensionHypothesisReview(Contract):
    hypothesis_id: str
    status: Literal["supported", "inconclusive"]
    rationale: str = Field(min_length=1)
    assessment_ids: list[str] = Field(default_factory=list)
    checked_evidence_ids: list[str] = Field(default_factory=list)
    scope_supported: bool = False
    unverified_claims: list[str] = Field(default_factory=list)


class CodeComprehensionReview(Review):
    findings: list[ComprehensionFindingReview]
    hypotheses: list[ComprehensionHypothesisReview] = Field(default_factory=list)


class CodeComprehensionFinding(Finding):
    assessment_ids: list[str]
    quality_attribute: Literal["maintainability"] = "maintainability"
    subcharacteristic: Literal["analysability"] = "analysability"


class InvestigatedComprehension(ComprehensionAssessment):
    path: str | None = None
    file_id: str | None = None
    symbol_name: str | None = None
    evidence: list[EvidenceReference] = Field(default_factory=list)
    validation_status: Literal["source_backed", "insufficient_evidence"]
    validation_issues: list[str] = Field(default_factory=list)


class CandidateDiagnostic(Contract):
    candidate_id: str
    status: Literal["rejected", "insufficient_evidence"]
    reasons: list[str]


class CodeComprehensionResult(AuditResult):
    plan: CodeComprehensionPlan | None
    hypotheses: list[ComprehensionHypothesis]
    findings: list[CodeComprehensionFinding]
    comprehension_assessments: list[InvestigatedComprehension] = Field(default_factory=list)
    candidate_diagnostics: list[CandidateDiagnostic] = Field(default_factory=list)
    critical_review: CodeComprehensionReview | None = None
    discarded_hypotheses: list[ComprehensionHypothesis] = Field(default_factory=list)
    inconclusive_investigations: list[str] = Field(default_factory=list)
