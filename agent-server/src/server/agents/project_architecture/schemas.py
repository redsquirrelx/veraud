"""Small snapshot-bound architectural conclusions and validator handoff."""

from typing import Literal

from pydantic import Field, model_validator

from ..repository_runtime.schemas import (
    AgentContract,
    BudgetUsage,
    ExecutionIssue,
    RepositoryToolCall,
    RetrievedEvidence,
)
from ..repository_runtime.telemetry import ExecutionTelemetry


class ArchitecturalClaim(AgentContract):
    statement: str = Field(min_length=1, max_length=1500)
    scope: str = Field(min_length=1, max_length=250)
    status: Literal["supported", "hypothesis", "unresolved"]
    evidence_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def support(self):
        if self.status == "supported" and not self.evidence_ids:
            raise ValueError(
                "Supported architectural claims require inspected source evidence."
            )
        if self.status != "supported" and not self.limitations:
            raise ValueError("Hypothesis/unresolved claims require limitations.")
        return self


class OrganizationUnit(AgentContract):
    name: str = Field(min_length=1, max_length=120)
    file_ids: tuple[str, ...] = Field(min_length=1)
    responsibility: ArchitecturalClaim


class ArchitectureConnection(AgentContract):
    source_unit: str
    target_unit: str
    description: ArchitecturalClaim


class ArchitectureClassification(AgentContract):
    pattern: str = Field(min_length=1, max_length=100)
    assessment: ArchitecturalClaim
    scope_kind: Literal["local", "repository"] = "local"
    observed_paths: tuple[tuple[ArchitectureConnection, ...], ...] = Field(
        default=(), max_length=2
    )
    observed_dependencies: tuple[ArchitectureConnection, ...] = Field(
        default=(), max_length=6
    )
    assessment_origin: Literal["model", "host_downgrade", "host_fallback"] = "model"
    contrast_question: str | None = Field(default=None, min_length=1, max_length=400)
    contrast_result: ArchitecturalClaim | None = None

    @model_validator(mode="after")
    def investigation(self):
        if self.assessment.status == "supported":
            if (not self.observed_paths and not self.observed_dependencies) or any(
                not path for path in self.observed_paths
            ):
                raise ValueError(
                    "Supported patterns require an observed implementation path or dependency links."
                )
            if any(
                edge.description.status != "supported"
                for path in (*self.observed_paths, self.observed_dependencies)
                for edge in path
            ):
                raise ValueError("Observed paths must contain supported connections.")
            if (
                not self.contrast_question
                or self.contrast_result is None
                or self.contrast_result.status != "supported"
            ):
                raise ValueError(
                    "Supported patterns require a source-backed contrast question and result."
                )
            if self.scope_kind == "repository" and len(self.observed_paths) < 2:
                raise ValueError(
                    "Repository-wide patterns require two independently inspected paths; otherwise use local scope."
                )
        return self


class ArchitectureDeviation(AgentContract):
    observed_decision: ArchitecturalClaim
    pattern_expectation: str = Field(min_length=1, max_length=500)
    explanation: str = Field(min_length=1, max_length=700)


class InfrastructureFinding(AgentContract):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["execution_unit", "communication", "state"]
    configured: ArchitecturalClaim | None = None
    inspected_use: ArchitecturalClaim | None = None

    @model_validator(mode="after")
    def finding(self):
        if self.configured is None and self.inspected_use is None:
            raise ValueError(
                "Infrastructure requires configuration or inspected-use findings."
            )
        return self


class ArchitectureReport(AgentContract):
    organization: tuple[OrganizationUnit, ...] = Field(default=(), max_length=8)
    connections: tuple[ArchitectureConnection, ...] = Field(default=(), max_length=10)
    closest_architecture: ArchitectureClassification | None = None
    supporting_evidence: tuple[ArchitecturalClaim, ...] = Field(
        default=(), max_length=8
    )
    deviations: tuple[ArchitectureDeviation, ...] = Field(default=(), max_length=6)
    infrastructure: tuple[InfrastructureFinding, ...] = Field(default=(), max_length=6)
    explanation: ArchitecturalClaim | None = None
    uncertainties: tuple[str, ...] = Field(default=(), max_length=10)


class ArchitectureTurn(AgentContract):
    tool_calls: tuple[RepositoryToolCall, ...] = Field(default=(), max_length=4)
    architecture: ArchitectureReport | None = None

    @model_validator(mode="after")
    def action(self):
        if bool(self.tool_calls) == (self.architecture is not None):
            raise ValueError("Return tool_calls OR architecture, never both.")
        return self


class ArchitectureLimits(AgentContract):
    soft_token_budgets: bool = True
    max_model_calls: int = Field(default=8, ge=1, le=8)
    max_tool_calls: int = Field(default=20, ge=1, le=20)
    max_prompt_characters: int = Field(default=36000, ge=6000)
    max_source_characters: int = Field(default=2400, ge=400)


class SourceCitation(AgentContract):
    evidence_id: str
    file_id: str
    path: str
    start_line: int
    end_line: int
    content_hash: str


class ApplicationCoverage(AgentContract):
    project_id: str
    path: str
    status: Literal["explained", "inspected", "uninspected"]
    inspected_file_ids: tuple[str, ...] = ()
    reason: str


class ArchitectureResult(AgentContract):
    snapshot_hash: str
    completion_status: Literal["complete", "partial", "failed"]
    architecture: ArchitectureReport | None = None
    citations: tuple[SourceCitation, ...] = ()
    retrieved_evidence: tuple[RetrievedEvidence, ...] = ()
    inspected_file_ids: tuple[str, ...] = ()
    application_coverage: tuple[ApplicationCoverage, ...] = ()
    reference_repairs: dict[str, str] = Field(default_factory=dict)
    limitations: tuple[str, ...] = ()
    execution_issues: tuple[ExecutionIssue, ...] = ()
    usage: BudgetUsage
    telemetry: ExecutionTelemetry

    @model_validator(mode="after")
    def completion(self):
        if (self.completion_status == "failed") != (self.architecture is None):
            raise ValueError("Only failed architecture runs have no report.")
        return self
