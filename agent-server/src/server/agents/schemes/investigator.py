"""Investigator request, analysis and output contracts, including maintainability specializations."""

from enum import StrEnum
from typing import ClassVar, Literal

from pydantic import ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

from .base import (
    AuditRequest,
    AuditResult,
    CandidateFinding,
    Contract,
    Criterion,
    Evaluation,
    EvidenceReference,
    Finding,
    FindingReview,
    Hypothesis,
    InvestigationPlan,
    Review,
    TargetContext,
)

# Public names for the shared investigator envelope; each denotes the same class.
InvestigatorResult = AuditResult


class BoundarySupport(Contract):
    evidence_id: str
    role: Literal["declaration", "implementation", "usage", "composition", "dependency"]
    observation: str = Field(min_length=1, max_length=2000)
    symbol_id: str | None = Field(default=None,
        description="For behavior claims, identify the implemented function/method whose delivered body supports this specific observation, not the module's presumed purpose.")


class BoundaryClaimCheck(Contract):
    subject_type: Literal["candidate", "hypothesis"]
    subject_id: str
    claim_kind: Literal["declaration", "behavior", "dependency", "isolation", "absence_of_cycles"]
    scope_paths: list[str] = Field(min_length=1, max_length=40)
    support: list[BoundarySupport] = Field(min_length=1, max_length=80)
    coverage_complete: bool = False
    limitations: list[str] = Field(default_factory=list, max_length=20)


class BoundaryEvaluation(Evaluation):
    claim_checks: list[BoundaryClaimCheck] = Field(default_factory=list, max_length=60)
    validation_feedback: ClassVar[dict[str, str]] = Evaluation.validation_feedback | {
        "boundary_check_structure_invalid": "Return exactly one claim_check for every candidate and every confirmed/discarded hypothesis. Use exact subject IDs and real FILE paths, not directories. Repair the listed structural issues using delivered evidence; do not invent inspections. If evidence is lacking, retain an honest scoped candidate or unresolved hypothesis with sufficient=false and precise missing_information.",
        "too_short": "A required collection was empty. Every claim_check needs at least one scope_path and at least one support entry; every candidate needs at least one component and at least one evidence_id. An empty list is not a placeholder. If you did not inspect evidence that supports a subject, leave that hypothesis inconclusive and name the missing inspection in missing_information instead of asserting it.",
    }


class BoundaryFindingReview(FindingReview):
    scope_supported: bool = False
    checked_evidence_ids: list[str] = Field(default_factory=list, max_length=80)
    unverified_claims: list[str] = Field(default_factory=list, max_length=20)


class BoundaryHypothesisReview(Contract):
    hypothesis_id: str
    status: Literal["supported", "inconclusive"]
    rationale: str = Field(min_length=1, max_length=4000)
    scope_supported: bool = False
    checked_evidence_ids: list[str] = Field(default_factory=list, max_length=80)
    unverified_claims: list[str] = Field(default_factory=list, max_length=20)


class BoundaryReview(Review):
    findings: list[BoundaryFindingReview]
    hypotheses: list[BoundaryHypothesisReview] = Field(default_factory=list, max_length=60)
    validation_issues: list[str] = Field(default_factory=list)
    validation_feedback: ClassVar[dict[str, str]] = Review.validation_feedback | {
        "boundary_review_support_required": "An accepted boundary candidate requires scope_supported=true, no unverified_claims, and checked_evidence_ids covering every support item in its claim_check. Otherwise mark insufficient_evidence or rejected; do not invent verification.",
    }


class BoundaryFinding(Finding):
    claim_check: BoundaryClaimCheck | None = None
    validation_issues: list[str] = Field(default_factory=list)


class BoundaryResult(AuditResult):
    findings: list[BoundaryFinding]
    investigation_coverage: dict = Field(default_factory=dict,
        description="Host-derived indexed boundary coverage; navigation and inspected endpoints, not proof of isolation.")
    claim_checks: list[BoundaryClaimCheck] = Field(default_factory=list)
    critical_review: BoundaryReview | None = None
    failed_evaluation_attempt: BoundaryEvaluation | None = None
    evaluation_attempt_issues: list[dict[str, str]] = Field(default_factory=list)
    evaluation_evidence_status: Literal["not_evaluated", "current", "stale"] = "not_evaluated"
    evaluated_evidence_ids: list[str] = Field(default_factory=list,
        description="Delivered evidence available to the last structurally valid evaluation; not necessarily cited or verified.")
    pending_evaluation_evidence_ids: list[str] = Field(default_factory=list,
        description="Retained evidence not available to that evaluation. Its presence does not update prior conclusions.")


