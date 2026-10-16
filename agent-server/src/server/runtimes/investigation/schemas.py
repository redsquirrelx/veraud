"""Small validated contracts; source references are resolved by the host, not the LLM."""

from typing import Literal

from pydantic import Field

from config.agents import ConfigContract as Contract
from config.agents import InvestigationConfig, ProviderRateLimits

# Keep the established runtime imports working while configuration ownership moves.
__all__ = [
    "AuditRequest", "AuditResult", "CandidateFinding", "Contract", "Criterion", "Evaluation", "EvidenceReference",
    "Finding", "FindingReview", "Hypothesis", "InvestigationConfig", "InvestigationPlan", "ProviderRateLimits", "Review",
]


class Criterion(Contract):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    origin: Literal["explicit", "inferred", "design_principle"]
    provenance: str = Field(min_length=1)


class AuditRequest(Contract):
    objective: str = "Audit software modularity using source-backed evidence."
    architectural_context: str = Field(default="", max_length=12_000)
    criteria: list[Criterion] = Field(default_factory=list, max_length=40)


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
