"""Investigator request, analysis and output contracts, including maintainability specializations."""

from enum import StrEnum
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from .base import (
    AuditRequest,
    AuditResult,
    CandidateFinding,
    Contract,
    Criterion,
    Evaluation,
    EvidenceReference,
    Finding,
    Hypothesis,
    TargetContext,
)

InvestigatorResult = AuditResult


def responsibility_criteria():
    return [Criterion(
        id=identifier, description=description, origin="design_principle",
        provenance="Investigation lens, not a normative ISO rule, size threshold or documented project constraint.",
    ) for identifier, description in (
        ("responsibility-cohesion", "Behaviors should contribute to a coherent component purpose."),
        ("responsibility-separation", "Investigate conceptually independent behaviors and reasons for change."),
        ("responsibility-placement", "Compare behavior placement with the supplied architecture and contracts."),
        ("responsibility-accumulation", "Investigate heterogeneous functionality and whether its grouping is justified."),
    )]


class ResponsibilityRequest(AuditRequest):
    objective: str = "Do components group coherent responsibilities or mix incompatible functionality?"
    criteria: list[Criterion] = Field(default_factory=responsibility_criteria, max_length=40)


class Responsibility(Contract):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    behaviors: list[str] = Field(default_factory=list)
    possible_change_reasons: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)


class ResponsibilityConflict(Contract):
    responsibility_ids: list[str] = Field(min_length=2)
    independent_change_rationale: str = Field(min_length=1)
    maintenance_risk: str = Field(min_length=1)


class ComponentAssessment(Contract):
    id: str = Field(min_length=1)
    component_id: str = Field(min_length=1, description="An actual file or symbol ID returned by repository tools.")
    responsibilities: list[Responsibility]
    potentially_incompatible: list[ResponsibilityConflict]
    cohesion: Literal["coherent", "mixed", "inconclusive"]
    architectural_justification: str
    evidence_ids: list[str] = Field(default_factory=list)


class ResponsibilityCandidate(CandidateFinding):
    assessment_ids: list[str] = Field(min_length=1)
    basis: Literal["behavioral", "metrics_only", "names_only"]


class ResponsibilityEvaluation(Evaluation):
    candidates: list[ResponsibilityCandidate]
    component_assessments: list[ComponentAssessment]


class ResponsibilityFinding(Finding):
    assessment_ids: list[str]
    basis: Literal["behavioral", "metrics_only", "names_only"]


class InvestigatedComponent(ComponentAssessment):
    path: str
    file_id: str
    symbol_name: str | None = None
    evidence: list[EvidenceReference]
    validation_status: Literal["source_backed", "insufficient_evidence"]
    validation_issues: list[str]


class ResponsibilityResult(AuditResult):
    findings: list[ResponsibilityFinding]
    components_investigated: list[InvestigatedComponent] = Field(default_factory=list)
    discarded_hypotheses: list[Hypothesis] = Field(default_factory=list)
    inconclusive_investigations: list[str] = Field(default_factory=list)


class ArchitectureBoundaryRequest(AuditRequest):
    model_config = ConfigDict(title="AuditRequest")

    objective: str = "Audit architectural boundaries and their impact on modularity."
    criteria: list[Criterion] = Field(default_factory=lambda: [Criterion(
        id="responsibility-boundaries", origin="design_principle",
        description="Keep responsibilities separated and dependencies aligned with declared component contracts.",
        provenance="Auditor design heuristic, not a normative ISO rule or a documented project constraint.",
    )], max_length=40)


ImpactKind = Literal["demonstrated", "plausible_risk", "none", "inconclusive"]
FindingBasis = Literal[
    "consequence_evidence", "metrics_only", "cycle_only", "transitivity_only",
    "interface_shape_only", "dependency_existence_only",
]


def dependency_impact_criteria():
    return [Criterion(
        id=identifier, description=description, origin="design_principle",
        provenance="Investigation lens, not a normative ISO rule, coupling threshold or documented project constraint.",
    ) for identifier, description in (
        ("concrete-coupling", "Investigate unnecessary dependence on implementation details and replacement costs."),
        ("change-propagation", "Explain concretely how a change can affect consumers across dependency boundaries."),
        ("dependency-cycles", "Assess whether cycles actually restrict independent maintenance."),
        ("shared-dependencies", "Investigate maintenance consequences for consumers of shared components."),
        ("contract-stability", "Inspect actual contracts and usage; interfaces alone prove neither stability nor low coupling."),
        ("component-independence", "Assess maintenance independence and justified co-evolution."),
    )]


