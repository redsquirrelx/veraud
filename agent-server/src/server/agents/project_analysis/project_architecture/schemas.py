"""Small snapshot-bound architectural conclusions and validator handoff."""

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
from .config import ArchitectureLimits  # noqa: F401 - compatibility export


class ArchitecturalClaim(AgentContract):
    statement: str = Field(min_length=1, max_length=3000)
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
    kind: Literal["calls", "depends_on", "implements", "relationship"] = "relationship"


class ArchitectureClassification(AgentContract):
    pattern: str = Field(min_length=1, max_length=100)
    assessment: ArchitecturalClaim
    scope_kind: Literal["local", "repository"] = "local"
    observed_paths: tuple[tuple[ArchitectureConnection, ...], ...] = Field(
        default=(), max_length=4
    )
    observed_dependencies: tuple[ArchitectureConnection, ...] = Field(
        default=(), max_length=12
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


class RelationshipInvestigation(AgentContract):
    unit_name: str = Field(min_length=1, max_length=120)
    status: Literal["connected", "isolated", "unresolved"]
    assessment: ArchitecturalClaim
    examined_file_ids: tuple[str, ...] = ()
    resolution_blocker: (
        Literal["evidence_inconclusive", "dynamic_resolution"] | None
    ) = None
    blocker_reason: str | None = Field(default=None, min_length=1, max_length=700)

    @model_validator(mode="after")
    def certainty(self):
        if (self.resolution_blocker is None) != (self.blocker_reason is None):
            raise ValueError(
                "A resolution blocker requires a concrete reason, and vice versa."
            )
        if self.status != "unresolved" and self.resolution_blocker:
            raise ValueError(
                "Only unresolved investigations may declare a resolution blocker."
            )
        if self.status == "connected" and self.assessment.status != "supported":
            raise ValueError(
                "Verified connection investigations require supported assessments; use unresolved otherwise."
            )
        if self.status == "unresolved" and self.assessment.status == "supported":
            raise ValueError(
                "Unresolved relationship investigations require hypothesis/unresolved certainty and limitations."
            )
        if self.status == "isolated" and (
            not self.examined_file_ids or self.assessment.status != "supported"
        ):
            raise ValueError(
                "Isolation requires inspected files and a supported, precisely scoped assessment."
            )
        return self


class DiagramGroup(AgentContract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    title: str = Field(min_length=1, max_length=120)
    scope: str = Field(min_length=1, max_length=250)


class DiagramNode(AgentContract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    unit_ref: str = Field(pattern=r"^/organization/(0|[1-9][0-9]*)$")
    group_id: str | None = None
    role: Literal[
        "component",
        "actor",
        "interface",
        "service",
        "adapter",
        "data_store",
        "event_bus",
    ] = "component"


class DiagramEdge(AgentContract):
    source: str
    target: str
    claim_ref: str = Field(min_length=1, max_length=200)
    kind: Literal["calls", "depends_on", "implements", "relationship"]
    label: str | None = Field(default=None, min_length=1, max_length=120)


class DiagramDeviation(AgentContract):
    deviation_ref: str = Field(pattern=r"^/deviations/(0|[1-9][0-9]*)$")
    node_ids: tuple[str, ...] = Field(min_length=1, max_length=12)
    explanation: str = Field(min_length=1, max_length=400)


class DiagramView(AgentContract):
    title: str = Field(min_length=1, max_length=120)
    scope: str = Field(min_length=1, max_length=250)
    view_kind: Literal["structure", "dependencies", "flow", "deployment", "custom"] = (
        "structure"
    )
    direction: Literal["LR", "TB"] = "LR"
    groups: tuple[DiagramGroup, ...] = Field(default=(), max_length=8)
    nodes: tuple[DiagramNode, ...] = Field(min_length=1, max_length=12)
    edges: tuple[DiagramEdge, ...] = Field(default=(), max_length=24)
    deviations: tuple[DiagramDeviation, ...] = Field(default=(), max_length=10)
    limitations: tuple[str, ...] = Field(default=(), max_length=10)


class ArchitectureDiagram(DiagramView):
    views: tuple[DiagramView, ...] = Field(default=(), max_length=2)


class ArchitectureReport(AgentContract):
    organization: tuple[OrganizationUnit, ...] = Field(default=(), max_length=12)
    connections: tuple[ArchitectureConnection, ...] = Field(default=(), max_length=18)
    closest_architecture: ArchitectureClassification | None = None
    supporting_evidence: tuple[ArchitecturalClaim, ...] = Field(
        default=(), max_length=24
    )
    deviations: tuple[ArchitectureDeviation, ...] = Field(default=(), max_length=10)
    infrastructure: tuple[InfrastructureFinding, ...] = Field(default=(), max_length=10)
    explanation: ArchitecturalClaim | None = None
    uncertainties: tuple[str, ...] = Field(default=(), max_length=16)
    diagram: ArchitectureDiagram | None = None
    relationship_investigations: tuple[RelationshipInvestigation, ...] = Field(
        default=(), max_length=12
    )

    @model_validator(mode="after")
    def diagram_references(self):
        from .diagram import validate_diagram

        validate_diagram(self)
        return self


class ArchitectureTurn(AgentContract):
    tool_calls: tuple[RepositoryToolCall, ...] = Field(default=(), max_length=8)
    architecture: ArchitectureReport | None = None

    @model_validator(mode="after")
    def action(self):
        if self.tool_calls and self.architecture is not None:
            raise ValueError("Return tool_calls OR architecture, never both.")
        if not self.tool_calls and self.architecture is None:
            raise ValueError(
                "No action returned: provide non-empty tool_calls OR an architecture report."
            )
        return self


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


class RelationshipCoverage(AgentContract):
    unit_name: str
    status: Literal["connected", "isolated", "unresolved", "uninvestigated"]
    pending_paths: tuple[str, ...] = ()
    pending_units: tuple[str, ...] = ()
    reason: str
    resolution_blocker: str | None = None
    blocker_reason: str | None = None


class ArchitectureResult(AgentContract):
    snapshot_hash: str
    completion_status: Literal["complete", "partial", "failed"]
    architecture: ArchitectureReport | None = None
    citations: tuple[SourceCitation, ...] = ()
    retrieved_evidence: tuple[RetrievedEvidence, ...] = ()
    inspected_file_ids: tuple[str, ...] = ()
    application_coverage: tuple[ApplicationCoverage, ...] = ()
    relationship_coverage: tuple[RelationshipCoverage, ...] = ()
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
