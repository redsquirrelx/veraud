"""Reuse-opportunity specialization of the established investigator protocol."""

from enum import StrEnum
from typing import Literal

from pydantic import Field

from ...modularity_runtime.schemas import (
    AuditRequest,
    AuditResult,
    CandidateFinding,
    Contract,
    Criterion,
    Evaluation,
    EvidenceReference,
    Finding,
    InvestigationConfig,
)

Classification = Literal["recommended", "conditional", "not_recommended"]


class InspectRoute(StrEnum):
    USE_TOOLS = "use_tools"
    VALIDATE = "validate"


class ValidationRoute(StrEnum):
    INSPECT = "inspect"
    FINALIZE = "finalize"
    LIMITED_FINALIZE = "limited_finalize"


class ReuseOpportunityRequest(AuditRequest):
    objective: str = "Do conceptually similar functionalities exist that could share an implementation?"
    targets: list[str] = Field(default_factory=list, max_length=20)
    criteria: list[Criterion] = Field(default_factory=lambda: [Criterion(
        id="reuse-opportunity", origin="design_principle",
        description="Assess compatible responsibilities and sharing tradeoffs, not textual duplication alone.",
        provenance="Reusability investigation lens, not a mandatory refactor or normative quality threshold.",
    )], max_length=40)


class ReuseOpportunityConfig(InvestigationConfig):
    max_discovery_symbols: int = Field(default=160, ge=2, le=500)
    max_groups: int = Field(default=8, ge=1, le=20)
    max_feature_characters: int = Field(default=6000, ge=256, le=16000)
    max_source_lines: int = Field(default=80, ge=1, le=120)
    max_source_characters: int = Field(default=4000, ge=256, le=12000)


class CandidateLocation(Contract):
    component_id: str
    file_id: str
    path: str
    symbol: str
    start_line: int
    end_line: int
    language: str


class ReuseGroup(Contract):
    id: str
    members: list[CandidateLocation]
    discovery_signals: list[str]


class ImplementationComparison(Contract):
    component_id: str
    evidence_ids: list[str] = Field(max_length=24)
    purpose: str = Field(min_length=1, max_length=1500)
    inputs_outputs: str = Field(min_length=1, max_length=1500)
    preconditions_postconditions: str = Field(min_length=1, max_length=1500)
    failure_behavior: str = Field(min_length=1, max_length=1500)
    side_effects: str = Field(min_length=1, max_length=1500)
    dependencies: str = Field(min_length=1, max_length=1500)
    invariants: str = Field(min_length=1, max_length=1500)


class CallerInspection(Contract):
    implementation_id: str
    caller_id: str
    relationship_id: str
    evidence_ids: list[str] = Field(max_length=16)
    constraints: str = Field(min_length=1, max_length=1500)


class ReuseAssessment(Contract):
    group_id: str
    hypothesis_id: str
    classification: Classification
    implementations: list[ImplementationComparison] = Field(min_length=2, max_length=2)
    callers: list[CallerInspection] = Field(default_factory=list, max_length=12)
    shared_responsibility: str = Field(min_length=1, max_length=2000)
    meaningful_differences: str = Field(min_length=1, max_length=2000)
    variation_points: str = Field(min_length=1, max_length=2000)
    proposed_boundary: str = Field(min_length=1, max_length=2000)
    expected_benefit: str = Field(min_length=1, max_length=2000)
    risks_tradeoffs: str = Field(min_length=1, max_length=2000)
    migration_complexity: str = Field(min_length=1, max_length=1500)
    counterevidence_analysis: str = Field(min_length=1, max_length=2000)
    rationale: str = Field(min_length=1, max_length=2500)
    unknowns: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class ReuseCandidate(CandidateFinding):
    group_id: str
    classification: Classification


class ReuseEvaluation(Evaluation):
    candidates: list[ReuseCandidate]
    group_assessments: list[ReuseAssessment] = Field(max_length=20)


class ExaminedGroup(ReuseAssessment):
    members: list[CandidateLocation]
    evidence: list[EvidenceReference]
    validation_issues: list[str]
    validation_status: Literal["source_backed", "insufficient_evidence"]


class ReuseFinding(Finding):
    group_id: str
    classification: Classification
    stable_id: str = ""
    duplicate_of: str | None = None


class DiscoveryCoverage(Contract):
    indexed_eligible_symbols: int
    shortlisted_symbols: int
    compared_pairs: int
    matching_pairs: int
    omitted_groups: int
    omitted_symbols: int
    selected_groups: list[ReuseGroup]
    inspected_paths: list[str] = Field(default_factory=list)
    unassessed_groups: list[str] = Field(default_factory=list)
    exhaustive: bool = False


class ReuseOpportunityResult(AuditResult):
    investigator: Literal["ReuseOpportunityAgent"] = "ReuseOpportunityAgent"
    quality_attribute: Literal["reusability"] = "reusability"
    status: Literal["completed", "partial", "failed"] = "partial"
    findings: list[ReuseFinding]
    examined_groups: list[ExaminedGroup] = Field(default_factory=list)
    coverage: DiscoveryCoverage | None = None
    tool_failures: list[str] = Field(default_factory=list)
    execution_trace: list[str] = Field(default_factory=list)