class DependencyImpactRequest(AuditRequest):
    objective: str = "Do identified dependencies create coupling harmful to independent maintenance?"
    criteria: list[Criterion] = Field(default_factory=dependency_impact_criteria, max_length=40)


class DependencyLink(Contract):
    id: str = Field(min_length=1)
    source_id: str = Field(min_length=1, description="Actual source file/symbol ID, not its name.")
    target_id: str = Field(min_length=1, description="Actual target file/symbol ID, not its name.")
    relationship_id: str | None = Field(default=None, description="Actual snapshot relationship ID; null if unresolved.")
    dependency_type: str = Field(min_length=1, description="Exact kind of the cited graph relationship, not an inferred runtime call.")
    evidence_ids: list[str] = Field(default_factory=list)


class DependencyAssessment(Contract):
    id: str = Field(min_length=1)
    hypothesis_id: str = Field(min_length=1)
    dependencies: list[DependencyLink] = Field(min_length=1, max_length=32)
    dependency_path: list[str] = Field(default_factory=list, description="Optional ordered component IDs; each hop must occur in dependencies.")
    contract_analysis: str
    architectural_justification: str
    impact_kind: ImpactKind
    consequence: str
    change_scenario: str
    propagation_explanation: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    demonstration_evidence_ids: list[str] = Field(default_factory=list)
    demonstration_rationale: str = ""
    uncertainty: Literal["low", "medium", "high"]
    limitations: list[str] = Field(default_factory=list)


class DependencyImpactCandidate(CandidateFinding):
    assessment_ids: list[str] = Field(min_length=1)
    basis: FindingBasis


class DependencyImpactEvaluation(Evaluation):
    candidates: list[DependencyImpactCandidate]
    dependency_assessments: list[DependencyAssessment]


class DependencyImpactFinding(Finding):
    assessment_ids: list[str]
    basis: FindingBasis


class DependencyComponentReference(Contract):
    model_config = ConfigDict(title="ComponentReference")

    id: str
    file_id: str
    path: str
    symbol_name: str | None = None


class InvestigatedDependency(DependencyLink):
    source: DependencyComponentReference
    target: DependencyComponentReference
    evidence: list[EvidenceReference]
    validation_status: Literal["source_backed", "insufficient_evidence"]
    validation_issues: list[str]


class InvestigatedImpact(DependencyAssessment):
    dependencies: list[InvestigatedDependency] = Field(default_factory=list)
    evidence: list[EvidenceReference]
    is_cycle: bool
    validation_status: Literal["source_backed", "insufficient_evidence"]
    validation_issues: list[str]


class DependencyImpactResult(AuditResult):
    findings: list[DependencyImpactFinding]
    components_investigated: list[DependencyComponentReference] = Field(default_factory=list)
    dependency_assessments: list[InvestigatedImpact] = Field(default_factory=list)
    discarded_hypotheses: list[Hypothesis] = Field(default_factory=list)
    inconclusive_investigations: list[str] = Field(default_factory=list)


Category = Literal["useful_abstraction", "unnecessary_abstraction", "coupling", "missed_reuse"]
Basis = Literal["usage_evidence", "structure_only", "metrics_only", "names_only"]


class AbstractionRequest(AuditRequest):
    objective: str = "Do abstractions facilitate reuse, or introduce unnecessary complexity and coupling?"
    targets: list[str] = Field(default_factory=list, max_length=20)
    criteria: list[Criterion] = Field(default_factory=lambda: [Criterion(
        id="abstraction-reuse", origin="design_principle",
        description="Assess concrete reuse benefits, variation, coupling and indirection costs, not abstraction counts.",
        provenance="Reusability investigation lens, not an ISO compliance rule or a numerical design threshold.",
    )], max_length=40)


class AbstractionCandidateTarget(Contract):
    component_id: str
    path: str
    symbol_name: str | None
    kind: str
    start_line: int | None
    end_line: int | None
    relationship_ids: list[str]


class Participant(Contract):
    component_id: str
    role: Literal["consumer", "implementation", "delegate", "contract", "duplicate", "composition", "test"]
    relationship_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list, max_length=16)
    usage_explanation: str = Field(min_length=1, max_length=2000)


