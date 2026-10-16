"""Domain-independent contracts safe for shared runtimes to import.

This module must not import category-specific schemes, concrete agents, registries
or runtimes. It owns the shared investigator envelope and reusable evidence,
review, criteria and accounting contracts.
"""

from typing import Literal

from pydantic import Field, field_validator

from config.agents import ConfigContract as Contract


class Criterion(Contract):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    origin: Literal["explicit", "inferred", "design_principle"]
    provenance: str = Field(min_length=1)


class AuditRequest(Contract):
    objective: str = "Audit software modularity using source-backed evidence."
    architectural_context: str = Field(default="", max_length=12_000)
    criteria: list[Criterion] = Field(default_factory=list, max_length=40)


class ScopedAuditRequest(AuditRequest):
    """Bounded audit scope shared by coordinators and managers of any dimension."""

    objective: str = "Assess software within the declared scope using source-backed evidence."
    architectural_context: str = Field(default="", max_length=6000)
    targets: list[str] = Field(default_factory=list, max_length=12)


class TargetContext(Contract):
    """Optional destination context shared by requests that analyze reuse or adaptation."""

    target_context: str | None = Field(default=None, min_length=1, max_length=6000)

    @field_validator("target_context")
    @classmethod
    def meaningful_context(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("target_context must be meaningful or null")
        return value


class Hypothesis(Contract):
    id: str
    question: str
    criterion_id: str | None = None
    priority: Literal["high", "medium", "low"] = "medium"
    evidence_needed: list[str] = Field(default_factory=list)
    status: Literal["pending", "confirmed", "discarded", "inconclusive"] = "pending"
    rationale: str = ""


class InvestigationPlan(Contract):
    objectives: list[str]
    components: list[str]
    hypotheses: list[Hypothesis]


class CandidateFinding(Contract):
    id: str
    title: str
    description: str
    criterion_id: str
    kind: Literal["violation", "design_observation"]
    components: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    justification: str
    modularity_impact: str
    severity: Literal["info", "low", "medium", "high", "critical"]
    confidence: float = Field(ge=0, le=1)
    recommendation: str


class Evaluation(Contract):
    sufficient: bool
    hypotheses: list[Hypothesis]
    candidates: list[CandidateFinding]
    missing_information: list[str]


class FindingReview(Contract):
    finding_id: str
    status: Literal["accepted", "rejected", "insufficient_evidence"]
    rationale: str = Field(min_length=1)
    severity: Literal["info", "low", "medium", "high", "critical"]
    confidence: float = Field(ge=0, le=1)


class Review(Contract):
    findings: list[FindingReview]
    limitations: list[str] = Field(default_factory=list)


class EvidenceReference(Contract):
    id: str
    snapshot_hash: str
    commit: str | None
    path: str
    file_id: str
    content_hash: str
    kind: Literal["source", "metadata"]
    start_line: int | None = None
    end_line: int | None = None
    symbol_ids: list[str] = Field(default_factory=list)
    tool_call_id: str


class Finding(CandidateFinding):
    evidence_ids: list[str] = Field(default_factory=list)
    criterion: Criterion
    evidence: list[EvidenceReference]
    validation_status: Literal["accepted", "rejected", "insufficient_evidence"]
    review_rationale: str


class AuditResult(Contract):
    repository_id: str
    commit: str | None
    snapshot_hash: str
    objective: str
    plan: InvestigationPlan | None
    findings: list[Finding]
    hypotheses: list[Hypothesis]
    missing_information: list[str]
    limitations: list[str]
    termination_reason: str
    model_calls: int
    tool_calls: int
    iterations: int
    accounted_tokens: int
    estimated_tokens: int


class Consumption(Contract):
    model_calls: int = 0
    tool_calls: int = 0
    accounted_tokens: int = 0
    estimated_tokens: int = 0
    model_calls_estimated: bool = False
