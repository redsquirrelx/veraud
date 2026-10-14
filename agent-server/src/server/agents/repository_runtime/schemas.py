"""Shared execution and evidence contracts; no role-specific report schemas."""

from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(min_length=1)]
SnapshotHash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class AgentContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="after")
    def unique_members(self) -> Self:
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, tuple):
                identifiers = [getattr(item, "id", item) for item in value]
                if len(set(identifiers)) != len(identifiers):
                    raise ValueError(f"Duplicate members in {name}.")
        return self


class ExecutionBudget(AgentContract):
    max_model_calls: int = Field(default=8, ge=1)
    max_total_tokens: int = Field(default=60_000, ge=1000)
    max_input_tokens_per_call: int = Field(default=6000, ge=500)
    max_tokens_per_objective: int = Field(default=20_000, ge=1000)
    max_output_tokens_per_call: int = Field(default=3000, ge=256)
    max_tool_calls: int = Field(default=20, ge=1)
    max_retrieved_characters: int = Field(default=150_000, ge=1)
    max_elapsed_seconds: float = Field(default=600, gt=0, allow_inf_nan=False)


class BudgetUsage(AgentContract):
    model_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    retrieved_characters: int = Field(default=0, ge=0)
    elapsed_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    reported_input_tokens: int = Field(default=0, ge=0)
    reported_output_tokens: int = Field(default=0, ge=0)
    unknown_usage_attempts: int = Field(default=0, ge=0)
    provider_attempts: int = Field(default=0, ge=0)
    provider_retries: int = Field(default=0, ge=0)
    provider_wait_seconds: float = Field(default=0, ge=0)
    accounted_tokens: int = Field(default=0, ge=0)
    estimated_tokens: int = Field(default=0, ge=0)
    token_budget_exhausted: bool = False


class RepositoryInput(AgentContract):
    snapshot_hash: SnapshotHash
    snapshot_schema_version: Literal["1"] = "1"
    budget: ExecutionBudget = Field(default_factory=ExecutionBudget)


class RetrievedEvidence(AgentContract):
    id: Identifier
    snapshot_hash: SnapshotHash
    file_id: Identifier
    content_hash: SnapshotHash
    tool_call_id: Identifier
    kind: Literal["source", "metadata"]
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    snapshot_evidence_ids: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def valid_range(self) -> Self:
        if (self.start_line is None) != (self.end_line is None):
            raise ValueError("Source ranges require both start_line and end_line.")
        if self.kind == "source" and self.start_line is None:
            raise ValueError("Source retrieval requires a line range.")
        if self.start_line is not None and self.end_line < self.start_line:
            raise ValueError("end_line must not precede start_line.")
        return self


class RepositoryToolCall(AgentContract):
    id: Identifier
    name: Identifier
    arguments: dict[str, Any] = Field(default_factory=dict)


class ExecutionIssue(AgentContract):
    id: Identifier
    stage: Identifier
    category: Identifier
    message: Identifier
