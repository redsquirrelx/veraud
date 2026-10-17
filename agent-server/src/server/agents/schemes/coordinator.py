"""General coordinator outputs and concrete maintainability coordination contracts."""

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, SerializeAsAny

from ...runtimes.repository.schemas import ExecutionBudget
from ...services.execution_failures import ExecutionFailure
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

# Identifiers of the three investigators registered with the modularity coordinator.
InvestigatorId = Literal["architecture_boundary", "responsibility", "dependency_impact"]
# Modularity graph routes after synthesis: investigate again, finalize or finalize with limitations.
Route = Literal["reinvestigate", "finalize", "finalize_limited"]


# Modularity request: specializes the objective while inheriting scope from a neutral base.
# ModularityAgent.run() uses it to delegate boundary, responsibility and dependency-impact work.
class ModularityRequest(ScopedAuditRequest):
    objective: str = "Assess software modularity within the declared scope using the three specialized investigators."


# Advertised agent capability: parameterizes its identifier without fixing an audit dimension.
# Coordinators include these entries in capability registries to describe available delegates.
class AgentCapability[AgentIdT: str](Contract):
    """Advertised capability of any delegated agent."""

    id: AgentIdT
    agent_name: str
    capability: str


# Modularity investigator capability: restricts id to the three implemented investigators.
# Used by the modularity registry when constructing the coordinator's plan and final assessment.
class InvestigatorCapability(AgentCapability[InvestigatorId]):
    """Capabilities of the modularity investigators."""


# Generic work assignment: links an invocation to an agent, round, question, targets and budget.
# Shared by both coordinators' investigator assignments and the manager's coordinator assignments.
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


# Modularity assignment: narrows allowed agent IDs without changing the shared delegation structure.
# Used in ModularityExecution's initial plan, targeted follow-ups and invocation records.
class Assignment(DelegationAssignment[InvestigatorId]):
    """Assignment to a modularity investigator."""


# Collected delegation result: combines typed assignments/results with status, accounting and errors.
# Specialized by coordinators and the manager when converting raw responses into auditable records.
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


# Validated modularity investigator invocation; preserves specialized fields in its result.
# Constructed by collect_findings and retained in ModularityAssessment for execution provenance.
class InvocationRecord(AgentInvocation[Assignment, SerializeAsAny[AuditResult]]):
    """Collected modularity investigator result."""


# Raw delegation response: retains the received value or failure before result validation.
# Used between child execution and collection by the supervising coordinator or manager.
class RawAgentInvocation[AssignmentT: Contract](Contract):
    """Unvalidated response associated with a delegated assignment."""

    assignment: AssignmentT
    status: Literal["received", "failed", "timeout", "skipped"]
    value: Any = None
    error: str | None = None
    failure: ExecutionFailure | None = None
    duration_seconds: float = 0
    evidence: list[EvidenceReference] = Field(default_factory=list)


# Raw modularity investigator response, correlated with the assignment that produced it.
# Returned by delegation; collect_findings validates value against the registered investigator contract.
class RawInvocation(RawAgentInvocation[Assignment]):
    """Unvalidated modularity investigator response."""


# Persistent evidence gap: records the question, supporting references and whether the gap is material.
# Coordinators retain it through synthesis and use it to evaluate targeted follow-up investigations.
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


# Modularity gap: attributes missing information or contradictions to an investigator when applicable.
# ModularityExecution retains it in material_gaps and includes unresolved gaps in its final assessment.
class EvidenceGap(CoordinatorEvidenceGap[InvestigatorId]):
    """Evidence gap within modularity coordination."""


# Bounded gap proposal: links a follow-up question to an agent, targets and existing references.
# Returned by the synthesis model and validated by the coordinator before becoming a retained gap.
class ProposedEvidenceGap[AgentIdT: str](Contract):
    """Bounded synthesis proposal for a delegated agent's follow-up investigation."""

    kind: Literal["missing_evidence", "contradiction"]
    investigator_id: AgentIdT
    question: str = Field(min_length=1, max_length=2000)
    targets: list[str] = Field(default_factory=list, max_length=12)
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)
    finding_refs: list[str] = Field(default_factory=list, max_length=8)


# Follow-up proposal for a modularity investigator, with bounds on text and referenced records.
# Appears in SynthesisDraft.gaps during the modularity coordinator's synthesize_findings node.
class ProposedGap(ProposedEvidenceGap[InvestigatorId]):
    """Proposed modularity investigation gap."""