# Default design-principle criteria for the responsibility investigator's request.
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


# Responsibility investigation input: supplies the objective and cohesion/separation/placement criteria.
# Consumed by agents/maintainability/modularity/responsibility/ when investigating scoped components.
class ResponsibilityRequest(AuditRequest):
    objective: str = "Do components group coherent responsibilities or mix incompatible functionality?"
    criteria: list[Criterion] = Field(default_factory=responsibility_criteria, max_length=40)


# Observed responsibility: groups behaviors and possible reasons to change, with evidence on both sides.
# The responsibility investigator uses these records inside each ComponentAssessment.
class Responsibility(Contract):
    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    behaviors: list[str] = Field(default_factory=list)
    possible_change_reasons: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)


# Conflict between responsibilities: explains independent change reasons and the resulting maintenance risk.
# Included in ComponentAssessment when the responsibility investigator identifies incompatible concerns.
class ResponsibilityConflict(Contract):
    responsibility_ids: list[str] = Field(min_length=2)
    independent_change_rationale: str = Field(min_length=1)
    maintenance_risk: str = Field(min_length=1)


# Technical component analysis: associates responsibilities and conflicts with a real repository component ID.
# Produced in ResponsibilityEvaluation, then source-validated into InvestigatedComponent during finalization.
class ComponentAssessment(Contract):
    id: str = Field(min_length=1)
    component_id: str = Field(min_length=1, description="An actual file or symbol ID returned by repository tools.")
    responsibilities: list[Responsibility]
    potentially_incompatible: list[ResponsibilityConflict]
    cohesion: Literal["coherent", "mixed", "inconclusive"]
    architectural_justification: str
    evidence_ids: list[str] = Field(default_factory=list)


# Proposed responsibility finding: cites the analyses behind it and identifies its evidential basis.
# Emitted by the responsibility investigator's evaluate_evidence before review and host validation.
class ResponsibilityCandidate(CandidateFinding):
    assessment_ids: list[str] = Field(min_length=1)
    basis: Literal["behavioral", "metrics_only", "names_only"]


# Responsibility iteration output: combines typed finding candidates with component-level analyses.
# evaluate_evidence returns it to the shared investigator runtime for review or further investigation.
class ResponsibilityEvaluation(Evaluation):
    candidates: list[ResponsibilityCandidate]
    component_assessments: list[ComponentAssessment]


# Final responsibility finding: retains the reviewed judgment, analysis IDs and the claim's basis.
# Returned in ResponsibilityResult and preserved as a contribution by the modularity coordinator.
class ResponsibilityFinding(Finding):
    assessment_ids: list[str]
    basis: Literal["behavioral", "metrics_only", "names_only"]


class ResponsibilityHypothesisReview(Contract):
    hypothesis_id: str
    status: Literal["supported", "inconclusive"]
    rationale: str = Field(min_length=1)
    assessment_ids: list[str] = Field(default_factory=list)
    checked_evidence_ids: list[str] = Field(default_factory=list)
    scope_supported: bool = False
    unverified_claims: list[str] = Field(default_factory=list)


class ResponsibilityReview(Review):
    hypotheses: list[ResponsibilityHypothesisReview] = Field(default_factory=list)


# Host-enriched component analysis: resolves file/symbol location and evidence, recording validation issues.
# Built by the responsibility investigator's finalize step and retained even when evidence is insufficient.
class InvestigatedComponent(ComponentAssessment):
    path: str
    file_id: str
    symbol_name: str | None = None
    evidence: list[EvidenceReference]
    validation_status: Literal["source_backed", "insufficient_evidence"]
    validation_issues: list[str]


# Responsibility investigator output: extends the common report with inspected components and uncertainties.
# Returned by ResponsibilityAgent.run() and validated by the modularity coordinator during collection.
class ResponsibilityResult(AuditResult):
    findings: list[ResponsibilityFinding]
    components_investigated: list[InvestigatedComponent] = Field(default_factory=list)
    discarded_hypotheses: list[Hypothesis] = Field(default_factory=list)
    inconclusive_investigations: list[str] = Field(default_factory=list)
    unresolved_component_assessments: list[ComponentAssessment] = Field(default_factory=list,
        description="Retained inconclusive assessments whose component identity could not be resolved.")
    critical_review: ResponsibilityReview | None = None


