"""General coordinator outputs and concrete maintainability coordination contracts."""

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, SerializeAsAny

from ...runtimes.repository.schemas import ExecutionBudget
from .base import (
    AuditRequest,  # noqa: F401 - compatibility export
    AuditResult,
    Consumption,
    Contract,
    EvidenceReference,
    Finding,
    ScopedAuditRequest,
    TargetContext,
)
from .investigator import (
    AbstractionFinding,
    AbstractionResult,
    AdaptabilityFinding,
    ComponentAdaptabilityResult,
    ReuseFinding,
    ReuseOpportunityResult,
)

InvestigatorId = Literal["architecture_boundary", "responsibility", "dependency_impact"]
Route = Literal["reinvestigate", "finalize", "finalize_limited"]


class ModularityRequest(ScopedAuditRequest):
    objective: str = "Assess software modularity within the declared scope using the three specialized investigators."


class AgentCapability[AgentIdT: str](Contract):
    """Advertised capability of any delegated agent."""

    id: AgentIdT
    agent_name: str
    capability: str


class InvestigatorCapability(AgentCapability[InvestigatorId]):
    """Capabilities of the modularity investigators."""


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


class Assignment(DelegationAssignment[InvestigatorId]):
    """Assignment to a modularity investigator."""


class AgentInvocation[AssignmentT: Contract, ResultT: Contract](Contract):
    """Collected result of a delegated execution, with accounting and partial failures."""

    assignment: AssignmentT
    status: Literal["completed", "partial", "failed", "timeout", "skipped"]
    result: ResultT | None = None
    evidence: list[EvidenceReference] = Field(default_factory=list)
    consumption: Consumption = Field(default_factory=Consumption)
    duration_seconds: float = 0
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)


class InvocationRecord(AgentInvocation[Assignment, SerializeAsAny[AuditResult]]):
    """Collected modularity investigator result."""


class RawAgentInvocation[AssignmentT: Contract](Contract):
    """Unvalidated response associated with a delegated assignment."""

    assignment: AssignmentT
    status: Literal["received", "failed", "timeout", "skipped"]
    value: Any = None
    error: str | None = None
    duration_seconds: float = 0
    evidence: list[EvidenceReference] = Field(default_factory=list)


class RawInvocation(RawAgentInvocation[Assignment]):
    """Unvalidated modularity investigator response."""


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


class EvidenceGap(CoordinatorEvidenceGap[InvestigatorId]):
    """Evidence gap within modularity coordination."""


class ProposedEvidenceGap[AgentIdT: str](Contract):
    """Bounded synthesis proposal for a delegated agent's follow-up investigation."""

    kind: Literal["missing_evidence", "contradiction"]
    investigator_id: AgentIdT
    question: str = Field(min_length=1, max_length=2000)
    targets: list[str] = Field(default_factory=list, max_length=12)
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)
    finding_refs: list[str] = Field(default_factory=list, max_length=8)


class ProposedGap(ProposedEvidenceGap[InvestigatorId]):
    """Proposed modularity investigation gap."""


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


class SynthesisDraft(CoordinatorSynthesis[ProposedGap]):
    """Modularity synthesis draft."""


class AgentFindingContribution[AgentIdT: str, FindingT: Contract](Contract):
    """An agent's original finding and the invocation that produced it."""

    reference: str
    invocation_id: str
    investigator_id: AgentIdT
    finding: FindingT


class FindingContribution(AgentFindingContribution[InvestigatorId, SerializeAsAny[Finding]]):
    """Modularity investigator contribution."""


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


class ConsolidatedFinding(ConsolidatedKnowledge[FindingContribution]):
    """Consolidated modularity finding."""


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


class ModularityAssessment(CoordinatorResult[
    InvestigatorCapability, Assignment, InvocationRecord, ConsolidatedFinding, EvidenceGap,
]):
    """Assessment produced by the modularity coordinator."""


ReusabilityInvestigatorId = Literal["abstraction", "reuse_opportunity", "component_adaptability"]
InvestigationResult = Annotated[
    AbstractionResult | ReuseOpportunityResult | ComponentAdaptabilityResult,
    Field(discriminator="investigator"),
]


