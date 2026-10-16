"""Reusability specializations of the established coordinator/report contracts."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, field_validator

from config.agents import CoordinatorConfig as ReusabilityConfig  # noqa: F401 - compatibility export

from .....runtimes.investigation.schemas import Contract
from ...modularity.coordinator import schemas as shared
from ..abstraction.schemas import AbstractionFinding, AbstractionResult
from ..component_adaptability.schemas import (
    AdaptabilityFinding,
    ComponentAdaptabilityResult,
)
from ..reuse_opportunity.schemas import ReuseFinding, ReuseOpportunityResult

InvestigatorId = Literal["abstraction", "reuse_opportunity", "component_adaptability"]
InvestigationResult = Annotated[
    AbstractionResult | ReuseOpportunityResult | ComponentAdaptabilityResult,
    Field(discriminator="investigator"),
]


class Route(StrEnum):
    YES = "yes"
    NO = "no"


class ReusabilityRequest(shared.ModularityRequest):
    objective: str = "Assess reusability through abstractions, shared-implementation opportunities and context-specific adaptation constraints."
    target_context: str | None = Field(default=None, min_length=1, max_length=6000)

    @field_validator("target_context")
    @classmethod
    def meaningful_context(cls, value):
        if value is not None and not value.strip():
            raise ValueError("target_context must be meaningful or null")
        return value


class InvestigatorCapability(shared.InvestigatorCapability):
    id: InvestigatorId


class Assignment(shared.Assignment):
    investigator_id: InvestigatorId
    request_id: str
    round_id: str
    priority: Literal["high", "medium", "low"] = "high"
    evidence_expectations: list[str] = Field(default_factory=list)


class InvocationRecord(shared.InvocationRecord):
    assignment: Assignment
    result: InvestigationResult | None = None


class RawInvocation(shared.RawInvocation):
    assignment: Assignment


class EvidenceGap(shared.EvidenceGap):
    investigator_id: InvestigatorId | None


class ProposedGap(shared.ProposedGap):
    investigator_id: InvestigatorId


class FindingContribution(shared.FindingContribution):
    investigator_id: InvestigatorId
    finding: AbstractionFinding | ReuseFinding | AdaptabilityFinding


class ConsolidatedFinding(shared.ConsolidatedFinding):
    contributions: list[FindingContribution]


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


class SynthesisDraft(shared.SynthesisDraft):
    gaps: list[ProposedGap] = Field(default_factory=list, max_length=12)
    conclusions: list[Conclusion] = Field(default_factory=list, max_length=16)
    relationships: list[FindingRelationship] = Field(default_factory=list, max_length=24)


class ContinuationDecision(Contract):
    route: Route
    reason: str
    rationale: str = ""
    material_gap_ids: list[str]
    pending_request_ids: list[str]


class SynthesisRound(Contract):
    round: int
    draft: SynthesisDraft | None
    decision: ContinuationDecision


class ReusabilityAssessment(shared.ModularityAssessment):
    investigator: Literal["ReusabilityAgent"] = "ReusabilityAgent"
    quality_attribute: Literal["reusability"] = "reusability"
    target_context: str | None = None
    investigator_registry: list[InvestigatorCapability]
    initial_plan: list[Assignment]
    invocations: list[InvocationRecord]
    consolidated_findings: list[ConsolidatedFinding]
    material_gaps: list[EvidenceGap]
    conclusions: list[Conclusion] = Field(default_factory=list)
    finding_relationships: list[FindingRelationship] = Field(default_factory=list)
    synthesis_history: list[SynthesisRound] = Field(default_factory=list)
    continuation_decision: ContinuationDecision
    coverage: dict[str, list[dict]] = Field(default_factory=dict)