# Architectural-boundary input: supplies the boundary objective and default design-principle criterion.
# Consumed by agents/maintainability/modularity/architecture_boundary/; its output uses AuditResult directly.
class ArchitectureBoundaryRequest(AuditRequest):
    model_config = ConfigDict(title="AuditRequest")

    objective: str = "Audit architectural boundaries and their impact on modularity."
    criteria: list[Criterion] = Field(default_factory=lambda: [Criterion(
        id="responsibility-boundaries", origin="design_principle",
        description="Keep responsibilities separated and dependencies aligned with declared component contracts.",
        provenance="Auditor design heuristic, not a normative ISO rule or a documented project constraint.",
    )], max_length=40)


# Separates demonstrated dependency harm from plausible risk, no observed impact or uncertainty.
ImpactKind = Literal["demonstrated", "plausible_risk", "none", "inconclusive"]
# Records the basis of a dependency finding so metrics or graph shape are not treated as consequences.
FindingBasis = Literal[
    "consequence_evidence", "metrics_only", "cycle_only", "transitivity_only",
    "interface_shape_only", "dependency_existence_only",
]


# Default criteria for concrete coupling, change propagation and justified dependency relationships.
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


# Dependency-impact input: defines the investigation objective and maintenance-consequence criteria.
# Consumed by agents/maintainability/modularity/dependency_impact/ before inspecting graph and source evidence.
class DependencyImpactRequest(AuditRequest):
    objective: str = "Do identified dependencies create coupling harmful to independent maintenance?"
    criteria: list[Criterion] = Field(default_factory=dependency_impact_criteria, max_length=40)


# Observed dependency: names actual source/target IDs and the indexed relationship when it is resolved.
# Used within dependency-impact analyses to distinguish graph facts from inferred runtime behavior.
class DependencyLink(Contract):
    id: str = Field(min_length=1)
    source_id: str = Field(min_length=1, description="Actual source file/symbol ID, not its name.")
    target_id: str = Field(min_length=1, description="Actual target file/symbol ID, not its name.")
    relationship_id: str | None = Field(default=None, description="Actual snapshot relationship ID; null if unresolved.")
    dependency_type: str = Field(min_length=1, description="Exact kind of the cited graph relationship, not an inferred runtime call.")
    evidence_ids: list[str] = Field(default_factory=list)


# Technical impact analysis: connects dependency paths to change scenarios, consequences and counterevidence.
# The dependency-impact investigator produces it during evaluation; finalize resolves its references.
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


# Proposed dependency-impact finding: references the supporting analyses and labels the claim's basis.
# Emitted in DependencyImpactEvaluation, then reviewed and checked against retained repository evidence.
class DependencyImpactCandidate(CandidateFinding):
    assessment_ids: list[str] = Field(min_length=1)
    basis: FindingBasis


# Dependency-impact iteration output: carries typed candidates alongside their causal analyses.
# Used by evaluate_evidence and the shared runtime to decide whether investigation can conclude.
class DependencyImpactEvaluation(Evaluation):
    candidates: list[DependencyImpactCandidate]
    dependency_assessments: list[DependencyAssessment]


# Reviewed dependency-impact finding: retains analysis references and whether its basis supports the claim.
# Returned in DependencyImpactResult and consumed by modularity coordination and manager consolidation.
class DependencyImpactFinding(Finding):
    assessment_ids: list[str]
    basis: FindingBasis


class DependencyHypothesisReview(Contract):
    hypothesis_id: str
    status: Literal["supported", "inconclusive"]
    rationale: str = Field(min_length=1)
    assessment_ids: list[str] = Field(default_factory=list)
    checked_evidence_ids: list[str] = Field(default_factory=list)
    scope_supported: bool = False
    unverified_claims: list[str] = Field(default_factory=list)


class DependencyImpactReview(Review):
    hypotheses: list[DependencyHypothesisReview] = Field(default_factory=list)


# Resolved endpoint location: identifies a repository component, file and optional symbol.
# The dependency-impact finalizer attaches it to both endpoints of an InvestigatedDependency.
class DependencyComponentReference(Contract):
    model_config = ConfigDict(title="ComponentReference")

    id: str
    file_id: str
    path: str
    symbol_name: str | None = None


# Host-enriched dependency: resolves both endpoint locations, evidence references and validation problems.
# Included in InvestigatedImpact so dependency-impact reports expose what was actually verified.
class InvestigatedDependency(DependencyLink):
    source: DependencyComponentReference
    target: DependencyComponentReference
    evidence: list[EvidenceReference]
    validation_status: Literal["source_backed", "insufficient_evidence"]
    validation_issues: list[str]


# Finalized impact analysis: adds verified dependencies, evidence, cycle information and validation status.
# Built during dependency-impact finalization and retained in DependencyImpactResult.dependency_assessments.
class InvestigatedImpact(DependencyAssessment):
    dependencies: list[InvestigatedDependency] = Field(default_factory=list)
    evidence: list[EvidenceReference]
    is_cycle: bool
    validation_status: Literal["source_backed", "insufficient_evidence"]
    validation_issues: list[str]


