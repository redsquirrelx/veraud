"""Canonical contracts for this maintainability participant."""

from typing import Literal

from pydantic import ConfigDict, Field

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
    Review,
)

ImpactKind = Literal["demonstrated", "plausible_risk", "none", "inconclusive"]

FindingBasis = Literal[
    "consequence_evidence", "metrics_only", "cycle_only", "transitivity_only",
    "interface_shape_only", "dependency_existence_only",
]

def dependency_impact_criteria():
    return [Criterion(
        id=identifier, description=description, origin="design_principle",
        provenance="Investigation lens, not a normative ISO rule, coupling threshold or documented project constraint.",
    ) for identifier, description in (
        ("concrete-coupling", "Investigate unnecessary dependence on implementation details and replacement costs."),
        ("change-propagation", "Explain concretely how a change can affect consumers across dependency boundaries."),
        ("dependency-cycles", "Assess whether cycles actually restrict independent maintenance."),
        ("shared-dependencies", "Investigate maintenance consequences for consumers of shared components."),
        ("contract-stability", "Inspect actual contracts and usage; interfaces alone prove neither stability nor low coupling."),
        ("component-independence", "Assess maintenance independence and justified co-evolution."),
    )]

class DependencyImpactRequest(AuditRequest):
    objective: str = "Do identified dependencies create coupling harmful to independent maintenance?"
    criteria: list[Criterion] = Field(default_factory=dependency_impact_criteria, max_length=40)

class DependencyLink(Contract):
    id: str = Field(min_length=1)
    source_id: str = Field(min_length=1, description="Actual source file/symbol ID, not its name.")
    target_id: str = Field(min_length=1, description="Actual target file/symbol ID, not its name.")
    relationship_id: str | None = Field(default=None, description="Actual snapshot relationship ID; null if unresolved.")
    dependency_type: str = Field(min_length=1, description="Exact kind of the cited graph relationship, not an inferred runtime call.")
    evidence_ids: list[str] = Field(default_factory=list)

class DependencyAssessment(Contract):
    id: str = Field(min_length=1)
    hypothesis_id: str = Field(min_length=1)
    dependencies: list[DependencyLink] = Field(min_length=1, max_length=32)
    dependency_path: list[str] = Field(default_factory=list, description="Optional ordered component IDs; each hop must occur in dependencies.")
    contract_analysis: str
    architectural_justification: str
    impact_kind: ImpactKind
    consequence: str
    change_scenario: str
    propagation_explanation: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    demonstration_evidence_ids: list[str] = Field(default_factory=list)
    demonstration_rationale: str = ""
    uncertainty: Literal["low", "medium", "high"]
    limitations: list[str] = Field(default_factory=list)

class DependencyImpactCandidate(CandidateFinding):
    assessment_ids: list[str] = Field(min_length=1)
    basis: FindingBasis

class DependencyImpactEvaluation(Evaluation):
    candidates: list[DependencyImpactCandidate]
    dependency_assessments: list[DependencyAssessment]

class DependencyImpactFinding(Finding):
    assessment_ids: list[str]
    basis: FindingBasis

class DependencyHypothesisReview(Contract):
    hypothesis_id: str
    status: Literal["supported", "inconclusive"]
    rationale: str = Field(min_length=1)
    assessment_ids: list[str] = Field(default_factory=list)
    checked_evidence_ids: list[str] = Field(default_factory=list)
    scope_supported: bool = False
    unverified_claims: list[str] = Field(default_factory=list)

class DependencyImpactReview(Review):
    hypotheses: list[DependencyHypothesisReview] = Field(default_factory=list)

class DependencyComponentReference(Contract):
    model_config = ConfigDict(title="ComponentReference")

    id: str
    file_id: str
    path: str
    symbol_name: str | None = None

class InvestigatedDependency(DependencyLink):
    source: DependencyComponentReference
    target: DependencyComponentReference
    evidence: list[EvidenceReference]
    validation_status: Literal["source_backed", "insufficient_evidence"]
    validation_issues: list[str]

class InvestigatedImpact(DependencyAssessment):
    dependencies: list[InvestigatedDependency] = Field(default_factory=list)
    evidence: list[EvidenceReference]
    is_cycle: bool
    validation_status: Literal["source_backed", "insufficient_evidence"]
    validation_issues: list[str]

class DependencyImpactResult(AuditResult):
    findings: list[DependencyImpactFinding]
    components_investigated: list[DependencyComponentReference] = Field(default_factory=list)
    dependency_assessments: list[InvestigatedImpact] = Field(default_factory=list)
    discarded_hypotheses: list[Hypothesis] = Field(default_factory=list)
    inconclusive_investigations: list[str] = Field(default_factory=list)
    critical_review: DependencyImpactReview | None = None

from .config import DependencyImpactConfig

__all__ = ['AuditRequest', 'AuditResult', 'CandidateFinding', 'ComponentReference', 'Contract', 'Criterion', 'DependencyAssessment', 'DependencyImpactCandidate', 'DependencyImpactConfig', 'DependencyImpactEvaluation', 'DependencyImpactFinding', 'DependencyImpactRequest', 'DependencyImpactResult', 'DependencyImpactReview', 'DependencyLink', 'Evaluation', 'EvidenceReference', 'Finding', 'FindingBasis', 'Hypothesis', 'ImpactKind', 'InvestigatedDependency', 'InvestigatedImpact', 'default_criteria']

ComponentReference = DependencyComponentReference
default_criteria = dependency_impact_criteria
