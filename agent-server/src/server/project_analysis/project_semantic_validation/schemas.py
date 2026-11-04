"""Traceable semantic reviews preserve the exact architectural input."""

from typing import Literal

from pydantic import Field, model_validator

from server.project_analysis.project_architecture.schemas import (
    ArchitecturalClaim,
    ArchitectureResult,
    SourceCitation,
)
from server.runtimes.repository.schemas import (
    AgentContract,
    BudgetUsage,
    ExecutionIssue,
    RepositoryToolCall,
    RetrievedEvidence,
)
from server.runtimes.repository.telemetry import ExecutionTelemetry

from .config import ValidationLimits  # noqa: F401 - compatibility export


class ReviewTarget(AgentContract):
    id: str = Field(min_length=1)
    kind: str
    claim: ArchitecturalClaim
    context: dict = Field(default_factory=dict)
    source_hints: tuple[SourceCitation, ...] = ()


class EvidenceRequest(AgentContract):
    question: str = Field(min_length=1, max_length=700)
    paths: tuple[str, ...] = Field(default=(), max_length=6)


class ProposedCorrection(AgentContract):
    statement: str = Field(min_length=1, max_length=1500)
    scope: str = Field(min_length=1, max_length=250)
    status: Literal["supported", "hypothesis", "unresolved"]
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def certainty(self):
        if self.status != "supported" and not self.limitations:
            raise ValueError("Uncertain corrections require limitations.")
        return self


class SemanticFinding(AgentContract):
    target_id: str = Field(min_length=1)
    checked_statement: str = Field(min_length=1, max_length=3000)
    verdict: Literal["supported", "overstated", "contradicted", "insufficient_evidence"]
    reason: str = Field(min_length=1, max_length=1200)
    counterevidence_check: str = Field(min_length=1, max_length=900)
    evidence_ids: tuple[str, ...] = ()
    correction: ProposedCorrection | None = None
    missing_evidence: tuple[EvidenceRequest, ...] = Field(default=(), max_length=3)

    @model_validator(mode="after")
    def support(self):
        if self.verdict != "insufficient_evidence" and not self.evidence_ids:
            raise ValueError(
                "Decisive verdicts require independently inspected source evidence."
            )
        if self.verdict == "insufficient_evidence" and not self.missing_evidence:
            raise ValueError(
                "Insufficient evidence requires an actionable investigation request."
            )
        if self.verdict == "supported" and (self.correction or self.missing_evidence):
            raise ValueError(
                "Supported findings do not propose corrections or missing evidence."
            )
        if self.correction and self.verdict not in {"overstated", "contradicted"}:
            raise ValueError(
                "Only overstated/contradicted findings propose corrections."
            )
        return self


class ValidationTurn(AgentContract):
    tool_calls: tuple[RepositoryToolCall, ...] = Field(default=(), max_length=4)
    findings: tuple[SemanticFinding, ...] = Field(default=(), max_length=4)

    @model_validator(mode="after")
    def action(self):
        if bool(self.tool_calls) == bool(self.findings):
            raise ValueError("Return tool_calls OR findings, never both or neither.")
        return self


class SemanticValidationResult(AgentContract):
    snapshot_hash: str
    report_hash: str
    original_result: ArchitectureResult
    completion_status: Literal["complete", "partial", "failed"]
    verdict: Literal["accepted", "revisions_needed", "needs_evidence", "inconclusive"]
    selected_target_ids: tuple[str, ...]
    pending_target_ids: tuple[str, ...]
    findings: tuple[SemanticFinding, ...] = ()
    citations: tuple[SourceCitation, ...] = ()
    retrieved_evidence: tuple[RetrievedEvidence, ...] = ()
    execution_issues: tuple[ExecutionIssue, ...] = ()
    limitations: tuple[str, ...] = ()
    usage: BudgetUsage
    telemetry: ExecutionTelemetry

    @model_validator(mode="after")
    def coverage(self):
        if self.snapshot_hash != self.original_result.snapshot_hash:
            raise ValueError("A review must preserve its original snapshot identity.")
        ids = [item.target_id for item in self.findings]
        if len(set(ids)) != len(ids) or not set(ids) <= set(self.selected_target_ids):
            raise ValueError("Findings must uniquely identify selected review targets.")
        if set(ids).intersection(self.pending_target_ids):
            raise ValueError("Reviewed targets cannot remain pending.")
        if not (set(self.selected_target_ids) - set(ids)) <= set(
            self.pending_target_ids
        ):
            raise ValueError("Unreviewed selected targets must remain pending.")
        if self.completion_status == "complete" and (
            self.pending_target_ids or self.execution_issues or not self.findings
        ):
            raise ValueError(
                "Complete reviews require findings, full coverage, and no execution issues."
            )
        if self.verdict == "accepted" and (
            self.completion_status != "complete"
            or any(item.verdict != "supported" for item in self.findings)
        ):
            raise ValueError("Acceptance requires a complete, supported review.")
        return self
