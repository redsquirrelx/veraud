"""Small orientation contracts; no planning, flow, or architecture contracts."""

from typing import Literal

from pydantic import Field, model_validator

from ....runtimes.repository.schemas import (
    AgentContract,
    BudgetUsage,
    ExecutionIssue,
    RepositoryToolCall,
    RetrievedEvidence,
)
from ....runtimes.repository.telemetry import ExecutionTelemetry
from .config import OrientationLimits  # noqa: F401 - compatibility export


class Observation(AgentContract):
    statement: str = Field(min_length=1, max_length=2500)
    status: Literal["supported", "hypothesis", "unresolved"]
    evidence_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def support(self):
        if self.status == "supported" and not self.evidence_ids:
            raise ValueError(
                "Supported observations require inspected source evidence."
            )
        if self.status != "supported" and not self.limitations:
            raise ValueError("Uncertain observations require explicit limitations.")
        return self


class Component(AgentContract):
    name: str = Field(min_length=1, max_length=150)
    file_ids: tuple[str, ...] = Field(min_length=1)
    responsibility: Observation


class StartingPoint(AgentContract):
    file_id: str
    reason: str = Field(min_length=1, max_length=500)


class Orientation(AgentContract):
    project_type: Observation | None = None
    purpose: Observation | None = None
    components: tuple[Component, ...] = Field(default=(), max_length=6)
    starting_points: tuple[StartingPoint, ...] = Field(default=(), max_length=8)
    uncertainties: tuple[str, ...] = Field(default=(), max_length=10)


class OrientationTurn(AgentContract):
    tool_calls: tuple[RepositoryToolCall, ...] = Field(default=(), max_length=3)
    orientation: Orientation | None = None

    @model_validator(mode="after")
    def action(self):
        if bool(self.tool_calls) == (self.orientation is not None):
            raise ValueError("Return tool_calls OR orientation, never both.")
        return self


class OrientationResult(AgentContract):
    snapshot_hash: str
    completion_status: Literal["complete", "partial", "failed"]
    orientation: Orientation | None = None
    retrieved_evidence: tuple[RetrievedEvidence, ...] = ()
    inspected_file_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    execution_issues: tuple[ExecutionIssue, ...] = ()
    usage: BudgetUsage
    telemetry: ExecutionTelemetry
