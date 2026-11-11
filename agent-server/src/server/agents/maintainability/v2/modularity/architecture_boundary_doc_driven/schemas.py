"""Canonical contracts for this maintainability participant."""

from typing import ClassVar, Literal

from pydantic import ConfigDict, Field, model_validator

from server.agents.architecture_context.schemas import (
    ArchitectureContextResult,
    KnowledgeClaim,
)
from server.contracts.audit import (
    AuditRequest,
    AuditResult,
    CandidateFinding,
    Contract,
    Criterion,
    Evaluation,
    EvidenceReference,
    FindingReview,
    Hypothesis,
    InvestigationPlan,
    Review,
)
from server.services.document_indexing import IndexReference


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

class BoundaryFinding(CandidateFinding):
    """Source-linked investigation candidate, without a critical-review verdict."""

    evidence_ids: list[str] = Field(default_factory=list)
    criterion: Criterion
    evidence: list[EvidenceReference]
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
    kind: Literal["direction", "cycle", "component_boundary", "encapsulation", "discovery", "integration", "documented_boundary"]
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
    document_claim_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def documentary_references(self):
        if self.structural_signal.kind == "documented_boundary" and not self.document_claim_ids:
            raise ValueError("A documentary investigation requires document_claim_ids")
        if len(self.document_claim_ids) != len(set(self.document_claim_ids)):
            raise ValueError("Document claim IDs must be unique")
        return self


class DocumentClaimPortion(Contract):
    id: str
    scope_paths: list[str] = Field(min_length=1, max_length=12)
    relationship_ids: list[str] = Field(default_factory=list)
    opportunity_ids: list[str] = Field(default_factory=list)


class DocumentClaimRecord(Contract):
    """Documentary identity/provenance, never an entry in the code evidence ledger."""

    claim: KnowledgeClaim
    document_index: IndexReference | None
    section_paths: dict[str, str]
    status: Literal["applicable", "not_applicable", "uncertain", "unmapped", "incompatible", "invalid_reference", "scope_limit"]
    reason: str = Field(min_length=1)
    scope_paths: list[str] = Field(default_factory=list)
    opportunity_ids: list[str] = Field(default_factory=list)
    boundary_family: str | None = None
    mapping_basis: Literal["exact", "corroborated", "ambiguous", "unmapped"] = "unmapped"
    owner_paths: dict[str, list[str]] = Field(default_factory=dict)
    symbol_ids: list[str] = Field(default_factory=list)
    subject_paths: list[str] = Field(default_factory=list)
    excluded_paths: list[str] = Field(default_factory=list)
    unresolved_references: list[str] = Field(default_factory=list)
    portions: list[DocumentClaimPortion] = Field(default_factory=list)
    unrepresented_paths: list[str] = Field(default_factory=list)


class BoundaryPlan(InvestigationPlan):
    """Exploration tasks, deliberately not defect hypotheses."""

    hypotheses: list[Hypothesis] = Field(default_factory=list, max_length=0)
    investigations: list[BoundaryInvestigation] = Field(default_factory=list, max_length=15)
    limitations: list[str] = Field(default_factory=list)
    snapshot_hash: str
    document_claims: dict[str, DocumentClaimRecord] = Field(default_factory=dict)


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
    document_claim_ids: list[str] = Field(default_factory=list,
        description="Applicable documentary contradictions supporting this provisional candidate; never technical evidence IDs.")


class ClaimAssessment(Contract):
    claim_id: str
    status: Literal["supported", "contradicted", "not_applicable", "inconclusive"]
    rationale: str = Field(min_length=1, max_length=4000,
        description="Identify the architectural obligation, its local applicability and the observed mechanism; exclude functional/data requirements.")
    code_evidence_ids: list[str] = Field(default_factory=list, max_length=80)
    scope_paths: list[str] = Field(default_factory=list, max_length=40,
        description="Exact inspected files, not the whole mapped scope of a global rule.")
    exceptions_examined: list[str] = Field(default_factory=list, max_length=20)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    assessment_origin: Literal["investigator", "host_pending", "unknown"] = "unknown"


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
    claim_assessments: list[ClaimAssessment] = Field(default_factory=list,
        description="Independent local assessments only; supported never establishes repository-wide compliance. Missing assessments are retained as inconclusive by the host.")
    document_claim_delivery: dict[str, Literal["delivered", "unavailable", "not_delivered"]] = Field(default_factory=dict,
        description="Host-recorded prompt delivery, not applicability or evaluation. Absent entries in legacy results mean unknown.")