# Dependency-impact report: extends the shared output with resolved endpoints, analyses and uncertainty.
# Returned by DependencyImpactAgent.run() for validation and consolidation by the modularity coordinator.
class DependencyImpactResult(AuditResult):
    findings: list[DependencyImpactFinding]
    components_investigated: list[DependencyComponentReference] = Field(default_factory=list)
    dependency_assessments: list[InvestigatedImpact] = Field(default_factory=list)
    discarded_hypotheses: list[Hypothesis] = Field(default_factory=list)
    inconclusive_investigations: list[str] = Field(default_factory=list)
    critical_review: DependencyImpactReview | None = None


# Categories of abstraction findings; a useful abstraction may be reported as a design observation.
Category = Literal["useful_abstraction", "unnecessary_abstraction", "coupling", "missed_reuse"]
# Basis of an abstraction claim, distinguishing usage evidence from structural or naming-only signals.
Basis = Literal["usage_evidence", "structure_only", "metrics_only", "names_only"]


# Abstraction investigation input: scopes the concrete reuse benefits and costs of abstraction boundaries.
# Consumed by agents/maintainability/reusability/abstraction/ with optional file/component targets.
class AbstractionRequest(AuditRequest):
    objective: str = "Do abstractions facilitate reuse, or introduce unnecessary complexity and coupling?"
    targets: list[str] = Field(default_factory=list, max_length=20)
    criteria: list[Criterion] = Field(default_factory=lambda: [Criterion(
        id="abstraction-reuse", origin="design_principle",
        description="Assess concrete reuse benefits, variation, coupling and indirection costs, not abstraction counts.",
        provenance="Reusability investigation lens, not an ISO compliance rule or a numerical design threshold.",
    )], max_length=40)


# Indexed abstraction candidate: records a declaration's location and available relationship IDs.
# Discovery supplies it to the abstraction investigator and records selected candidates in coverage.
class AbstractionCandidateTarget(Contract):
    component_id: str
    path: str
    symbol_name: str | None
    kind: str
    start_line: int | None
    end_line: int | None
    relationship_ids: list[str]


class AbstractionHypothesis(Hypothesis):
    declaration_ids: list[str] = Field(default_factory=list, max_length=40,
        description="Selected declaration IDs this question commits to investigate. Discovery candidates alone are not commitments.")


class AbstractionPlan(InvestigationPlan):
    hypotheses: list[AbstractionHypothesis]


class AbstractionHypothesisValidation(Contract):
    iteration: int
    proposed: Hypothesis
    validated: Hypothesis


# Abstraction participant: explains a component's role and its evidence-backed relationship to a declaration.
# Used in AbstractionAssessment to connect contracts, implementations, consumers, tests and alternatives.
class Participant(Contract):
    component_id: str
    role: Literal["consumer", "implementation", "delegate", "contract", "duplicate", "composition", "test"]
    relationship_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list, max_length=16)
    usage_explanation: str = Field(min_length=1, max_length=2000)


# Technical abstraction analysis: weighs observed use, variation, indirection, coupling and counterevidence.
# Produced by the abstraction investigator's evaluation step; it is not a coordinator-level assessment.
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


# Proposed abstraction finding: binds a category and evidential basis to the relevant technical analyses.
# Appears in AbstractionEvaluation before shared review and abstraction-specific host checks.
class AbstractionCandidate(CandidateFinding):
    category: Category
    assessment_ids: list[str] = Field(min_length=1, max_length=12)
    basis: Basis


# Abstraction iteration output: pairs proposed findings with the technical assessments supporting them.
# Returned by the abstraction investigator's evaluate_evidence and retained for review/finalization.
class AbstractionEvaluation(Evaluation):
    candidates: list[AbstractionCandidate]
    abstraction_assessments: list[AbstractionAssessment] = Field(max_length=40)


class AbstractionHypothesisReview(Contract):
    hypothesis_id: str
    status: Literal["supported", "inconclusive"]
    rationale: str = Field(min_length=1)
    assessment_ids: list[str] = Field(default_factory=list)
    checked_evidence_ids: list[str] = Field(default_factory=list)
    scope_supported: bool = False
    unverified_claims: list[str] = Field(default_factory=list)
    resolution: Literal["confirmed", "discarded", "inconclusive"] = "inconclusive"


class AbstractionReview(Review):
    hypotheses: list[AbstractionHypothesisReview] = Field(default_factory=list)