class ReusabilityRoute(StrEnum):
    YES = "yes"
    NO = "no"


class ReusabilityRequest(ScopedAuditRequest, TargetContext):
    objective: str = "Assess reusability through abstractions, shared-implementation opportunities and context-specific adaptation constraints."


class ReusabilityInvestigatorCapability(AgentCapability[ReusabilityInvestigatorId]):
    model_config = ConfigDict(title="InvestigatorCapability")


class ReusabilityAssignment(DelegationAssignment[ReusabilityInvestigatorId]):
    model_config = ConfigDict(title="Assignment")

    request_id: str
    round_id: str
    priority: Literal["high", "medium", "low"] = "high"
    evidence_expectations: list[str] = Field(default_factory=list)


class ReusabilityInvocationRecord(AgentInvocation[ReusabilityAssignment, InvestigationResult]):
    model_config = ConfigDict(title="InvocationRecord")


class ReusabilityRawInvocation(RawAgentInvocation[ReusabilityAssignment]):
    model_config = ConfigDict(title="RawInvocation")


class ReusabilityEvidenceGap(CoordinatorEvidenceGap[ReusabilityInvestigatorId]):
    model_config = ConfigDict(title="EvidenceGap")


class ReusabilityProposedGap(ProposedEvidenceGap[ReusabilityInvestigatorId]):
    model_config = ConfigDict(title="ProposedGap")


class ReusabilityFindingContribution(AgentFindingContribution[
    ReusabilityInvestigatorId, AbstractionFinding | ReuseFinding | AdaptabilityFinding,
]):
    model_config = ConfigDict(title="FindingContribution")


class ReusabilityConsolidatedFinding(ConsolidatedKnowledge[ReusabilityFindingContribution]):
    model_config = ConfigDict(title="ConsolidatedFinding")


class Conclusion(Contract):
    statement: str = Field(min_length=1, max_length=2000)
    finding_refs: list[str] = Field(min_length=1, max_length=12)
    evidence_refs: list[str] = Field(min_length=1, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=12)
    status: Literal["supported", "disputed"] = "supported"


class FindingRelationship(Contract):
    kind: Literal["supports", "tradeoff", "conflicts", "depends_on"]
    finding_refs: list[str] = Field(min_length=2, max_length=8)
    rationale: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[str] = Field(min_length=1, max_length=12)
    resolution_status: Literal["observed", "unresolved", "resolved"] = "observed"


class ReusabilitySynthesisDraft(CoordinatorSynthesis[ReusabilityProposedGap]):
    model_config = ConfigDict(title="SynthesisDraft")

    conclusions: list[Conclusion] = Field(default_factory=list, max_length=16)
    relationships: list[FindingRelationship] = Field(default_factory=list, max_length=24)


class ContinuationDecision(Contract):
    route: ReusabilityRoute
    reason: str
    rationale: str = ""
    material_gap_ids: list[str]
    pending_request_ids: list[str]


class ReusabilitySynthesisRound(Contract):
    model_config = ConfigDict(title="SynthesisRound")

    round: int
    draft: ReusabilitySynthesisDraft | None
    decision: ContinuationDecision


class ReusabilityAssessment(CoordinatorResult[
    ReusabilityInvestigatorCapability, ReusabilityAssignment, ReusabilityInvocationRecord,
    ReusabilityConsolidatedFinding, ReusabilityEvidenceGap,
]):
    investigator: Literal["ReusabilityAgent"] = "ReusabilityAgent"
    quality_attribute: Literal["reusability"] = "reusability"
    target_context: str | None = None
    conclusions: list[Conclusion] = Field(default_factory=list)
    finding_relationships: list[FindingRelationship] = Field(default_factory=list)
    synthesis_history: list[ReusabilitySynthesisRound] = Field(default_factory=list)
    continuation_decision: ContinuationDecision
    coverage: dict[str, list[dict]] = Field(default_factory=dict)