class AbstractionAssessment(Contract):
    id: str
    hypothesis_id: str
    declaration_id: str
    conclusion: Literal["useful_abstraction", "unnecessary_abstraction", "coupling", "missed_reuse", "justified_boundary", "inconclusive"]
    participants: list[Participant] = Field(default_factory=list, max_length=24)
    observed_facts: list[str] = Field(min_length=1, max_length=16)
    supporting_evidence_ids: list[str] = Field(default_factory=list, max_length=32)
    counterevidence_ids: list[str] = Field(default_factory=list, max_length=16)
    variation_points: str = Field(default="", max_length=2000)
    reuse_benefit: str = Field(default="", max_length=2000)
    indirection_cost: str = Field(default="", max_length=2000)
    coupling_consequence: str = Field(default="", max_length=2000)
    duplication_comparison: str = Field(default="", max_length=2000)
    boundary_justification: str = Field(default="", max_length=2000)
    counterevidence_analysis: str = Field(min_length=1, max_length=3000)
    proportional_alternative: str = Field(default="", max_length=2000)
    uncertainty: Literal["low", "medium", "high"]
    limitations: list[str] = Field(default_factory=list, max_length=16)


class AbstractionCandidate(CandidateFinding):
    category: Category
    assessment_ids: list[str] = Field(min_length=1, max_length=12)
    basis: Basis


class AbstractionEvaluation(Evaluation):
    candidates: list[AbstractionCandidate]
    abstraction_assessments: list[AbstractionAssessment] = Field(max_length=40)


class AbstractionComponentReference(Contract):
    model_config = ConfigDict(title="ComponentReference")

    id: str
    file_id: str
    path: str
    symbol_name: str | None


class InspectedParticipant(Participant):
    component: AbstractionComponentReference
    evidence: list[EvidenceReference]
    validation_issues: list[str]


class InvestigatedAbstraction(AbstractionAssessment):
    declaration: AbstractionComponentReference | None
    participants: list[InspectedParticipant]
    evidence: list[EvidenceReference]
    validation_status: Literal["source_backed", "insufficient_evidence"]
    validation_issues: list[str]


class AbstractionFinding(Finding):
    category: Category
    assessment_ids: list[str]
    basis: Basis
    duplicate_of: str | None = None


class AbstractionCoverage(Contract):
    targets: list[str] = Field(default_factory=list)
    selected_candidates: list[AbstractionCandidateTarget] = Field(default_factory=list)
    candidate_count: int = 0
    omitted_candidates: int = 0
    inspected_paths: list[str] = Field(default_factory=list)
    assessed_declarations: list[str] = Field(default_factory=list)
    unassessed_candidates: list[str] = Field(default_factory=list)
    exhaustive: bool = False


class AbstractionResult(AuditResult):
    findings: list[AbstractionFinding]
    investigator: Literal["AbstractionAgent"] = "AbstractionAgent"
    quality_attribute: Literal["reusability"] = "reusability"
    status: Literal["completed", "partial", "failed"] = "partial"
    abstractions_investigated: list[InvestigatedAbstraction] = Field(default_factory=list)
    coverage: AbstractionCoverage = Field(default_factory=AbstractionCoverage)
    inconclusive_investigations: list[str] = Field(default_factory=list)
    tool_failures: list[str] = Field(default_factory=list)


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


ConstraintType = Literal[
    "infrastructure", "environment", "global_state", "framework", "configuration",
    "side_effects", "interface", "dependency_injection", "platform", "data_schema",
]
Conclusion = Literal["verified_obstacle", "context_dependent_risk", "mitigated", "unknown"]
ToolName = Literal[
    "list_files", "find_symbols", "list_relationships", "get_source_excerpt",
    "search_repository_text", "get_evidence", "get_infrastructure",
]


class AdaptabilityInspectRoute(StrEnum):
    USE_TOOLS = "use_tools"
    VALIDATE = "validate"


class AdaptabilityValidationRoute(StrEnum):
    INSPECT = "inspect"
    FINALIZE = "finalize"
    LIMITED_FINALIZE = "limited_finalize"


class InspectionToolRequest(Contract):
    name: ToolName
    arguments_json: str = Field(min_length=2, max_length=4000)


class InspectionDecision(Contract):
    action: AdaptabilityInspectRoute
    tool_requests: list[InspectionToolRequest] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def consistent_action(self):
        if (self.action == AdaptabilityInspectRoute.USE_TOOLS) != bool(self.tool_requests):
            raise ValueError("use_tools requires requests; validate forbids requests")
        return self


class ComponentAdaptabilityRequest(AuditRequest, TargetContext):
    objective: str = "Which constraints make a component difficult to reuse in another context?"
    targets: list[str] = Field(default_factory=list, max_length=20)
    component_ids: list[str] = Field(default_factory=list, max_length=20)
    criteria: list[Criterion] = Field(default_factory=lambda: [Criterion(
        id="component-adaptability", origin="design_principle",
        description="Investigate concrete context-specific adaptation obstacles and existing mitigating seams.",
        provenance="Reusability investigation lens; dependencies are not automatically defects or normative violations.",
    )], max_length=40)