# Proposed finding group: references at least two contributions without copying their contents.
# Proposed during synthesis; consolidate checks references before merging related concerns.
class FindingGroup(Contract):
    finding_refs: list[str] = Field(min_length=2, max_length=12)


# Proposed gap resolution: cites the invocation and evidence supporting closure of an existing gap.
# Both coordinators receive it in synthesis drafts; it can also propose withdrawing related findings.
class GapResolution(Contract):
    gap_id: str
    invocation_id: str
    evidence_refs: list[str] = Field(min_length=1, max_length=8)
    explanation: str = Field(min_length=1, max_length=2000)
    withdrawn_finding_refs: list[str] = Field(default_factory=list, max_length=8)


# Generic synthesis draft: combines a summary, finding groups, typed gaps and resolution proposals.
# Coordinators specialize it as the structured model-response contract for synthesize_findings.
class CoordinatorSynthesis[GapT: Contract](Contract):
    """Synthesis shared by coordinators, parameterized by their gap proposals."""

    summary: str = Field(max_length=3000)
    groups: list[FindingGroup] = Field(default_factory=list, max_length=24)
    gaps: list[GapT] = Field(default_factory=list, max_length=12)
    resolutions: list[GapResolution] = Field(default_factory=list, max_length=12)


# Modularity synthesis draft: restricts proposed gaps to registered modularity investigators.
# ModularitySynthesisExecution obtains it from the model and host-validates its proposals.
class SynthesisDraft(CoordinatorSynthesis[ProposedGap]):
    """Modularity synthesis draft."""


# Original contribution: links a typed finding to its producing agent and invocation through a reference.
# Coordination indexes use it to group findings while preserving each contributor's provenance.
class AgentFindingContribution[AgentIdT: str, FindingT: Contract](Contract):
    """An agent's original finding and the invocation that produced it."""

    reference: str
    invocation_id: str
    investigator_id: AgentIdT
    finding: FindingT


# Modularity contribution: preserves the complete specialized finding through SerializeAsAny.
# Used as the provenance unit in finding_index and consolidated modularity findings.
class FindingContribution(AgentFindingContribution[InvestigatorId, SerializeAsAny[Finding]]):
    """Modularity investigator contribution."""


# Consolidated concern: gathers components, evidence and contributions with supported/disputed status.
# Built by consolidate without replacing originals; severity and confidence can remain undetermined.
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


# Consolidated modularity finding: groups investigator contributions and their evidence references.
# Included in ModularityAssessment as an auditable concern available to the manager.
class ConsolidatedFinding(ConsolidatedKnowledge[FindingContribution]):
    """Consolidated modularity finding."""


# General coordinator output: parameterizes capability, assignment, invocation, finding and gap types.
# Both coordinators specialize it to deliver synthesis, provenance and accounting to the manager.
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


# Final modularity assessment: binds the common envelope to the three modularity investigators' types.
# Returned by ModularityAgent's finalize_assessment, then validated and consolidated by the manager.
class ModularityAssessment(CoordinatorResult[
    InvestigatorCapability, Assignment, InvocationRecord, ConsolidatedFinding, EvidenceGap,
]):
    """Assessment produced by the modularity coordinator."""


# Identifiers of the investigators registered with the reusability coordinator.
ReusabilityInvestigatorId = Literal["abstraction", "reuse_opportunity", "component_adaptability"]
# Result union discriminated by investigator to restore the concrete output type when reading JSON.
InvestigationResult = Annotated[
    AbstractionResult | ReuseOpportunityResult | ComponentAdaptabilityResult,
    Field(discriminator="investigator"),
]


# Reusability graph routes: yes requests follow-up; no leads to finalization.
# Stored in ContinuationDecision and consumed by the transition immediately after synthesis.
class ReusabilityRoute(StrEnum):
    YES = "yes"
    NO = "no"


# Reusability request: combines shared scope and destination context through neutral request bases.
# ReusabilityAgent.run() uses it to delegate abstraction, reuse-opportunity and adaptability analysis.
class ReusabilityRequest(ScopedAuditRequest, TargetContext):
    objective: str = "Assess reusability through abstractions, shared-implementation opportunities and context-specific adaptation constraints."


# Reusability capability: restricts the identifier to the dimension's three registered investigators.
# Included in capability registries within the plan and ReusabilityAssessment.
class ReusabilityInvestigatorCapability(AgentCapability[ReusabilityInvestigatorId]):
    model_config = ConfigDict(title="InvestigatorCapability")


