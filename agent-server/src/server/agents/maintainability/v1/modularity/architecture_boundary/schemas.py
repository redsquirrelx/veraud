"""Canonical contracts for this maintainability participant."""

from typing import ClassVar, Literal

from pydantic import ConfigDict, Field

from server.contracts.audit import (
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
)


class BoundarySupport(Contract):
    evidence_id: str
    role: Literal["declaration", "implementation", "usage", "composition", "dependency"]
    observation: str = Field(min_length=1, max_length=2000)
    symbol_id: str | None = Field(default=None,
        description="For behavior claims, identify the implemented function/method whose delivered body supports this specific observation, not the module's presumed purpose.")

class BoundaryVerification(Contract):
    dimension: Literal["dependency_direction", "shared_resources", "composition", "deployment"]
    evidence_ids: list[str] = Field(min_length=1, max_length=40)
    observation: str = Field(min_length=1, max_length=2000)

class BoundaryClaimCheck(Contract):
    subject_type: Literal["candidate", "hypothesis"]
    subject_id: str
    claim_kind: Literal["declaration", "behavior", "dependency", "isolation", "absence_of_cycles", "deployment"]
    scope_paths: list[str] = Field(min_length=1, max_length=40)
    support: list[BoundarySupport] = Field(min_length=1, max_length=80)
    coverage_complete: bool = False
    limitations: list[str] = Field(default_factory=list, max_length=20)
    verifications: list[BoundaryVerification] = Field(default_factory=list, max_length=8,
        description="For isolation: separately verify dependency direction, shared resources and composition. Deployment also needs deployment configuration. All entries cite delivered source, not an assertion of coverage.")

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


class StructuralRelationship(Contract):
    id: str
    source_id: str
    target_id: str
    source_path: str
    target_path: str
    kind: str


class IntegrationPoint(Contract):
    id: str
    file_id: str
    path: str
    project_id: str
    start_line: int
    end_line: int
    content_hash: str
    mechanism: str
    route: str | None = None
    method: str | None = None
    authority: str | None = None
    indexed_entrypoint_id: str | None = None


class IntegrationLink(Contract):
    id: str
    client: IntegrationPoint
    endpoints: list[IntegrationPoint] = Field(default_factory=list)
    binding_points: list[IntegrationPoint] = Field(default_factory=list)
    target_project_id: str | None = None
    match_basis: Literal["authority_route_method", "route_only_ambiguous", "ambiguous_destination", "unresolved_target"]
    status: Literal["structural_candidate", "ambiguous"]


class StructuralSignal(Contract):
    kind: Literal["direction", "cycle", "component_boundary", "encapsulation", "discovery", "integration"]
    observed: list[str] = Field(min_length=1)
    inference: str
    relationships: list[StructuralRelationship] = Field(default_factory=list)
    symbol_ids: list[str] = Field(default_factory=list)
    entrypoint_ids: list[str] = Field(default_factory=list)
    basis: Literal["corroborated", "indexed", "inferred"] = "indexed"
    integration_links: list[IntegrationLink] = Field(default_factory=list)


class StructuralQuery(Contract):
    tool: Literal["list_files", "find_symbols", "list_relationships"]
    arguments: dict = Field(default_factory=dict)


class BoundaryInvestigation(Contract):
    id: str = Field(min_length=1)
    priority: Literal["high", "medium", "low"]
    scope: list[str] = Field(min_length=1)
    structural_signal: StructuralSignal
    question: str = Field(min_length=1)
    evidence_needed: list[str] = Field(min_length=1)
    investigation_strategy: list[StructuralQuery] = Field(min_length=1)
    completion_condition: str = Field(min_length=1)
    scope_kind: Literal["internal", "inter_application", "integration_discovery"] = "internal"
    project_ids: list[str] = Field(default_factory=list)


class BoundaryPlan(InvestigationPlan):
    """Exploration tasks, deliberately not defect hypotheses."""

    hypotheses: list[Hypothesis] = Field(default_factory=list, max_length=0)
    investigations: list[BoundaryInvestigation] = Field(default_factory=list, max_length=15)
    limitations: list[str] = Field(default_factory=list)
    snapshot_hash: str


class BoundaryPlanSelection(Contract):
    """The model ranks host-grounded opportunities, never inventing entities."""

    opportunity_ids: list[str] = Field(max_length=15)
    discovery_queries: list[StructuralQuery] = Field(default_factory=list, max_length=3)


class BoundaryToolQuery(Contract):
    tool: Literal["list_files", "find_symbols", "list_relationships", "get_source_excerpt",
        "search_repository_text", "get_evidence", "get_infrastructure"]
    arguments: dict = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=1000)
    scope_expansion: str = Field(default="", max_length=1000,
        description="Concrete reason to inspect a path/entity outside the initial task scope.")


class BoundaryCandidate(CandidateFinding):
    inferred_boundary: str = Field(min_length=1, max_length=2000)
    contradictory_dependency: str = Field(min_length=1, max_length=2000)
    technical_basis: str = Field(min_length=1, max_length=3000)
    symbol_ids: list[str] = Field(default_factory=list, max_length=40)
    relationship_ids: list[str] = Field(default_factory=list, max_length=40)


class BoundaryInvestigationResult(Contract):
    investigation_id: str
    status: Literal["finding_candidate", "no_finding", "inconclusive"]
    summary: str = Field(min_length=1, max_length=2000)
    justification: str = Field(min_length=1, max_length=4000)
    components: list[str] = Field(default_factory=list, max_length=40)
    symbol_ids: list[str] = Field(default_factory=list, max_length=80)
    relationship_ids: list[str] = Field(default_factory=list, max_length=80)
    evidence_ids: list[str] = Field(default_factory=list, max_length=80)
    candidates: list[BoundaryCandidate] = Field(default_factory=list, max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=40)


