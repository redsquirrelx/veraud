"""Canonical reusability coordinator contracts."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field

from config.agents import CoordinatorConfig as ReusabilityConfig
from server.agents.maintainability.reusability.abstraction.schemas import (
    AbstractionFinding,
    AbstractionResult,
)
from server.agents.maintainability.reusability.component_adaptability.schemas import (
    AdaptabilityFinding,
    ComponentAdaptabilityResult,
)
from server.agents.maintainability.reusability.reuse_opportunity.schemas import (
    ReuseFinding,
    ReuseOpportunityResult,
)
from server.contracts.audit import Contract, ScopedAuditRequest, TargetContext
from server.runtimes.coordination.contracts import (
    AgentCapability,
    AgentFindingContribution,
    AgentInvocation,
    ConsolidatedKnowledge,
    CoordinatorEvidenceGap,
    CoordinatorResult,
    CoordinatorSynthesis,
    DelegationAssignment,
    ProposedEvidenceGap,
    RawAgentInvocation,
)

ReusabilityInvestigatorId = Literal["abstraction", "reuse_opportunity", "component_adaptability"]


class ReusabilityRoute(StrEnum):
    YES = "yes"
    NO = "no"

InvestigationResult = Annotated[
    AbstractionResult | ReuseOpportunityResult | ComponentAdaptabilityResult,
    Field(discriminator="investigator"),
]

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

__all__ = ['Assignment', 'Conclusion', 'ConsolidatedFinding', 'ContinuationDecision', 'Contract', 'EvidenceGap', 'FindingContribution', 'FindingRelationship', 'InvestigationResult', 'InvestigatorCapability', 'InvestigatorId', 'InvocationRecord', 'ProposedGap', 'RawInvocation', 'ReusabilityAssessment', 'ReusabilityConfig', 'ReusabilityRequest', 'Route', 'SynthesisDraft', 'SynthesisRound']

Assignment = ReusabilityAssignment
InvestigatorCapability = ReusabilityInvestigatorCapability
ConsolidatedFinding = ReusabilityConsolidatedFinding
EvidenceGap = ReusabilityEvidenceGap
FindingContribution = ReusabilityFindingContribution
InvestigatorId = ReusabilityInvestigatorId
InvocationRecord = ReusabilityInvocationRecord
ProposedGap = ReusabilityProposedGap
RawInvocation = ReusabilityRawInvocation
Route = ReusabilityRoute
SynthesisDraft = ReusabilitySynthesisDraft
SynthesisRound = ReusabilitySynthesisRound