# Resolved abstraction location: carries the component/file IDs, path and nullable symbol name.
# Used by the abstraction finalizer to locate declarations and inspected participants in the report.
class AbstractionComponentReference(Contract):
    model_config = ConfigDict(title="ComponentReference")

    id: str
    file_id: str
    path: str
    symbol_name: str | None


# Host-enriched participant: adds its resolved component, actual evidence and reference-validation issues.
# Included in InvestigatedAbstraction when the abstraction investigator finalizes an assessment.
class InspectedParticipant(Participant):
    component: AbstractionComponentReference
    evidence: list[EvidenceReference]
    validation_issues: list[str]


# Finalized abstraction analysis: resolves the declaration and participants and records evidence sufficiency.
# Retained in AbstractionResult to preserve technical reasoning even when it cannot support a finding.
class InvestigatedAbstraction(AbstractionAssessment):
    declaration: AbstractionComponentReference | None
    participants: list[InspectedParticipant]
    evidence: list[EvidenceReference]
    validation_status: Literal["source_backed", "insufficient_evidence"]
    validation_issues: list[str]


# Reviewed abstraction finding: preserves category, analysis IDs, basis and any duplicate-of relationship.
# Returned in AbstractionResult and used as a typed contribution by the reusability coordinator.
class AbstractionFinding(Finding):
    category: Category
    assessment_ids: list[str]
    basis: Basis
    duplicate_of: str | None = None


# Abstraction coverage record: distinguishes selected/assessed declarations from omitted or unassessed ones.
# The abstraction investigator attaches it to its result so bounded inspection is not mistaken for exhaustiveness.
class AbstractionCoverage(Contract):
    targets: list[str] = Field(default_factory=list)
    selected_candidates: list[AbstractionCandidateTarget] = Field(default_factory=list)
    candidate_count: int = 0
    omitted_candidates: int = 0
    inspected_paths: list[str] = Field(default_factory=list)
    assessed_declarations: list[str] = Field(default_factory=list)
    planned_declarations: list[str] = Field(default_factory=list)
    unplanned_candidates: list[str] = Field(default_factory=list)
    unassessed_candidates: list[str] = Field(default_factory=list)
    exhaustive: bool = False


# Abstraction investigator output: includes reviewed findings, technical analyses, coverage and tool failures.
# Returned by AbstractionAgent.run(); its investigator discriminator selects this type in reusability collection.
class AbstractionResult(AuditResult):
    plan: AbstractionPlan | None
    findings: list[AbstractionFinding]
    investigator: Literal["AbstractionAgent"] = "AbstractionAgent"
    quality_attribute: Literal["reusability"] = "reusability"
    status: Literal["completed", "partial", "failed"] = "partial"
    abstractions_investigated: list[InvestigatedAbstraction] = Field(default_factory=list)
    coverage: AbstractionCoverage = Field(default_factory=AbstractionCoverage)
    inconclusive_investigations: list[str] = Field(default_factory=list)
    tool_failures: list[str] = Field(default_factory=list)
    critical_review: AbstractionReview | None = None
    hypothesis_validation_history: list[AbstractionHypothesisValidation] = Field(default_factory=list)


# Qualifies whether a shared implementation is advisable, conditional or unsuitable for an examined group.
Classification = Literal["recommended", "conditional", "not_recommended"]


# Reuse-opportunity inspection routes: request more tool interaction or proceed to validation.
# Used by the reuse-opportunity graph while examining discovered implementation groups.
class ReuseInspectRoute(StrEnum):
    USE_TOOLS = "use_tools"
    VALIDATE = "validate"


# Reuse-opportunity validation routes: inspect again, finalize normally or finalize with limitations.
# Used after evidence checks to bound investigation and make incomplete termination explicit.
class ReuseValidationRoute(StrEnum):
    INSPECT = "inspect"
    FINALIZE = "finalize"
    LIMITED_FINALIZE = "limited_finalize"


# Reuse-opportunity input: asks whether similar responsibilities can share an implementation safely.
# Consumed by agents/maintainability/reusability/reuse_opportunity/ to scope discovery and comparison.
class ReuseOpportunityRequest(AuditRequest):
    objective: str = "Do conceptually similar functionalities exist that could share an implementation?"
    targets: list[str] = Field(default_factory=list, max_length=20)
    criteria: list[Criterion] = Field(default_factory=lambda: [Criterion(
        id="reuse-opportunity", origin="design_principle",
        description="Assess compatible responsibilities and sharing tradeoffs, not textual duplication alone.",
        provenance="Reusability investigation lens, not a mandatory refactor or normative quality threshold.",
    )], max_length=40)


