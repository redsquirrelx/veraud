"""Small snapshot-bound architectural conclusions and validator handoff."""

from typing import Literal

from pydantic import Field, model_validator

from ..project_analysis.schemas import (
    AnalysisContract,
    BudgetUsage,
    ExecutionIssue,
    RepositoryToolCall,
    RetrievedEvidence,
)
from ..project_analysis.telemetry import ExecutionTelemetry


class ArchitecturalClaim(AnalysisContract):
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


class OrganizationUnit(AnalysisContract):
    name: str = Field(min_length=1, max_length=120)
    file_ids: tuple[str, ...] = Field(min_length=1)
    responsibility: ArchitecturalClaim


class ArchitectureConnection(AnalysisContract):
    source_unit: str
    target_unit: str
    description: ArchitecturalClaim


class ArchitectureClassification(AnalysisContract):
    pattern: str = Field(min_length=1, max_length=100)
    assessment: ArchitecturalClaim


class ArchitectureDeviation(AnalysisContract):
    observed_decision: ArchitecturalClaim
    pattern_expectation: str = Field(min_length=1, max_length=500)
    explanation: str = Field(min_length=1, max_length=700)


class InfrastructureFinding(AnalysisContract):
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


class ArchitectureReport(AnalysisContract):
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


class ArchitectureTurn(AnalysisContract):
    tool_calls: tuple[RepositoryToolCall, ...] = Field(default=(), max_length=4)
    architecture: ArchitectureReport | None = None

    @model_validator(mode="after")
    def action(self):
        if bool(self.tool_calls) == (self.architecture is not None):
            raise ValueError("Return tool_calls OR architecture, never both.")
        return self


class ArchitectureLimits(AnalysisContract):
    max_model_calls: int = Field(default=6, ge=1, le=6)
    max_tool_calls: int = Field(default=10, ge=1, le=10)
    max_prompt_characters: int = Field(default=24000, ge=6000)


class SourceCitation(AnalysisContract):
    evidence_id: str
    file_id: str
    path: str
    start_line: int
    end_line: int
    content_hash: str


class ArchitectureResult(AnalysisContract):
    snapshot_hash: str
    completion_status: Literal["complete", "partial", "failed"]
    architecture: ArchitectureReport | None = None
    citations: tuple[SourceCitation, ...] = ()
    retrieved_evidence: tuple[RetrievedEvidence, ...] = ()
    inspected_file_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    execution_issues: tuple[ExecutionIssue, ...] = ()
    usage: BudgetUsage
    telemetry: ExecutionTelemetry

    @model_validator(mode="after")
    def completion(self):
        if (self.completion_status == "failed") != (self.architecture is None):
            raise ValueError("Only failed architecture runs have no report.")
        return self
