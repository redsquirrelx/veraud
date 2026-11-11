"""Canonical V2 Manager contracts; subordinate payloads retain their own schemas."""

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from server.agents.architecture_context import ArchitectureContextResult
from server.contracts.audit import Consumption, Contract, EvidenceReference
from server.runtimes.coordination.contracts import AgentCapability
from server.runtimes.repository.access import repository_relative_path
from server.runtimes.repository.schemas import ExecutionBudget
from server.services.execution_failures import ExecutionFailure


class CoordinatorCapability(AgentCapability[str]):
    """Public specialty/capability plus problems and restrictions, not internals."""

    id: str = Field(min_length=1)
    agent_name: str = Field(min_length=1)
    capability: str = Field(min_length=1)
    problem_types: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class MaintainabilityRequest(Contract):
    objective: str = Field(default="Investigar la mantenibilidad arquitectónica de la revisión seleccionada.", min_length=1)
    targets: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    repository_context: str = ""
    maintainability_selection: dict[str, list[str]] | None = None
    documented_architecture: ArchitectureContextResult | None = Field(default=None,
        description="Transport-only documentary input for opt-in investigators; excluded from manager model prompts.")

    @field_validator("targets")
    @classmethod
    def normalize_targets(cls, values):
        return sorted({repository_relative_path(value) for value in values})


class CoordinatorAssignment(Contract):
    coordinator_id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    scope: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)


class AuditPlan(Contract):
    objective: str = Field(min_length=1)
    assignments: list[CoordinatorAssignment]
    uncovered_requirements: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class CoordinatorExecutionRecord(Contract):
    """Uncollected output, not a synthesized or accepted assessment."""

    assignment_id: str
    assignment: CoordinatorAssignment
    request: dict[str, Any] | None = None
    budget: ExecutionBudget | None = None
    status: Literal["completed", "partial", "failed", "timeout", "skipped"]
    result: Any = None
    consumption: Consumption = Field(default_factory=Consumption)
    limitations: list[str] = Field(default_factory=list)
    failure: ExecutionFailure | None = None
    evidence: list[EvidenceReference] = Field(default_factory=list)
    duration_seconds: float = 0


class AuditIssue(Contract):
    code: str
    assignment_id: str = ""
    location: str = ""
    message: str


class FindingOrigin(Contract):
    assignment_id: str
    coordinator_id: str
    finding_id: str | None
    location: str


class AuditFinding(Contract):
    payload: dict[str, Any]
    origins: list[FindingOrigin]
    evidence_refs: list[str] = Field(default_factory=list)
    integrity_issues: list[str] = Field(default_factory=list)


class CollectedAssessment(Contract):
    assignment_id: str
    coordinator_id: str
    status: Literal["completed", "partial", "failed", "timeout", "skipped"]
    result_kind: Literal["planning", "assessment"]
    evaluation_performed: bool = False
    findings: list[AuditFinding] = Field(default_factory=list)
    evidence: dict[str, EvidenceReference] = Field(default_factory=dict)
    reported_coverage: Any = None
    inconclusive: list[Any] = Field(default_factory=list)
    issues: list[AuditIssue] = Field(default_factory=list)


class FindingRelation(Contract):
    finding_refs: list[str] = Field(min_length=2, max_length=2)
    shared_components: list[str] = Field(default_factory=list)
    shared_evidence: list[str] = Field(default_factory=list)
    shared_references: list[str] = Field(default_factory=list)
    interpretation: Literal["shared_anchors_only"] = "shared_anchors_only"


class AuditCoverage(Contract):
    selected_assignment_ids: list[str] = Field(default_factory=list)
    evaluated_assignment_ids: list[str] = Field(default_factory=list)
    completed_assignment_ids: list[str] = Field(default_factory=list)
    partial_assignment_ids: list[str] = Field(default_factory=list)
    failed_assignment_ids: list[str] = Field(default_factory=list)
    not_executed_assignment_ids: list[str] = Field(default_factory=list)
    observed_source_paths: list[str] = Field(default_factory=list)
    uncovered_requirements: list[str] = Field(default_factory=list)
    global_compliance_established: Literal[False] = False


class AssessmentSynthesis(Contract):
    findings: dict[str, AuditFinding] = Field(default_factory=dict)
    evidence: dict[str, EvidenceReference] = Field(default_factory=dict)
    links: list[FindingRelation] = Field(default_factory=list)
    coverage: AuditCoverage = Field(default_factory=AuditCoverage)
    issues: list[AuditIssue] = Field(default_factory=list)


class AuditResult(AssessmentSynthesis):
    quality_attribute: Literal["maintainability"] = "maintainability"
    assessment_id: str
    repository_id: str
    commit: str | None
    snapshot_hash: str
    objective: str
    targets: list[str]
    request: MaintainabilityRequest
    plan: AuditPlan | None
    coordinator_catalog: list[CoordinatorCapability]
    coordinator_results: list[CoordinatorExecutionRecord]
    assessments: list[CollectedAssessment]
    status: Literal["completed", "partial", "failed", "not_applicable"]
    termination_reason: str
    summary: str
    limitations: list[str]
    consumption: Consumption
    duration_seconds: float
    node_transitions: list[str]

    @model_validator(mode="after")
    def valid_references(self):
        receipts = {record.assignment_id for record in self.coordinator_results}
        if any(set(finding.evidence_refs) - self.evidence.keys() or any(origin.assignment_id not in receipts for origin in finding.origins)
            for finding in self.findings.values()):
            raise ValueError("Unknown audit finding origin/evidence")
        if any(len(set(link.finding_refs)) != 2 or set(link.finding_refs) - self.findings.keys()
            or set(link.shared_evidence) - self.evidence.keys() for link in self.links):
            raise ValueError("Unknown or duplicate audit relation reference")
        if self.status == "completed" and (self.issues or not self.assessments or any(a.status != "completed" for a in self.assessments)):
            raise ValueError("Incomplete assessments cannot establish a completed audit")
        return self
