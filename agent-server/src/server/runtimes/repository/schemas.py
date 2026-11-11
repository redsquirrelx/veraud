"""Shared execution and evidence contracts; no role-specific report schemas."""

from typing import Annotated, Any, Literal, Self

from pydantic import Field, model_validator

from config.agents.base import RepositoryContract as AgentContract
from config.agents.repository_execution import ExecutionBudget

from ...agent_services.budgeting.usage import BudgetUsage as BudgetUsage  # noqa: PLC0414 - compatibility re-export

Identifier = Annotated[str, Field(min_length=1)]
SnapshotHash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


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
