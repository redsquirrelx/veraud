"""Canonical modularity coordinator contracts."""

from typing import Literal

from pydantic import SerializeAsAny

from config.agents import CoordinatorConfig as ModularityConfig
from config.agents.repository_execution import ExecutionBudget
from server.contracts.audit import (
    AuditRequest,
    AuditResult,
    Consumption,
    Contract,
    EvidenceReference,
    Finding,
    ScopedAuditRequest,
)
from server.runtimes.coordination.contracts import (
    AgentCapability,
    AgentFindingContribution,
    AgentInvocation,
    ConsolidatedKnowledge,
    CoordinatorEvidenceGap,
    CoordinatorResult,
    CoordinatorSynthesis,
    DelegationAssignment,
    FindingGroup,
    GapResolution,
    ProposedEvidenceGap,
    RawAgentInvocation,
)

InvestigatorId = Literal["architecture_boundary", "responsibility", "dependency_impact"]

Route = Literal["reinvestigate", "finalize", "finalize_limited"]

class ModularityRequest(ScopedAuditRequest):
    investigator_ids: list[InvestigatorId] | None = None
    objective: str = "Assess software modularity within the declared scope using the three specialized investigators."

class InvestigatorCapability(AgentCapability[InvestigatorId]):
    """Capabilities of the modularity investigators."""

class Assignment(DelegationAssignment[InvestigatorId]):
    """Assignment to a modularity investigator."""

class InvocationRecord(AgentInvocation[Assignment, SerializeAsAny[AuditResult]]):
    """Collected modularity investigator result."""

class RawInvocation(RawAgentInvocation[Assignment]):
    """Unvalidated modularity investigator response."""

class EvidenceGap(CoordinatorEvidenceGap[InvestigatorId]):
    """Evidence gap within modularity coordination."""

class ProposedGap(ProposedEvidenceGap[InvestigatorId]):
    """Proposed modularity investigation gap."""

class SynthesisDraft(CoordinatorSynthesis[ProposedGap]):
    """Modularity synthesis draft."""

class FindingContribution(AgentFindingContribution[InvestigatorId, SerializeAsAny[Finding]]):
    """Modularity investigator contribution."""

class ConsolidatedFinding(ConsolidatedKnowledge[FindingContribution]):
    """Consolidated modularity finding."""

class ModularityAssessment(CoordinatorResult[
    InvestigatorCapability, Assignment, InvocationRecord, ConsolidatedFinding, EvidenceGap,
]):
    """Assessment produced by the modularity coordinator."""

__all__ = ['Assignment', 'AuditRequest', 'AuditResult', 'ConsolidatedFinding', 'Consumption', 'Contract', 'EvidenceGap', 'EvidenceReference', 'ExecutionBudget', 'Finding', 'FindingContribution', 'FindingGroup', 'GapResolution', 'InvestigatorCapability', 'InvestigatorId', 'InvocationRecord', 'ModularityAssessment', 'ModularityConfig', 'ModularityRequest', 'ProposedGap', 'RawInvocation', 'Route', 'SynthesisDraft']