class BoundaryCandidateOrigin(Contract):
    investigation_id: str
    candidate_id: str


class BoundaryInvestigationTurn(Contract):
    validation_feedback: ClassVar[dict[str, str]] = {
        "invalid_boundary_query": "Use an enabled tool and its supplied argument schema with exact accessible references.",
        "scope_expansion_reason_required": "Provide scope_expansion explaining the concrete reason for an out-of-scope path/entity or unscoped query.",
        "unknown_or_undelivered_evidence": "Cite only evidence IDs in the current context. Retrieve reusable queries before citing their evidence.",
        "uninspected_component": "Components must be exact paths with cited delivered source, not names or directories.",
        "unexamined_relationship": "Use only relationship IDs actually returned by list_relationships. Integration claims should cite client/endpoint source, not invented edges.",
        "uninspected_symbol": "Use only indexed symbol IDs overlapping cited source ranges.",
        "conclusion_requires_inspected_source_and_components": "finding_candidate and no_finding require source evidence and inspected components. Otherwise return inconclusive with limitations.",
        "unverified_source_provenance": "The cited source cannot be attributed to the retained commit. Return inconclusive with the provenance limitation; do not invent verification.",
        "candidate_evidence_not_in_conclusion": "Include every candidate citation in the conclusion evidence_ids.",
        "dependency_endpoints_source_not_inspected": "Inspect and cite source at both endpoints of a candidate's indexed dependency.",
        "duplicate_candidate_or_unknown_criterion": "Use unique candidate IDs and only supplied criterion IDs.",
        "inconclusive_requires_limitations": "An inconclusive result requires a concrete limitation.",
        "candidate_status_mismatch": "finding_candidate requires one or more candidates; no_finding and inconclusive require candidates=[].",
        "close_requires_current_investigation_conclusion": "Return action=close, queries=[] and a conclusion with the current investigation_id.",
        "tools_requires_queries_without_conclusion": "Return action=tools with one or more queries and conclusion=null.",
    }
    action: Literal["tools", "close"]
    queries: list[BoundaryToolQuery] = Field(default_factory=list, max_length=4)
    conclusion: BoundaryInvestigationResult | None = None


class BoundaryCitationPatch(Contract):
    subject_id: str = Field(description="conclusion, or an existing candidate ID")
    field: Literal["components", "evidence_ids", "symbol_ids", "relationship_ids"]
    values: list[str] = Field(max_length=80)


class BoundaryCitationRepair(Contract):
    validation_feedback: ClassVar[dict[str, str]] = BoundaryInvestigationTurn.validation_feedback
    action: Literal["patch", "tools", "inconclusive"]
    corrections: list[BoundaryCitationPatch] = Field(default_factory=list, max_length=20)
    queries: list[BoundaryToolQuery] = Field(default_factory=list, max_length=4)
    limitation: str = Field(default="", max_length=1000)


class BoundaryResult(AuditResult):
    plan: BoundaryPlan | InvestigationPlan | None
    findings: list[BoundaryFinding]
    request_fingerprint: str = ""
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
    investigation_tasks: list[dict] = Field(default_factory=list)
    investigation_progress: list[dict] = Field(default_factory=list)
    investigation_results: list[BoundaryInvestigationResult] = Field(default_factory=list)
    candidates: list[BoundaryCandidate] = Field(default_factory=list,
        description="Consolidated provisional candidates; original claims remain in investigation_results.")
    candidate_origins: dict[str, list[BoundaryCandidateOrigin]] = Field(default_factory=dict,
        description="Consolidated candidate ID to original investigation and local candidate IDs.")
    next_phase: Literal["synthesis"] | None = None
    consumption_by_phase: dict[str, dict[str, int]] = Field(default_factory=dict)
    continuation_usage: dict[str, int] = Field(default_factory=dict,
        description="Previous execution usage, kept separate from this run's counters.")

class ArchitectureBoundaryRequest(AuditRequest):
    model_config = ConfigDict(title="AuditRequest")

    objective: str = "Investigate dependencies that may contradict architectural boundaries inferred from code and structural relationships."
    targets: list[str] = Field(default_factory=list, max_length=12,
        description="Initial repository paths, module names, file IDs or symbol IDs. Related endpoints may be included.")
    continuation: BoundaryResult | None = Field(default=None,
        description="Prior result for the exact same snapshot, commit, objective and criteria. Source is re-delivered through bounded repository tools and conclusions revalidated; previous usage stays separate.")
    criteria: list[Criterion] = Field(default_factory=lambda: [Criterion(
        id="architectural-boundaries", origin="design_principle",
        description="Investigate whether dependency directions and integration access paths respect boundaries supported by code declarations and structural relationships.",
        provenance="Auditor design heuristic, not a normative ISO rule or a documented project constraint.",
    )], max_length=40)

from .config import BoundaryConfig

__all__ = ['AuditRequest', 'AuditResult', 'BaseAuditRequest', 'BoundaryClaimCheck', 'BoundaryConfig', 'BoundaryEvaluation', 'BoundaryFinding', 'BoundaryFindingReview', 'BoundaryReview', 'BoundarySupport', 'CandidateFinding', 'Contract', 'Criterion', 'Evaluation', 'EvidenceReference', 'Finding', 'FindingReview', 'Hypothesis', 'InvestigationPlan', 'Review']

BaseAuditRequest = AuditRequest
AuditRequest = ArchitectureBoundaryRequest
AuditResult = BoundaryResult
