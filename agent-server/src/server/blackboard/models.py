"""Shared knowledge records published by agents to the blackboard."""

from datetime import UTC, datetime
from typing import Annotated, Literal, Self
from uuid import uuid4

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    model_validator,
)

from server.contracts.audit import Consumption, Criterion

NonEmptyString = Annotated[str, Field(min_length=1, pattern=r"\S")]
Confidence = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Severity = Literal["info", "low", "medium", "high", "critical"]


class BlackboardRecord(BaseModel):
    """Identity and provenance common to all blackboard records."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: NonEmptyString = Field(default_factory=lambda: str(uuid4()))
    agent_id: NonEmptyString
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    run_id: NonEmptyString
    invocation_id: NonEmptyString
    local_id: NonEmptyString | None = Field(
        default=None,
        description="Original invocation-local ID; id is the globally unique blackboard ID.",
    )
    details: dict[str, JsonValue] = Field(
        default_factory=dict,
        description="Domain-specific data retained with its original field names and structure.",
    )


class Evidence(BlackboardRecord):
    commit_verification: Literal["exact", "line_endings_equivalent", "unverified"] | None = None
    git_blob_id: str | None = None
    """Verifiable technical evidence published by an investigator."""

    kind: Literal["source", "metadata", "tool_result"]
    source: NonEmptyString = Field(
        validation_alias=AliasChoices("source", "path"),
        description="File path, URI or other source identifier.",
    )
    content: str | None = Field(default=None, description="Optional excerpt; an empty file is valid.")
    snapshot_hash: NonEmptyString
    commit: NonEmptyString | None = None
    file_id: NonEmptyString
    content_hash: NonEmptyString
    symbol_ids: tuple[NonEmptyString, ...] = ()
    tool_call_id: NonEmptyString
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def valid_line_range(self) -> Self:
        if (self.start_line is None) != (self.end_line is None):
            raise ValueError("Line ranges require both start_line and end_line.")
        if self.start_line is not None and self.end_line < self.start_line:
            raise ValueError("end_line must not precede start_line.")
        return self


class Finding(BlackboardRecord):
    """An investigator's claim, retained even when evidence validation fails.

    Keep category, basis, classification, stable_id, group_id, assessed_context,
    adaptation analysis and other investigator-specific fields in details.
    Review outcomes belong to FindingDecision, not to this record.
    """

    title: NonEmptyString
    description: NonEmptyString
    kind: Literal["violation", "design_observation"]
    criterion_id: NonEmptyString
    criterion: Criterion
    components: tuple[NonEmptyString, ...] = Field(min_length=1)
    justification: str
    modularity_impact: str
    severity: Severity | None = None
    confidence: Confidence | None = None
    evidence_ids: tuple[NonEmptyString, ...] = ()
    assessment_ids: tuple[NonEmptyString, ...] = Field(
        default=(),
        description="Blackboard assessment references, when applicable.",
    )
    recommendation: str | None = None

    @model_validator(mode="after")
    def matching_criterion(self) -> Self:
        if self.criterion_id != self.criterion.id:
            raise ValueError("criterion_id must match criterion.id.")
        return self


class Assessment(BlackboardRecord):
    """Coordinator/manager synthesis, including empty, partial and failed results.

    Investigator-local technical assessments remain in Finding.details or the
    original report; their local IDs are not blackboard assessment references.
    """

    repository_id: NonEmptyString
    commit: NonEmptyString | None = None
    snapshot_hash: NonEmptyString
    objective: str
    targets: tuple[NonEmptyString, ...] = ()
    quality_attribute: NonEmptyString | None = None
    scope: str | dict[str, JsonValue] = ""
    status: Literal["completed", "complete", "partial", "failed"]
    termination_reason: str
    summary: str = ""
    interpretation: str = ""
    finding_ids: tuple[NonEmptyString, ...] = ()
    assessment_ids: tuple[NonEmptyString, ...] = ()
    evidence_ids: tuple[NonEmptyString, ...] = ()
    confidence: Confidence | None = None
    limitations: tuple[NonEmptyString, ...] = ()
    consolidated_findings: tuple[dict[str, JsonValue], ...] = Field(
        default=(),
        description="Original groups, including supported/disputed status and contributions.",
    )
    coverage: dict[str, JsonValue] = Field(default_factory=dict)
    gaps: tuple[dict[str, JsonValue], ...] = Field(
        default=(),
        validation_alias=AliasChoices("gaps", "material_gaps", "unresolved_gaps"),
    )
    resolved_gap_ids: tuple[NonEmptyString, ...] = ()
    withdrawn_finding_refs: tuple[NonEmptyString, ...] = ()
    conclusions: tuple[dict[str, JsonValue], ...] = ()
    relationships: tuple[dict[str, JsonValue], ...] = Field(
        default=(),
        validation_alias=AliasChoices("relationships", "finding_relationships", "links"),
    )
    consumption: Consumption = Field(default_factory=Consumption)
    rounds_completed: int = Field(default=0, ge=0)
    duration_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def no_self_reference(self) -> Self:
        if self.id in self.assessment_ids:
            raise ValueError("An assessment cannot reference itself.")
        return self


class FindingDecision(BlackboardRecord):
    """Acceptance, rejection or deduplication by a coordinator or reviewer."""

    finding_id: NonEmptyString
    verdict: Literal["accepted", "rejected", "insufficient_evidence", "duplicate"] = Field(
        validation_alias=AliasChoices("verdict", "status", "validation_status"),
    )
    rationale: NonEmptyString = Field(
        validation_alias=AliasChoices("rationale", "review_rationale"),
    )
    severity: Severity | None = None
    confidence: Confidence | None = None
    evidence_ids: tuple[NonEmptyString, ...] = ()
    canonical_finding_id: NonEmptyString | None = Field(
        default=None,
        validation_alias=AliasChoices("canonical_finding_id", "duplicate_of"),
        description="Finding retained when the reviewed finding is a duplicate.",
    )

    @model_validator(mode="after")
    def valid_duplicate_reference(self) -> Self:
        if self.verdict == "duplicate":
            if self.canonical_finding_id is None:
                raise ValueError("Duplicate decisions require a canonical_finding_id.")
            if self.canonical_finding_id == self.finding_id:
                raise ValueError("A finding cannot be a duplicate of itself.")
        elif self.canonical_finding_id is not None:
            raise ValueError("Only duplicate decisions may reference a canonical finding.")
        return self
