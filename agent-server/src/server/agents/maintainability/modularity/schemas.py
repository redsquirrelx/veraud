"""Coordinator contracts: invocation identities never collapse into investigator IDs."""

from typing import Any, Literal

from pydantic import Field, SerializeAsAny

from ...modularity_runtime.schemas import (
    AuditRequest,
    AuditResult,
    Contract,
    EvidenceReference,
    Finding,
    InvestigationConfig,
)
from ...repository_runtime.schemas import ExecutionBudget

InvestigatorId = Literal["architecture_boundary", "responsibility", "dependency_impact"]
Route = Literal["reinvestigate", "finalize", "finalize_limited"]


class ModularityRequest(AuditRequest):
    objective: str = "Assess software modularity within the declared scope using the three specialized investigators."
    architectural_context: str = Field(default="", max_length=6000)
    targets: list[str] = Field(default_factory=list, max_length=12)


class ModularityConfig(InvestigationConfig):
    max_model_calls: int = Field(default=96, ge=4, le=100)
    max_total_tokens: int = Field(default=300_000, ge=1000)
    max_tool_calls: int = Field(default=96, ge=0, le=200)
    timeout_seconds: float = Field(default=600, gt=0, allow_inf_nan=False)
    tools: list[str] = Field(default_factory=list, max_length=0)
    max_rounds: int = Field(default=2, ge=1, le=6)
    max_invocations: int = Field(default=6, ge=3, le=18)
    max_parallel: int = Field(default=3, ge=1, le=3)
    investigation_start_interval_seconds: float = Field(default=0, ge=0, le=120, allow_inf_nan=False)
    invocation_limits: InvestigationConfig = Field(default_factory=lambda: InvestigationConfig(
        max_model_calls=12, max_total_tokens=60_000, max_tool_calls=16,
        timeout_seconds=180, max_context_characters=100_000,
    ))


class InvestigatorCapability(Contract):
    id: InvestigatorId
    agent_name: str
    capability: str


class Assignment(Contract):
    invocation_id: str
    investigator_id: InvestigatorId
    round: int
    question: str
    targets: list[str]
    evidence_refs: list[str] = Field(default_factory=list)
    gap_ids: list[str] = Field(default_factory=list)
    budget: ExecutionBudget | None = None


class Consumption(Contract):
    model_calls: int = 0
    tool_calls: int = 0
    accounted_tokens: int = 0
    estimated_tokens: int = 0
    model_calls_estimated: bool = False


class InvocationRecord(Contract):
    assignment: Assignment
    status: Literal["completed", "partial", "failed", "timeout", "skipped"]
    result: SerializeAsAny[AuditResult] | None = None
    evidence: list[EvidenceReference] = Field(default_factory=list)
    consumption: Consumption = Field(default_factory=Consumption)
    duration_seconds: float = 0
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)


class RawInvocation(Contract):
    assignment: Assignment
    status: Literal["received", "failed", "timeout", "skipped"]
    value: Any = None
    error: str | None = None
    duration_seconds: float = 0
    evidence: list[EvidenceReference] = Field(default_factory=list)


class EvidenceGap(Contract):
    id: str
    kind: Literal["missing_evidence", "contradiction", "essential_failure", "synthesis_failure"]
    investigator_id: InvestigatorId | None
    question: str
    targets: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    finding_refs: list[str] = Field(default_factory=list)
    material: bool = True


class ProposedGap(Contract):
    kind: Literal["missing_evidence", "contradiction"]
    investigator_id: InvestigatorId
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


class SynthesisDraft(Contract):
    summary: str = Field(max_length=3000)
    groups: list[FindingGroup] = Field(default_factory=list, max_length=24)
    gaps: list[ProposedGap] = Field(default_factory=list, max_length=12)
    resolutions: list[GapResolution] = Field(default_factory=list, max_length=12)


class FindingContribution(Contract):
    reference: str
    invocation_id: str
    investigator_id: InvestigatorId
    finding: SerializeAsAny[Finding]


class ConsolidatedFinding(Contract):
    id: str
    concern: str
    affected_components: list[str]
    status: Literal["supported", "disputed"]
    evidence: list[EvidenceReference]
    contributions: list[FindingContribution]
    severity: str | None = None
    confidence: float | None = None
    limitations: list[str] = Field(default_factory=list)


class ModularityAssessment(Contract):
    assessment_id: str
    repository_id: str
    commit: str | None
    snapshot_hash: str
    objective: str
    targets: list[str]
    status: Literal["completed", "partial", "failed"]
    termination_reason: str
    summary: str
    investigator_registry: list[InvestigatorCapability]
    initial_plan: list[Assignment]
    invocations: list[InvocationRecord]
    consolidated_findings: list[ConsolidatedFinding]
    material_gaps: list[EvidenceGap]
    resolved_gap_ids: list[str]
    withdrawn_finding_refs: list[str]
    limitations: list[str]
    rounds_completed: int
    consumption: Consumption
    duration_seconds: float
    node_transitions: list[str]
