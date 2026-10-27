"""Dimension-neutral delegation and synthesis contracts."""

from typing import Any, Literal

from pydantic import Field

from config.agents.repository_execution import ExecutionBudget
from server.contracts.audit import (
    Consumption,
    Contract,
    EvidenceReference,
    InvestigationCommitment,
)
from server.services.execution_failures import ExecutionFailure


class AgentCapability[AgentIdT: str](Contract):
    """Advertised capability of any delegated agent."""

    id: AgentIdT
    agent_name: str
    capability: str

class DelegationAssignment[AgentIdT: str](Contract):
    """Invocation identity and work scope, independent of the delegated agent's role."""

    invocation_id: str
    investigator_id: AgentIdT
    round: int
    question: str
    targets: list[str]
    evidence_refs: list[str] = Field(default_factory=list)
    gap_ids: list[str] = Field(default_factory=list)
    budget: ExecutionBudget | None = None
    commitments: list[InvestigationCommitment] = Field(default_factory=list, max_length=40)
    diagnostics: list[str] = Field(default_factory=list)

class AgentInvocation[AssignmentT: Contract, ResultT: Contract](Contract):
    """Collected result of a delegated execution, with accounting and partial failures."""

    assignment: AssignmentT
    status: Literal["completed", "partial", "failed", "timeout", "skipped"]
    result: ResultT | None = None
    evidence: list[EvidenceReference] = Field(default_factory=list)
    consumption: Consumption = Field(default_factory=Consumption)
    duration_seconds: float = 0
    error: str | None = None
    failure: ExecutionFailure | None = None
    warnings: list[str] = Field(default_factory=list)

class RawAgentInvocation[AssignmentT: Contract](Contract):
    """Unvalidated response associated with a delegated assignment."""

    assignment: AssignmentT
    status: Literal["received", "failed", "timeout", "skipped"]
    value: Any = None
    error: str | None = None
    failure: ExecutionFailure | None = None
    duration_seconds: float = 0
    evidence: list[EvidenceReference] = Field(default_factory=list)

class CoordinatorEvidenceGap[AgentIdT: str](Contract):
    """Evidence gap attributable to an optional delegated agent."""

    id: str
    kind: Literal["missing_evidence", "contradiction", "essential_failure", "synthesis_failure"]
    investigator_id: AgentIdT | None
    question: str
    targets: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    finding_refs: list[str] = Field(default_factory=list)
    material: bool = True
    task_type: Literal["investigation", "source_inspection", "validation_repair", "external_context", "deferred_work", "contradiction"] = "investigation"
    commitments: list[InvestigationCommitment] = Field(default_factory=list, max_length=40)
    diagnostics: list[str] = Field(default_factory=list)

class ProposedEvidenceGap[AgentIdT: str](Contract):
    """Bounded synthesis proposal for a delegated agent's follow-up investigation."""

    kind: Literal["missing_evidence", "contradiction"]
    investigator_id: AgentIdT
    question: str = Field(min_length=1, max_length=2000)
    targets: list[str] = Field(default_factory=list, max_length=12)
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)
    finding_refs: list[str] = Field(default_factory=list, max_length=8)

class FindingGroup(Contract):
    finding_refs: list[str] = Field(min_length=2, max_length=12)

class GapResolution(Contract):
    gap_id: str
    invocation_id: str
    evidence_refs: list[str] = Field(min_length=1, max_length=8)
    explanation: str = Field(min_length=1, max_length=2000)
    withdrawn_finding_refs: list[str] = Field(default_factory=list, max_length=8)

class CoordinatorSynthesis[GapT: Contract](Contract):
    """Synthesis shared by coordinators, parameterized by their gap proposals."""

    summary: str = Field(max_length=3000)
    groups: list[FindingGroup] = Field(default_factory=list, max_length=24)
    gaps: list[GapT] = Field(default_factory=list, max_length=12)
    resolutions: list[GapResolution] = Field(default_factory=list, max_length=12)

class AgentFindingContribution[AgentIdT: str, FindingT: Contract](Contract):
    """An agent's original finding and the invocation that produced it."""

    reference: str
    invocation_id: str
    investigator_id: AgentIdT
    finding: FindingT

class ConsolidatedKnowledge[ContributionT: Contract](Contract):
    """A consolidated concern retaining the original agents' contributions."""

    id: str
    concern: str
    affected_components: list[str]
    status: Literal["supported", "disputed"]
    evidence: list[EvidenceReference]
    contributions: list[ContributionT]
    severity: str | None = None
    confidence: float | None = None
    limitations: list[str] = Field(default_factory=list)

class CoordinatorResult[
    CapabilityT: Contract,
    AssignmentT: Contract,
    InvocationT: Contract,
    ConsolidatedT: Contract,
    GapT: Contract,
](Contract):
    """Coordinator result envelope, parameterized by the concrete child contracts."""

    assessment_id: str
    repository_id: str
    commit: str | None
    snapshot_hash: str
    objective: str
    targets: list[str]
    status: Literal["completed", "partial", "failed"]
    termination_reason: str
    summary: str
    investigator_registry: list[CapabilityT]
    initial_plan: list[AssignmentT]
    invocations: list[InvocationT]
    consolidated_findings: list[ConsolidatedT]
    material_gaps: list[GapT]
    resolved_gap_ids: list[str]
    withdrawn_finding_refs: list[str]
    limitations: list[str]
    rounds_completed: int
    consumption: Consumption
    duration_seconds: float
    node_transitions: list[str]
    baseline_assessment_id: str | None = None
