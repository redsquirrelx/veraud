"""Responsibility-specific contracts, built on the shared modularity audit schemas."""

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
    Hypothesis,
    InvestigationConfig,
)


def default_criteria():
    return [Criterion(
        id=identifier, description=description, origin="design_principle",
        provenance="Investigation lens, not a normative ISO rule, size threshold or documented project constraint.",
    ) for identifier, description in (
        ("responsibility-cohesion", "Behaviors should contribute to a coherent component purpose."),
        ("responsibility-separation", "Investigate conceptually independent behaviors and reasons for change."),
        ("responsibility-placement", "Compare behavior placement with the supplied architecture and contracts."),
        ("responsibility-accumulation", "Investigate heterogeneous functionality and whether its grouping is justified."),
    )]


class ResponsibilityRequest(AuditRequest):
    objective: str = "Do components group coherent responsibilities or mix incompatible functionality?"
    criteria: list[Criterion] = Field(default_factory=default_criteria, max_length=40)


class ResponsibilityConfig(InvestigationConfig):
    pass


class Responsibility(Contract):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    behaviors: list[str] = Field(default_factory=list)
    possible_change_reasons: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)


class ResponsibilityConflict(Contract):
    responsibility_ids: list[str] = Field(min_length=2)
    independent_change_rationale: str = Field(min_length=1)
    maintenance_risk: str = Field(min_length=1)


class ComponentAssessment(Contract):
    id: str = Field(min_length=1)
    component_id: str = Field(min_length=1, description="An actual file or symbol ID returned by repository tools.")
    responsibilities: list[Responsibility]
    potentially_incompatible: list[ResponsibilityConflict]
    cohesion: Literal["coherent", "mixed", "inconclusive"]
    architectural_justification: str
    evidence_ids: list[str] = Field(default_factory=list)


class ResponsibilityCandidate(CandidateFinding):
    assessment_ids: list[str] = Field(min_length=1)
    basis: Literal["behavioral", "metrics_only", "names_only"]


class ResponsibilityEvaluation(Evaluation):
    candidates: list[ResponsibilityCandidate]
    component_assessments: list[ComponentAssessment]


class ResponsibilityFinding(Finding):
    assessment_ids: list[str]
    basis: Literal["behavioral", "metrics_only", "names_only"]


class InvestigatedComponent(ComponentAssessment):
    path: str
    file_id: str
    symbol_name: str | None = None
    evidence: list[EvidenceReference]
    validation_status: Literal["source_backed", "insufficient_evidence"]
    validation_issues: list[str]


class ResponsibilityResult(AuditResult):
    findings: list[ResponsibilityFinding]
    components_investigated: list[InvestigatedComponent] = Field(default_factory=list)
    discarded_hypotheses: list[Hypothesis] = Field(default_factory=list)
    inconclusive_investigations: list[str] = Field(default_factory=list)