# Indexed implementation location: identifies component/file IDs, symbol, language and source range.
# Reuse discovery groups these records so later analysis can retrieve the exact candidate implementations.
class CandidateLocation(Contract):
    component_id: str
    file_id: str
    path: str
    symbol: str
    start_line: int
    end_line: int
    language: str


# Discovery group: associates candidate implementations with the signals that made them worth comparing.
# Supplied to reuse-opportunity inspection and preserved in DiscoveryCoverage.selected_groups.
class ReuseGroup(Contract):
    id: str
    members: list[CandidateLocation]
    discovery_signals: list[str]


class ReuseHypothesis(Hypothesis):
    group_ids: list[str] = Field(default_factory=list, max_length=20,
        description="Exact selected group IDs committed to this question; discovery alone is not a commitment.")


class ReusePlan(InvestigationPlan):
    hypotheses: list[ReuseHypothesis]


# Implementation semantics: records purpose, contracts, effects, failure behavior and dependencies with evidence.
# Two such records form the core comparison inside a reuse-opportunity ReuseAssessment.
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


# Caller constraints: links an implementation to an actual caller/relationship and supporting evidence.
# The reuse-opportunity investigator uses it to check whether sharing would preserve real usage constraints.
class CallerInspection(Contract):
    implementation_id: str
    caller_id: str
    relationship_id: str
    evidence_ids: list[str] = Field(max_length=16)
    constraints: str = Field(min_length=1, max_length=1500)


# Technical reuse comparison: weighs exactly two implementations, their callers, benefits, differences and risks.
# Produced during reuse-opportunity evaluation; it is a local analysis rather than a coordinator report.
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


# Proposed reuse finding: references the examined group and qualifies whether sharing is advisable.
# Included in ReuseEvaluation, then reviewed and checked against the group's technical assessment.
class ReuseCandidate(CandidateFinding):
    group_id: str
    classification: Classification


# Reuse-opportunity iteration output: combines typed candidates with the implementation-group assessments.
# Returned by evaluate_evidence to guide validation, further inspection and finalization.
class ReuseEvaluation(Evaluation):
    candidates: list[ReuseCandidate]
    group_assessments: list[ReuseAssessment] = Field(max_length=20)


# Host-enriched group analysis: attaches candidate locations, resolved evidence and validation outcomes.
# Built by the reuse-opportunity finalizer and retained in ReuseOpportunityResult.examined_groups.
class ExaminedGroup(ReuseAssessment):
    qualification_notes: list[str] = Field(default_factory=list)
    proposed_evidence_ids: dict[str, list[str]] = Field(default_factory=dict)
    members: list[CandidateLocation]
    evidence: list[EvidenceReference]
    validation_issues: list[str]
    validation_status: Literal["source_backed", "insufficient_evidence"]


# Reviewed reuse finding: preserves group classification, stable identity and duplicate-of relationships.
# Included in ReuseOpportunityResult and consolidated by the reusability coordinator.
class ReuseFinding(Finding):
    group_id: str
    classification: Classification
    stable_id: str = ""
    duplicate_of: str | None = None
    conditions: list[str] = Field(default_factory=list)
    sharing_boundary: str = ""
    unknowns: list[str] = Field(default_factory=list)


# Reuse discovery coverage: counts eligible/shortlisted symbols, comparisons, omissions and unassessed groups.
# Included in the reuse-opportunity result to expose the limits of the search and inspected scope.
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


# Reuse-opportunity output: retains findings, examined groups, coverage, tool failures and execution trace.
# Returned by ReuseOpportunityAgent.run() and discriminated by investigator during reusability collection.
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


# Root categories used to classify concrete component-adaptation constraints.
ConstraintType = Literal[
    "infrastructure", "environment", "global_state", "framework", "configuration",
    "side_effects", "interface", "dependency_injection", "platform", "data_schema",
]
# Separates verified obstacles and context-qualified risks from mitigated or unresolved constraints.
Conclusion = Literal["verified_obstacle", "context_dependent_risk", "mitigated", "unknown"]
# Repository tools allowed in structured inspection requests from the adaptability investigator.
ToolName = Literal[
    "list_files", "find_symbols", "list_relationships", "get_source_excerpt",
    "search_repository_text", "get_evidence", "get_infrastructure",
]


# Adaptability inspection routes: request repository tools or proceed to evidence validation.
# InspectionDecision uses these values to control the component-adaptability inspection node.
class AdaptabilityInspectRoute(StrEnum):
    USE_TOOLS = "use_tools"
    VALIDATE = "validate"