class LocalClaimAssessment(Contract):
    id: str
    investigation_id: str
    assessment: ClaimAssessment
    delivery_status: Literal["delivered", "unavailable", "not_delivered", "unknown"]
    effective: bool
    investigation_limitations: list[str] = Field(default_factory=list)
    integrity_issues: list[str] = Field(default_factory=list)


class ClaimAssessmentComparison(Contract):
    assessment_ids: list[str] = Field(min_length=2, max_length=2)
    scope_relation: Literal["different_scopes", "same_technical_anchors", "overlapping_or_unknown"]
    limitation: str


class ConsolidatedClaimAssessments(Contract):
    claim_id: str = Field(description="Foreign key to plan.document_claims; original claim and documentary provenance remain there.")
    assessments: list[LocalClaimAssessment] = Field(default_factory=list)
    selected_investigation_ids: list[str] = Field(default_factory=list)
    evaluated_investigation_ids: list[str] = Field(default_factory=list)
    has_contradiction: bool = False
    has_inconclusive: bool = False
    coverage_status: Literal["not_evaluated", "partial"] = "not_evaluated"
    comparisons: list[ClaimAssessmentComparison] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class DocumentarySynthesisCoverage(Contract):
    selected_claim_ids: list[str] = Field(default_factory=list)
    delivered_claim_ids: list[str] = Field(default_factory=list)
    delivery_unknown_claim_ids: list[str] = Field(default_factory=list)
    evaluated_claim_ids: list[str] = Field(default_factory=list)
    source_examined_claim_ids: list[str] = Field(default_factory=list)
    contradicted_claim_ids: list[str] = Field(default_factory=list)
    locally_supported_claim_ids: list[str] = Field(default_factory=list)
    locally_not_applicable_claim_ids: list[str] = Field(default_factory=list)
    inconclusive_claim_ids: list[str] = Field(default_factory=list)
    selected_not_evaluated_claim_ids: list[str] = Field(default_factory=list)
    partially_covered_claim_ids: list[str] = Field(default_factory=list)


class DocumentarySynthesisIssue(Contract):
    code: str
    claim_id: str = ""
    investigation_ids: list[str] = Field(default_factory=list)
    assessment_ids: list[str] = Field(default_factory=list)
    reference_ids: list[str] = Field(default_factory=list)
    message: str


class DocumentarySynthesis(Contract):
    claims: dict[str, ConsolidatedClaimAssessments] = Field(default_factory=dict)
    unresolved_assessments: list[LocalClaimAssessment] = Field(default_factory=list)
    coverage: DocumentarySynthesisCoverage = Field(default_factory=DocumentarySynthesisCoverage)
    integrity_issues: list[DocumentarySynthesisIssue] = Field(default_factory=list)
    global_compliance_established: Literal[False] = False

    @model_validator(mode="after")
    def assessment_identity(self):
        ids = []
        for key, claim in self.claims.items():
            if key != claim.claim_id or any(row.assessment.claim_id != key for row in claim.assessments):
                raise ValueError("Consolidated claim/assessment identity mismatch")
            effective = [row for row in claim.assessments if row.effective]
            if (claim.evaluated_investigation_ids != sorted({row.investigation_id for row in effective}) or
                claim.has_contradiction != any(row.assessment.status == "contradicted" for row in effective) or
                claim.has_inconclusive != any(row.assessment.status == "inconclusive" for row in claim.assessments) or
                claim.coverage_status != ("partial" if effective else "not_evaluated")):
                raise ValueError("Inconsistent documentary synthesis coverage")
            local_ids = {row.id for row in claim.assessments}
            if any(len(set(item.assessment_ids)) != 2 or set(item.assessment_ids) - local_ids for item in claim.comparisons):
                raise ValueError("Unknown or duplicate assessment comparison reference")
            ids.extend(row.id for row in claim.assessments)
        ids.extend(row.id for row in self.unresolved_assessments)
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate consolidated assessment ID")
        if any(len(getattr(self.coverage, field)) != len(set(getattr(self.coverage, field)))
            for field in type(self.coverage).model_fields):
            raise ValueError("Duplicate documentary coverage claim ID")
        return self


class BoundaryCandidateOrigin(Contract):
    investigation_id: str
    candidate_id: str