# Reusability assignment: adds request/round correlation, priority and evidence expectations.
# Created by ReusabilityExecution during initial planning or targeted investigator follow-up.
class ReusabilityAssignment(DelegationAssignment[ReusabilityInvestigatorId]):
    model_config = ConfigDict(title="Assignment")

    request_id: str
    round_id: str
    priority: Literal["high", "medium", "low"] = "high"
    evidence_expectations: list[str] = Field(default_factory=list)


# Validated reusability invocation: discriminates among the three concrete investigator result types.
# Built during collection to retain specialized outputs in the coordinator's final assessment.
class ReusabilityInvocationRecord(AgentInvocation[ReusabilityAssignment, InvestigationResult]):
    model_config = ConfigDict(title="InvocationRecord")


# Raw reusability response: retains assignment, received value and failures before interpretation.
# Travels from delegation to collect_findings for validation against the investigator's result contract.
class ReusabilityRawInvocation(RawAgentInvocation[ReusabilityAssignment]):
    model_config = ConfigDict(title="RawInvocation")


# Reusability gap: retains missing evidence or contradictions linked to this dimension's investigators.
# Synthesis and continuation decisions use it to justify follow-up work or final limitations.
class ReusabilityEvidenceGap(CoordinatorEvidenceGap[ReusabilityInvestigatorId]):
    model_config = ConfigDict(title="EvidenceGap")


# Reusability gap proposal with contract-bounded investigator identifiers and references.
# Included by the model in ReusabilitySynthesisDraft; the host validates its incorporation into state.
class ReusabilityProposedGap(ProposedEvidenceGap[ReusabilityInvestigatorId]):
    model_config = ConfigDict(title="ProposedGap")


# Reusability contribution: accepts abstraction, reuse-opportunity or adaptability findings.
# Synthesis indexes retain the original interpretation together with its producing agent and invocation.
class ReusabilityFindingContribution(AgentFindingContribution[
    ReusabilityInvestigatorId, AbstractionFinding | ReuseFinding | AdaptabilityFinding,
]):
    model_config = ConfigDict(title="FindingContribution")


# Consolidated reusability concern: groups contributions while retaining evidence and disputes.
# Delivered to the manager as part of ReusabilityAssessment's auditable results.
class ReusabilityConsolidatedFinding(ConsolidatedKnowledge[ReusabilityFindingContribution]):
    model_config = ConfigDict(title="ConsolidatedFinding")


# Reusability conclusion: states a claim backed by references to findings and technical evidence.
# Proposed during synthesis; finalize_assessment retains supported references and records dispute status.
class Conclusion(Contract):
    statement: str = Field(min_length=1, max_length=2000)
    finding_refs: list[str] = Field(min_length=1, max_length=12)
    evidence_refs: list[str] = Field(min_length=1, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=12)
    status: Literal["supported", "disputed"] = "supported"


# Finding relationship: expresses support, trade-off, conflict or dependency with evidence and rationale.
# The reusability coordinator records it to explain interactions and contradictions in its output.
class FindingRelationship(Contract):
    kind: Literal["supports", "tradeoff", "conflicts", "depends_on"]
    finding_refs: list[str] = Field(min_length=2, max_length=8)
    rationale: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[str] = Field(min_length=1, max_length=12)
    resolution_status: Literal["observed", "unresolved", "resolved"] = "observed"


# Reusability draft: extends shared synthesis with conclusions and relationships between findings.
# Produced by the model in synthesize_findings, then host-validated and retained in round history.
class ReusabilitySynthesisDraft(CoordinatorSynthesis[ReusabilityProposedGap]):
    model_config = ConfigDict(title="SynthesisDraft")

    conclusions: list[Conclusion] = Field(default_factory=list, max_length=16)
    relationships: list[FindingRelationship] = Field(default_factory=list, max_length=24)


# Investigation-continuation decision: retains the route, rationale and pending gaps/requests.
# Calculated by ReusabilityExecution to route the graph and explain its final assessment.
class ContinuationDecision(Contract):
    route: ReusabilityRoute
    reason: str
    rationale: str = ""
    material_gap_ids: list[str]
    pending_request_ids: list[str]


# Round record: pairs the available synthesis draft with its corresponding continuation decision.
# Accumulated in synthesis_history to explain how reusability synthesis evolved across rounds.
class ReusabilitySynthesisRound(Contract):
    model_config = ConfigDict(title="SynthesisRound")

    round: int
    draft: ReusabilitySynthesisDraft | None
    decision: ContinuationDecision


# Final reusability assessment: binds the common envelope and adds coverage, conclusions and history.
# finalize_assessment returns it to the manager with subordinate results and their original limitations.
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