# Adaptability validation routes: inspect further, finalize or finalize with explicit limitations.
# Consumed by the adaptability graph after checking current evidence and investigation blockers.
class AdaptabilityValidationRoute(StrEnum):
    INSPECT = "inspect"
    FINALIZE = "finalize"
    LIMITED_FINALIZE = "limited_finalize"


# Structured tool request: restricts the tool name and carries its arguments as bounded JSON text.
# The adaptability investigator emits it inside InspectionDecision for host-side tool execution.
class InspectionToolRequest(Contract):
    name: ToolName
    arguments_json: str = Field(min_length=2, max_length=4000)


# Inspection-step decision: requires tool requests for use_tools and forbids them when choosing validate.
# Produced by the adaptability investigator's investigate step before tool execution or validation.
class InspectionDecision(Contract):
    action: AdaptabilityInspectRoute
    tool_requests: list[InspectionToolRequest] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def consistent_action(self):
        if (self.action == AdaptabilityInspectRoute.USE_TOOLS) != bool(self.tool_requests):
            raise ValueError("use_tools requires requests; validate forbids requests")
        return self


# Adaptability input: combines component/file targets with an optional explicitly supplied destination context.
# Consumed by agents/maintainability/reusability/component_adaptability/ without inheriting another domain's request.
class ComponentAdaptabilityRequest(AuditRequest, TargetContext):
    objective: str = "Which constraints make a component difficult to reuse in another context?"
    targets: list[str] = Field(default_factory=list, max_length=20)
    component_ids: list[str] = Field(default_factory=list, max_length=20)
    criteria: list[Criterion] = Field(default_factory=lambda: [Criterion(
        id="component-adaptability", origin="design_principle",
        description="Investigate concrete context-specific adaptation obstacles and existing mitigating seams.",
        provenance="Reusability investigation lens; dependencies are not automatically defects or normative violations.",
    )], max_length=40)


# Indexed adaptation signal: records a constraint category, source line and discovery rule.
# Discovery attaches these hints to ComponentTarget; later source inspection determines their significance.
class DiscoverySignal(Contract):
    constraint_type: ConstraintType
    line: int
    rule: str


# Inspectable adaptability target: locates a component's source range and the signals selecting it.
# Used by component-adaptability discovery, inspection and the finalized constraint report.
class ComponentTarget(Contract):
    component_id: str
    file_id: str
    path: str
    symbol: str | None
    start_line: int
    end_line: int
    signals: list[DiscoverySignal]
    source_role: Literal["implementation", "fixture", "configuration", "auxiliary"] = "implementation"


class AdaptabilityHypothesis(Hypothesis):
    component_ids: list[str] = Field(default_factory=list, max_length=20,
        description="Exact selected component IDs committed to the original question.")


class AdaptabilityPlan(InvestigationPlan):
    hypotheses: list[AdaptabilityHypothesis]


class AdaptabilityHypothesisReview(Contract):
    hypothesis_id: str
    assessment_ids: list[str] = Field(default_factory=list)
    checked_evidence_ids: list[str] = Field(default_factory=list)
    scope_supported: bool = False
    resolution: Literal["confirmed", "discarded", "inconclusive"] = "inconclusive"
    contract_and_fixture_claims_supported: bool = False
    rationale: str = Field(min_length=1)
    unverified_claims: list[str] = Field(default_factory=list)


class AdaptationClaimReview(Contract):
    assessment_id: str
    checked_evidence_ids: list[str] = Field(default_factory=list)
    required_change: str = ""
    existing_seams: str = ""
    why_seams_insufficient: str = ""
    target_mismatch_supported: bool = False
    input_normalization_suffices: bool | None = None
    change_scope: Literal["content_only", "input_normalization", "component_logic", "unknown"] = "unknown"
    qualified_impact: str = Field(default="", max_length=2500,
        description="Local, context-qualified adaptation consequence; do not infer impossibility or complete rewrites from domain-specific content.")
    qualified_recommendation: str = Field(default="", max_length=2500)


class AdaptabilityReview(Review):
    hypotheses: list[AdaptabilityHypothesisReview] = Field(default_factory=list)
    adaptation_checks: list[AdaptationClaimReview] = Field(default_factory=list)


# Observed component usage: links a caller/relationship to instantiation or configuration evidence.
# Included in ConstraintAssessment to test how a proposed adaptation obstacle affects actual consumers.
class UsageInspection(Contract):
    caller_id: str
    relationship_id: str
    evidence_ids: list[str] = Field(max_length=16)
    instantiation_configuration: str = Field(min_length=1, max_length=2000)


