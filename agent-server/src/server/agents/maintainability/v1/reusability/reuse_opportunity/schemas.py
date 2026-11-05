"""Canonical contracts for this maintainability participant."""

from enum import StrEnum
from typing import Literal

from pydantic import Field

from server.contracts.audit import (
    AuditRequest,
    AuditResult,
    CandidateFinding,
    Contract,
    Criterion,
    Evaluation,
    EvidenceReference,
    Finding,
    Hypothesis,
    InvestigationPlan,
    Review,
)

Classification = Literal["recommended", "conditional", "not_recommended"]

class ReuseInspectRoute(StrEnum):
    USE_TOOLS = "use_tools"
    VALIDATE = "validate"

class ReuseValidationRoute(StrEnum):
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

class ReuseHypothesis(Hypothesis):
    group_ids: list[str] = Field(default_factory=list, max_length=20,
        description="Exact selected group IDs committed to this question; discovery alone is not a commitment.")

class ReusePlan(InvestigationPlan):
    hypotheses: list[ReuseHypothesis]

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
    behavior_basis: Literal["implementation", "contract_only"] = "implementation"

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
    conditions: list[str] = Field(default_factory=list, max_length=16,
        description="Concrete prerequisites for the proposed boundary; conditional does not authorize immediate extraction.")
    limitations: list[str] = Field(default_factory=list, max_length=16)

class ReuseCandidate(CandidateFinding):
    group_id: str
    classification: Classification

class ReuseEvaluation(Evaluation):
    candidates: list[ReuseCandidate]
    group_assessments: list[ReuseAssessment] = Field(max_length=20)

class ExaminedGroup(ReuseAssessment):
    qualification_notes: list[str] = Field(default_factory=list)
    proposed_evidence_ids: dict[str, list[str]] = Field(default_factory=dict)
    members: list[CandidateLocation]
    evidence: list[EvidenceReference]
    validation_issues: list[str]
    validation_status: Literal["source_backed", "insufficient_evidence"]

class ReuseFinding(Finding):
    group_id: str
    classification: Classification
    stable_id: str = ""
    duplicate_of: str | None = None
    conditions: list[str] = Field(default_factory=list)
    sharing_boundary: str = ""
    unknowns: list[str] = Field(default_factory=list)

class DiscoveryCoverage(Contract):
    indexed_languages: list[str] = Field(default_factory=list)
    indexed_eligible_symbols: int
    shortlisted_symbols: int
    compared_pairs: int
    matching_pairs: int
    omitted_groups: int
    omitted_symbols: int
    selected_groups: list[ReuseGroup]
    inspected_paths: list[str] = Field(default_factory=list)
    unassessed_groups: list[str] = Field(default_factory=list)
    planned_groups: list[str] = Field(default_factory=list)
    unplanned_groups: list[str] = Field(default_factory=list)
    exhaustive: bool = False

class ReuseHypothesisReview(Contract):
    hypothesis_id: str
    assessment_group_ids: list[str] = Field(default_factory=list)
    checked_evidence_ids: list[str] = Field(default_factory=list)
    scope_supported: bool = False
    resolution: Literal["confirmed", "discarded", "inconclusive"] = "inconclusive"
    sharing_supported: bool | None = Field(default=None,
        description="Answer feasibility of sharing the original scoped responsibility, not mere syntactic similarity.")
    supporting_group_ids: list[str] = Field(default_factory=list)
    supported_boundary: str = Field(default="", max_length=2000,
        description="Concrete assessed sharing boundary supporting confirmation; empty for discarded/inconclusive.")
    rationale: str = Field(min_length=1)
    unverified_claims: list[str] = Field(default_factory=list)

class ReuseReview(Review):
    hypotheses: list[ReuseHypothesisReview] = Field(default_factory=list)

class ReuseToolFailure(Contract):
    tool: str
    call_id: str
    provider_call_id: str | None = None
    stage: Literal["repository", "tool_node"]
    code: str
    message: str
    path: str | None = None
    start_line: int | None = None
    end_line: int | None = None

class ReuseOpportunityResult(AuditResult):
    plan: ReusePlan | None
    investigator: Literal["ReuseOpportunityAgent"] = "ReuseOpportunityAgent"
    quality_attribute: Literal["reusability"] = "reusability"
    status: Literal["completed", "partial", "failed"] = "partial"
    findings: list[ReuseFinding]
    examined_groups: list[ExaminedGroup] = Field(default_factory=list)
    coverage: DiscoveryCoverage | None = None
    tool_failures: list[str] = Field(default_factory=list)
    tool_failure_details: list[ReuseToolFailure] = Field(default_factory=list)
    critical_review: ReuseReview | None = None
    hypothesis_validation_issues: dict[str, list[str]] = Field(default_factory=dict)
    execution_trace: list[str] = Field(default_factory=list)

from .config import ReuseOpportunityConfig

__all__ = ['AuditRequest', 'AuditResult', 'CallerInspection', 'CandidateFinding', 'CandidateLocation', 'Classification', 'Contract', 'Criterion', 'DiscoveryCoverage', 'Evaluation', 'EvidenceReference', 'ExaminedGroup', 'Finding', 'ImplementationComparison', 'InspectRoute', 'ReuseAssessment', 'ReuseCandidate', 'ReuseEvaluation', 'ReuseFinding', 'ReuseGroup', 'ReuseOpportunityConfig', 'ReuseOpportunityRequest', 'ReuseOpportunityResult', 'ReusePlan', 'ReuseReview', 'ReuseToolFailure', 'ValidationRoute']

InspectRoute = ReuseInspectRoute
ValidationRoute = ReuseValidationRoute