class DiscoverySignal(Contract):
    constraint_type: ConstraintType
    line: int
    rule: str


class ComponentTarget(Contract):
    component_id: str
    file_id: str
    path: str
    symbol: str | None
    start_line: int
    end_line: int
    signals: list[DiscoverySignal]


class UsageInspection(Contract):
    caller_id: str
    relationship_id: str
    evidence_ids: list[str] = Field(max_length=16)
    instantiation_configuration: str = Field(min_length=1, max_length=2000)


class ConstraintAssessment(Contract):
    id: str
    component_id: str
    hypothesis_id: str
    constraint_type: ConstraintType
    constraint_key: str = Field(min_length=1, max_length=160)
    conclusion: Conclusion
    assessed_context: str = Field(min_length=1, max_length=6000)
    context_basis: Literal["explicit", "plausible"]
    observed_facts: list[str] = Field(min_length=1, max_length=12)
    adaptation_impact: str = Field(min_length=1, max_length=2500)
    adaptation_effort: str = Field(min_length=1, max_length=2000)
    assumptions: list[str] = Field(default_factory=list, max_length=16)
    supporting_evidence_ids: list[str] = Field(default_factory=list, max_length=32)
    counterevidence_ids: list[str] = Field(default_factory=list, max_length=24)
    usage: list[UsageInspection] = Field(default_factory=list, max_length=8)
    seam_analysis: str = Field(min_length=1, max_length=2500)
    seam_evidence_ids: list[str] = Field(default_factory=list, max_length=24)
    counterevidence_analysis: str = Field(min_length=1, max_length=2500)
    unknowns: list[str] = Field(default_factory=list, max_length=16)
    mitigation_options: list[str] = Field(default_factory=list, max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=16)


class AdaptabilityCandidate(CandidateFinding):
    assessment_ids: list[str] = Field(min_length=1, max_length=16)
    constraint_type: ConstraintType
    classification: Literal["verified_obstacle", "context_dependent_risk"]


class AdaptabilityEvaluation(Evaluation):
    candidates: list[AdaptabilityCandidate]
    constraint_assessments: list[ConstraintAssessment] = Field(max_length=40)
    cleared_components: list[str] = Field(default_factory=list, max_length=20)
    coverage_rationale: str = Field(min_length=1, max_length=3000)
    can_investigate_further: bool = True
    continuation_reason: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def explain_blocker(self):
        if not self.can_investigate_further and not self.continuation_reason.strip():
            raise ValueError("An unverifiable investigation needs a concrete blocker")
        return self


class ExaminedConstraint(ConstraintAssessment):
    component: ComponentTarget | None
    evidence: list[EvidenceReference]
    validation_issues: list[str]
    validation_status: Literal["source_backed", "insufficient_evidence"]


class AdaptabilityFinding(Finding):
    assessment_ids: list[str]
    constraint_type: ConstraintType
    classification: Literal["verified_obstacle", "context_dependent_risk"]
    stable_id: str = ""
    duplicate_of: str | None = None
    assessed_context: str = ""
    adaptation_impact: str = ""
    adaptation_effort: str = ""
    assumptions: list[str] = Field(default_factory=list)
    mitigation_options: list[str] = Field(default_factory=list)


class AdaptabilityCoverage(Contract):
    selected_components: list[ComponentTarget]
    eligible_components: int
    omitted_components: int
    scanned_files: int
    omitted_scan_files: int
    scan_truncated_paths: list[str]
    inspected_paths: list[str] = Field(default_factory=list)
    unassessed_components: list[str] = Field(default_factory=list)
    exhaustive: bool = False


class ToolActivity(Contract):
    call_id: str
    tool: str
    status: str
    seconds: float
    cache_hit: bool


class ComponentAdaptabilityResult(AuditResult):
    investigator: Literal["ComponentAdaptabilityAgent"] = "ComponentAdaptabilityAgent"
    quality_attribute: Literal["reusability"] = "reusability"
    status: Literal["completed", "partial", "failed"] = "partial"
    target_context: str | None = None
    findings: list[AdaptabilityFinding]
    examined_constraints: list[ExaminedConstraint] = Field(default_factory=list)
    coverage: AdaptabilityCoverage | None = None
    summary: str = ""
    tool_failures: list[str] = Field(default_factory=list)
    execution_trace: list[str] = Field(default_factory=list)
    node_durations_seconds: dict[str, float] = Field(default_factory=dict)
    tool_activity: list[ToolActivity] = Field(default_factory=list)