# Technical adaptation analysis: relates a root constraint to a stated context, impact, seams and counterevidence.
# Produced in adaptability evaluation; explicit/plausible context and unknowns qualify the interpretation.
class ConstraintAssessment(Contract):
    id: str
    component_id: str
    hypothesis_id: str
    constraint_type: ConstraintType
    constraint_key: str = Field(min_length=1, max_length=160)
    schema_dependency_basis: Literal["input_contract", "fixed_domain_schema", "fixture_only", "unknown"] = "unknown"
    schema_adaptation_analysis: str = Field(default="", max_length=2500,
        description="For data_schema, distinguish input shape from fixed domain values and explain why existing parameters/mappings do not suffice for the assessed context.")
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


# Proposed adaptation finding: cites constraint analyses and distinguishes verified obstacles from contextual risks.
# Produced in AdaptabilityEvaluation before review and context/evidence validation by the host.
class AdaptabilityCandidate(CandidateFinding):
    split_from: str | None = None
    assessment_ids: list[str] = Field(min_length=1, max_length=16)
    constraint_type: ConstraintType
    classification: Literal["verified_obstacle", "context_dependent_risk"]


# Adaptability iteration output: carries candidates, constraint analyses, cleared components and coverage rationale.
# evaluate_evidence returns it; its validator requires a concrete reason when further investigation is blocked.
class AdaptabilityEvaluation(Evaluation):
    validation_feedback: ClassVar[dict[str, str]] = Evaluation.validation_feedback | {
        "investigation_blocker_required": "When can_investigate_further is false, continuation_reason must explain a concrete blocker. If more evidence can be obtained, use can_investigate_further=true and describe the missing information instead. Do not invent a blocker or claim sufficient evidence to pass validation.",
    }
    candidates: list[AdaptabilityCandidate]
    constraint_assessments: list[ConstraintAssessment] = Field(max_length=40)
    cleared_components: list[str] = Field(default_factory=list, max_length=20)
    coverage_rationale: str = Field(min_length=1, max_length=3000)
    can_investigate_further: bool = True
    continuation_reason: str = Field(default="", max_length=2000)
    continuation_blocker: Literal["none", "external_context", "unavailable_source", "dynamic_behavior"] = "none"

    @model_validator(mode="after")
    def explain_blocker(self):
        if not self.can_investigate_further and not self.continuation_reason.strip():
            raise PydanticCustomError("investigation_blocker_required",
                self.validation_feedback["investigation_blocker_required"])
        return self


# Host-enriched constraint analysis: attaches the resolved target, evidence and validation issues/status.
# Built during adaptability finalization and preserved in ComponentAdaptabilityResult.examined_constraints.
class ExaminedConstraint(ConstraintAssessment):
    component: ComponentTarget | None
    evidence: list[EvidenceReference]
    validation_issues: list[str]
    validation_status: Literal["source_backed", "insufficient_evidence"]


# Reviewed adaptation finding: retains context-qualified impact/effort, assumptions, mitigations and duplicate identity.
# Returned in ComponentAdaptabilityResult and used by the reusability coordinator without losing context.
class AdaptabilityFinding(Finding):
    split_from: str | None = None
    validation_issues: list[str] = Field(default_factory=list)
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


# Adaptability coverage: records eligible/selected/omitted components, file-scan truncation and unassessed targets.
# Included in the investigator's result to distinguish bounded inspection from exhaustive coverage.
class AdaptabilityCoverage(Contract):
    planned_components: list[str] = Field(default_factory=list)
    unplanned_components: list[str] = Field(default_factory=list)
    selected_components: list[ComponentTarget]
    eligible_components: int
    omitted_components: int
    scanned_files: int
    omitted_scan_files: int
    scan_truncated_paths: list[str]
    inspected_paths: list[str] = Field(default_factory=list)
    unassessed_components: list[str] = Field(default_factory=list)
    exhaustive: bool = False


# Tool telemetry entry: records a call ID, tool, outcome, elapsed time and cache use.
# The adaptability investigator adds these entries to its final output to explain inspection activity.
class ToolActivity(Contract):
    call_id: str
    tool: str
    status: str
    seconds: float
    cache_hit: bool


# Adaptability output: retains context, findings, examined constraints, coverage, blockers and execution telemetry.
# Returned by ComponentAdaptabilityAgent.run() and validated as a concrete investigator result by reusability coordination.
class ComponentAdaptabilityResult(AuditResult):
    candidate_split_history: dict[str, AdaptabilityCandidate] = Field(default_factory=dict)
    plan: AdaptabilityPlan | None
    critical_review: AdaptabilityReview | None = None
    hypothesis_validation_issues: dict[str, list[str]] = Field(default_factory=dict)
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
