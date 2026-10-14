"""Same append-at-collection state discipline as the existing coordinator."""

from ..modularity.state import ModularityState
from .schemas import (
    Assignment,
    ConsolidatedFinding,
    ContinuationDecision,
    EvidenceGap,
    InvestigatorCapability,
    InvocationRecord,
    RawInvocation,
    ReusabilityAssessment,
    SynthesisRound,
)


class ReusabilityState(ModularityState):
    investigator_registry: list[InvestigatorCapability]
    pending_assignments: list[Assignment]
    investigation_results: list[InvocationRecord]
    execution_records: list[RawInvocation]
    initial_plan: list[Assignment]
    consolidated_findings: list[ConsolidatedFinding]
    material_gaps: list[EvidenceGap]
    actionable_followups: list[EvidenceGap]
    continuation_decision: ContinuationDecision
    synthesis_history: list[SynthesisRound]
    result: ReusabilityAssessment