class BoundaryInvestigationTurn(Contract):
    validation_feedback: ClassVar[dict[str, str]] = {
        "invalid_document_claim_assessment": "Assess each delivered claim at most once using its exact ID. Unknown, duplicate or unavailable documentary references cannot support an assessment. Missing claims remain inconclusive.",
        "claim_assessment_requires_source": "supported/contradicted require cited delivered source, exact inspected scope_paths and verified source provenance. Explain applicability, obligation, observed mechanism and exceptions; absence of edges is not proof.",
        "claim_evidence_not_in_conclusion": "Include each assessment's code_evidence_ids in the conclusion evidence_ids; documentary IDs are never technical evidence.",
        "candidate_document_claim_mismatch": "Candidate document_claim_ids must name contradicted assessments and cite their code evidence. Every contradicted claim grounding a finding_candidate must retain a candidate reference. Do not invent a finding: return inconclusive if support is insufficient.",
        "documentary_no_finding_requires_resolution": "no_finding requires a positive scoped explanation and resolved compatible/not_applicable assessments, not contradicted, missing or inconclusive claims. Otherwise return inconclusive.",
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
    subject_id: str = Field(description="conclusion, an existing candidate ID, or claim:<claim_id> for an existing assessment")
    field: Literal["components", "evidence_ids", "symbol_ids", "relationship_ids", "code_evidence_ids", "scope_paths", "document_claim_ids"]
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
    documentary_synthesis: DocumentarySynthesis | None = None
    next_phase: Literal["synthesis"] | None = None
    consumption_by_phase: dict[str, dict[str, int]] = Field(default_factory=dict)
    continuation_usage: dict[str, int] = Field(default_factory=dict,
        description="Previous execution usage, kept separate from this run's counters.")

    @model_validator(mode="after")
    def documentary_catalog_references(self):
        if self.documentary_synthesis is not None:
            catalog = getattr(self.plan, "document_claims", {})
            if set(self.documentary_synthesis.claims) - catalog.keys():
                raise ValueError("Consolidated documentary claim absent from plan catalog")
        return self

class ArchitectureBoundaryRequest(Contract):
    """Data-only input. Investigation instructions are owned by this agent."""

    model_config = ConfigDict(title="ArchitectureBoundaryRequest")
    documented_architecture: ArchitectureContextResult | None = None
    targets: list[str] = Field(default_factory=list, max_length=12,
        description="Initial repository paths, module names, file IDs or symbol IDs. Related endpoints may be included.")
    constraints: list[str] = Field(default_factory=list, max_length=40,
        description="Scope/access restrictions as data, not investigation objectives or prompt overrides.")
    continuation: BoundaryResult | None = Field(default=None,
        description="Prior structured result; never an external investigation prompt.")

    @model_validator(mode="after")
    def continuation_uses_internal_objective(self):
        if self.continuation is not None and self.continuation.objective != self.objective:
            raise ValueError("Continuation must use this agent's internal objective, not an external prompt.")
        return self

    # Read-only compatibility with the shared execution protocol. None of these
    # are request fields: external values are rejected, not silently discarded.
    @property
    def objective(self):
        return "Investigate dependencies that may contradict architectural boundaries inferred from code and structural relationships."

    @property
    def architectural_context(self):
        return ""

    @property
    def criteria(self):
        return [Criterion(id="architectural-boundaries", origin="design_principle",
            description="Investigate whether dependency directions and integration access paths respect boundaries supported by code declarations and structural relationships.",
            provenance="Auditor design heuristic, not a normative ISO rule or a documented project constraint.")]

    @property
    def follow_up(self):
        return []

    @property
    def follow_up_diagnostics(self):
        return []

from .config import BoundaryConfig

__all__ = ['AuditRequest', 'AuditResult', 'BaseAuditRequest', 'BoundaryClaimCheck', 'BoundaryConfig', 'BoundaryEvaluation', 'BoundaryFinding', 'BoundaryFindingReview', 'BoundaryReview', 'BoundarySupport', 'CandidateFinding', 'Contract', 'Criterion', 'Evaluation', 'EvidenceReference', 'Finding', 'FindingReview', 'Hypothesis', 'InvestigationPlan', 'Review']

BaseAuditRequest = AuditRequest
AuditRequest = ArchitectureBoundaryRequest
AuditResult = BoundaryResult
Finding = BoundaryFinding
