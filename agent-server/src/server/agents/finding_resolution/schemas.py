"""Contracts for evidence-grounded finding resolution."""

from typing import Literal

from pydantic import Field, SerializeAsAny, ValidationInfo, model_validator

from server.contracts.audit import Consumption, Contract, EvidenceReference, Finding
from server.runtimes.repository.schemas import RepositoryToolCall
from server.runtimes.repository.tools import RepositoryToolResponse


class FindingResolutionRequest(Contract):
    repository_path: str = Field(min_length=1, description="Directory of the repository to analyze.")
    findings: list[Finding] = Field(description="Previous findings to verify.")


class VerificationCheck(Contract):
    question: str = Field(min_length=1)
    evidence_needed: list[str] = Field(min_length=1, max_length=8)
    queries: list[RepositoryToolCall] = Field(min_length=1, max_length=4)
    persists_if: str = Field(min_length=1)
    resolved_if: str = Field(min_length=1)


class VerificationPlan(Contract):
    finding_id: str = Field(min_length=1)
    checks: list[VerificationCheck] = Field(min_length=1, max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=20)


class FindingInvestigationTurn(Contract):
    finding_id: str = Field(min_length=1)
    action: Literal["tools", "close"]
    summary: str = Field(min_length=1, max_length=3000)
    queries: list[RepositoryToolCall] = Field(default_factory=list, max_length=4)
    evidence_ids: list[str] = Field(default_factory=list, max_length=80)
    limitations: list[str] = Field(default_factory=list, max_length=20)


class FindingInvestigation(Contract):
    """Collected work, not a resolution decision."""

    finding_id: str
    finding: SerializeAsAny[Finding]
    plan: VerificationPlan
    summary: str
    stop_reason: str
    evidence: list[EvidenceReference]
    tool_results: list[RepositoryToolResponse]
    history: list[FindingInvestigationTurn]
    limitations: list[str]
    consumption: Consumption


class FindingVerificationResult(Contract):
    finding_id: str = Field(min_length=1)
    status: Literal["resolved", "persists", "inconclusive"]
    reason: str = Field(min_length=1, pattern=r"\S")
    evidence_ids: list[str]


class FindingEvaluationTurn(Contract):
    finding_id: str = Field(min_length=1)
    action: Literal["record", "investigate"]
    result: FindingVerificationResult | None = None
    missing_checks: list[str] = Field(default_factory=list, max_length=8)


class FindingResolutionResult(Contract):
    results: list[FindingVerificationResult]

    @model_validator(mode="after")
    def matches_request(self, info: ValidationInfo):
        """Validate with context={"request": original_request}; never rewrite findings."""
        request = (info.context or {}).get("request")
        if not isinstance(request, FindingResolutionRequest):
            raise ValueError("The original FindingResolutionRequest is required in validation context.")  # noqa: TRY004 - Pydantic wraps ValueError, not TypeError.
        expected = [finding.id for finding in request.findings]
        actual = [result.finding_id for result in self.results]
        if len(expected) != len(set(expected)):
            raise ValueError("Original finding IDs must be unique to associate verification results.")
        if len(actual) != len(set(actual)):
            raise ValueError("Each finding must have exactly one verification result; duplicate IDs are not allowed.")
        if set(actual) != set(expected):
            raise ValueError("Verification results must match the original finding IDs, without missing or unknown IDs.")
        return self


class FindingResolutionRunRequest(Contract):
    """Direct HTTP entry: the library request plus host-owned job metadata."""

    repository_path: str = Field(min_length=1, description="Directory of the repository checkout to verify.")
    findings: list[Finding] = Field(description="Previous findings to verify.")
    commit_hash: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{40}$",
        description="Audited commit the checkout must currently match, when known.")
    source_audit_id: int | None = Field(default=None, ge=1,
        description="Audit execution that produced the findings; echoed for traceability.")

    def library_request(self) -> FindingResolutionRequest:
        return FindingResolutionRequest(repository_path=self.repository_path, findings=self.findings)


class FindingResolutionRunResult(Contract):
    """Compact direct-execution envelope; full investigations stay host-side."""

    status: Literal["completed", "partial", "failed"]
    source_audit_id: int | None = None
    commit_hash: str | None = None
    snapshot_hash: str | None = None
    results: list[FindingVerificationResult] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    consumption: Consumption
