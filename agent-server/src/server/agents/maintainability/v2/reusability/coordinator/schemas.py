"""Reusability V2 planning, invocation receipts and deterministic final assessment."""

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from server.agents.architecture_context import ArchitectureContextResult
from server.contracts.audit import (
    Consumption,
    Contract,
    EvidenceReference,
    InvestigationCommitment,
)
from server.runtimes.coordination.contracts import (
    AgentCapability,
    AgentFindingContribution,
    AgentInvocation,
    DelegationAssignment,
    RawAgentInvocation,
)
from server.runtimes.repository.access import repository_relative_path


class InvestigatorCapability(AgentCapability[str]):
    id: str = Field(min_length=1)
    agent_name: str = Field(min_length=1)
    capability: str = Field(min_length=1)
    problem_types: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class ReusabilityRequest(Contract):
    objective: str = Field(min_length=1, description="Delegated objective, or the direct standalone request.")
    original_objective: str | None = Field(default=None, min_length=1)
    targets: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    repository_context: str = ""
    documented_architecture: ArchitectureContextResult | None = Field(default=None,
        description="Transport-only documentary input; forwarded only to investigators declaring documented_architecture, never to the coordinator's model.")
    follow_up: list[InvestigationCommitment] = Field(default_factory=list, max_length=40)
    follow_up_diagnostics: list[str] = Field(default_factory=list)
    investigator_selection: list[str] | None = None
    continuations: dict[str, Any] = Field(default_factory=dict,
        description="Prior investigator results; passed only to native continuation contracts, never re-planned by this coordinator.")

    @property
    def architectural_context(self):
        return self.repository_context

    @field_validator("targets")
    @classmethod
    def normalize_targets(cls, values):
        return sorted({repository_relative_path(value) for value in values})


class InvestigationAssignment(Contract):
    investigator_id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    targets: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)


class ReusabilityPlan(Contract):
    objective: str = Field(min_length=1)
    assignments: list[InvestigationAssignment]
    uncovered_requirements: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class Assignment(DelegationAssignment[str]):
    source: InvestigationAssignment
    request: dict[str, Any] | None = None


class RawInvocation(RawAgentInvocation[Assignment]):
    """Full original response, also retained when canonical validation fails."""


class InvocationRecord(AgentInvocation[Assignment, Any]):
    """Actual specialized result validated through InvestigatorSpec.result_class."""


class FindingContribution(AgentFindingContribution[str, Any]):
    """An investigator's unmodified original Finding, including specialized fields."""


class ConsolidatedFinding(Contract):
    id: str
    concern: str
    affected_components: list[str]
    evidence: list[EvidenceReference]
    contributions: list[FindingContribution]
    severity: str
    confidence: float
    limitations: list[str] = Field(default_factory=list)
    document_claim_ids: list[str] = Field(default_factory=list)


class FindingRelation(Contract):
    finding_refs: list[str] = Field(min_length=2, max_length=2)
    shared_components: list[str] = Field(default_factory=list)
    shared_evidence: list[str] = Field(default_factory=list)
    interpretation: Literal["shared_anchors_only"] = "shared_anchors_only"


class ReusabilityCoverage(Contract):
    selected_investigation_ids: list[str]
    evaluated_investigation_ids: list[str]
    completed_investigation_ids: list[str]
    partial_investigation_ids: list[str]
    failed_investigation_ids: list[str]
    not_executed_investigation_ids: list[str]
    observed_source_paths: list[str]
    global_compliance_established: Literal[False] = False


class ReusabilityResult(Contract):
    assessment_id: str
    repository_id: str
    commit: str | None
    snapshot_hash: str
    objective: str
    targets: list[str]
    request: ReusabilityRequest
    plan: ReusabilityPlan | None
    investigator_registry: list[InvestigatorCapability]
    initial_plan: list[Assignment]
    execution_records: list[RawInvocation]
    invocations: list[InvocationRecord]
    consolidated_findings: list[ConsolidatedFinding]
    evidence: dict[str, EvidenceReference]
    links: list[FindingRelation]
    coverage: ReusabilityCoverage
    uncovered_requirements: list[str]
    material_gaps: list[dict[str, Any]]
    status: Literal["completed", "partial", "failed", "not_applicable"]
    termination_reason: str
    summary: str
    limitations: list[str]
    consumption: Consumption
    duration_seconds: float
    node_transitions: list[str]

    @model_validator(mode="after")
    def references_exist(self):
        invocations = {row.assignment.invocation_id for row in self.invocations}
        findings = {finding.id for finding in self.consolidated_findings}
        if len(findings) != len(self.consolidated_findings) or any(
            contribution.invocation_id not in invocations or not isinstance(contribution.finding, dict)
            or contribution.reference != f"{contribution.invocation_id}/{contribution.finding.get('id')}"
            for finding in self.consolidated_findings for contribution in finding.contributions
        ) or any(len(set(link.finding_refs)) != 2 or set(link.finding_refs) - findings
            or set(link.shared_evidence) - self.evidence.keys() for link in self.links):
            raise ValueError("Invalid assessment finding/provenance references")
        if self.status == "completed" and (not self.invocations or any(row.status != "completed" for row in self.invocations)):
            raise ValueError("Incomplete invocations cannot establish a completed assessment")
        return self
