"""Canonical contracts for the responsibility investigator."""

from typing import ClassVar, Literal

from pydantic import ConfigDict, Field, model_validator

from server.agents.architecture_context.schemas import (
    ArchitectureContextResult,
    KnowledgeClaim,
)
from server.contracts.audit import (
    AuditResult,
    CandidateFinding,
    Contract,
    Criterion,
    Finding,
    InvestigationPlan,
)
from server.services.document_indexing import IndexReference


class ResponsibilityFinding(Finding):
    """Consolidated provisional candidate; documentary IDs are never evidence IDs."""

    document_claim_ids: list[str] = Field(default_factory=list)


class DocumentClaimRecord(Contract):
    """Documentary provenance, never an entry in the code evidence ledger."""

    claim: KnowledgeClaim
    document_index: IndexReference | None
    section_paths: dict[str, str]
    status: Literal["applicable", "not_applicable", "uncertain", "unmapped"]
    reason: str = Field(min_length=1)
    scope_paths: list[str] = Field(default_factory=list)


class ResponsibilityCandidate(Contract):
    """A bounded cohesion question; never a violation or a finding."""

    id: str
    priority: Literal["high", "medium", "low"] = "medium"
    scope: list[str] = Field(min_length=1)
    primary_component: str = ""
    collaborators: list[str] = Field(default_factory=list)
    documented_responsibility: str | None = None
    observed_indicators: list[str] = Field(min_length=1)
    question: str = Field(min_length=1)
    evidence_needed: list[str] = Field(min_length=1)
    document_claim_ids: list[str] = Field(default_factory=list)


class ResponsibilityPlan(InvestigationPlan):
    limitations: list[str] = Field(default_factory=list)
    candidates: list[ResponsibilityCandidate] = Field(default_factory=list)
    document_claims: dict[str, DocumentClaimRecord] = Field(default_factory=dict)


class ResponsibilityPlanSelection(Contract):
    """The model ranks host-grounded opportunities, never inventing entities."""

    validation_feedback: ClassVar[dict[str, str]] = {
        "planning_size_limit": "Select at most budget.max_investigations candidate_ids.",
        "planning_unknown_candidate": "Select unique candidate_ids from the menu only.",
        "planning_invalid_question": "Each selected candidate needs a question naming its primary component.",
    }
    candidate_ids: list[str] = Field(max_length=32)
    questions: dict[str, str] = Field(default_factory=dict)


class ResponsibilityToolQuery(Contract):
    tool: Literal["list_files", "find_symbols", "list_relationships", "get_source_excerpt",
        "search_repository_text", "get_evidence", "get_infrastructure"]
    arguments: dict = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=1000)
    scope_expansion: str = Field(default="", max_length=1000)


class ResponsibilityClaimAssessment(Contract):
    claim_id: str
    status: Literal["supported", "contradicted", "not_applicable", "inconclusive"]
    rationale: str = Field(min_length=1, max_length=4000)
    code_evidence_ids: list[str] = Field(default_factory=list, max_length=80)
    scope_paths: list[str] = Field(default_factory=list, max_length=40)
    exceptions_examined: list[str] = Field(default_factory=list, max_length=20)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    assessment_origin: Literal["investigator", "host_pending", "unknown"] = "unknown"


class ResponsibilityInvestigationCandidate(CandidateFinding):
    symbol_ids: list[str] = Field(default_factory=list, max_length=80)
    relationship_ids: list[str] = Field(default_factory=list, max_length=80)
    document_claim_ids: list[str] = Field(default_factory=list)
    observed_responsibilities: list[str] = Field(min_length=1, max_length=20)
    independent_change_reasons: list[str] = Field(min_length=1, max_length=20)


class ResponsibilityInvestigationResult(Contract):
    investigation_id: str
    status: Literal["finding_candidate", "no_finding", "inconclusive"]
    summary: str = Field(min_length=1, max_length=2000)
    justification: str = Field(min_length=1, max_length=4000)
    components: list[str] = Field(default_factory=list, max_length=40)
    symbol_ids: list[str] = Field(default_factory=list, max_length=80)
    relationship_ids: list[str] = Field(default_factory=list, max_length=80)
    evidence_ids: list[str] = Field(default_factory=list, max_length=80)
    candidates: list[ResponsibilityInvestigationCandidate] = Field(default_factory=list, max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=40)
    claim_assessments: list[ResponsibilityClaimAssessment] = Field(default_factory=list,
        description="Independent local assessments only; supported never establishes repository-wide compliance. Missing assessments are retained as inconclusive by the host.")
    document_claim_delivery: dict[str, Literal["delivered", "unavailable", "not_delivered"]] = Field(default_factory=dict,
        description="Host-recorded prompt delivery, not applicability or evaluation. Absent entries in legacy results mean unknown.")


class ResponsibilityInvestigationTurn(Contract):
    validation_feedback: ClassVar[dict[str, str]] = {
        "disabled_tool": "Use only enabled tools.",
        "scope_expansion_reason_required": "Justify expanding beyond the primary component.",
        "tools_requires_queries_without_conclusion": "action=tools needs queries and no conclusion.",
        "close_requires_current_investigation_conclusion": "action=close needs current investigation_id.",
        "candidate_status_mismatch": "finding_candidate needs candidates; no_finding/inconclusive need none.",
        "inconclusive_requires_limitations": "inconclusive needs concrete limitations.",
        "conclusion_requires_inspected_primary_component": "no_finding must include the primary component.",
        "unknown_or_undelivered_evidence": "Cite only delivered evidence IDs.",
        "unexamined_relationship": "Cite only examined relationship IDs.",
        "candidate_evidence_not_in_conclusion": "Include every candidate citation in conclusion evidence_ids.",
        "conclusion_requires_inspected_source_and_components": "finding/no_finding need source evidence and components.",
        "unverified_source_provenance": "Do not cite unverified source provenance.",
        "uninspected_component": "Components must be exact inspected FILE paths.",
        "uninspected_symbol": "Cite only symbols overlapping delivered source.",
        "invalid_document_claim_assessment": "Assess each delivered claim once with its exact ID.",
        "claim_evidence_not_in_conclusion": "Assessment evidence must appear in conclusion evidence_ids.",
        "claim_assessment_requires_source": "supported/contradicted need cited source and scope_paths.",
        "claim_assessment_requires_uninspected_source": "scope_paths must be inspected source paths.",
        "candidate_document_claim_unassessed": "Referenced claims must be assessed.",
        "candidate_document_claim_mismatch": "Cited claims need contradicted assessments, cited code evidence and independent change reasons.",
        "finding_requires_distinct_responsibilities": "finding_candidate needs at least two distinct observed responsibilities.",
        "documentary_no_finding_requires_resolution": "no_finding needs every claim resolved.",
        "no_finding_with_contradiction": "no_finding cannot contain contradicted claim assessments; use finding_candidate, inconclusive or correct the assessment.",
        "coverage_incomplete": "Finding/no_finding cannot close with uncovered symbols, tails or relationships: request tools or close inconclusive with the gap.",
    }
    action: Literal["tools", "close"]
    queries: list[ResponsibilityToolQuery] = Field(default_factory=list, max_length=4)
    conclusion: ResponsibilityInvestigationResult | None = None


class LocalClaimAssessment(Contract):
    id: str
    investigation_id: str
    assessment: ResponsibilityClaimAssessment
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


class ResponsibilityResult(AuditResult):
    plan: ResponsibilityPlan | InvestigationPlan | None
    findings: list[ResponsibilityFinding]
    investigation_results: list["ResponsibilityInvestigationResult"] = Field(default_factory=list)
    candidates: list["ResponsibilityInvestigationCandidate"] = Field(default_factory=list)
    candidate_origins: dict[str, list[dict]] = Field(default_factory=dict)
    documentary_synthesis: DocumentarySynthesis | None = None

    @model_validator(mode="after")
    def documentary_catalog_references(self):
        if self.documentary_synthesis is not None:
            catalog = getattr(self.plan, "document_claims", {})
            if set(self.documentary_synthesis.claims) - catalog.keys():
                raise ValueError("Consolidated documentary claim absent from plan catalog")
        return self


class ResponsibilityRequest(Contract):
    """Data-only input. Investigation instructions are owned by this agent."""

    model_config = ConfigDict(title="ResponsibilityRequest")
    documented_architecture: ArchitectureContextResult | None = None
    targets: list[str] = Field(default_factory=list, max_length=12)
    constraints: list[str] = Field(default_factory=list, max_length=40)
    continuation: ResponsibilityResult | None = None

    @model_validator(mode="after")
    def continuation_uses_internal_objective(self):
        if self.continuation is not None and self.continuation.objective != self.objective:
            raise ValueError("Continuation must use this agent's internal objective, not an external prompt.")
        return self

    @property
    def objective(self):
        return "Investigate whether classes and components hold single responsibilities supported by source evidence."

    @property
    def architectural_context(self):
        return ""

    @property
    def criteria(self):
        return [Criterion(id="single-responsibility", origin="design_principle",
            description="Each class and component should own one cohesive responsibility aligned with its reason to change.",
            provenance="Auditor design heuristic, not a normative ISO rule or a documented project constraint.")]

    @property
    def follow_up(self):
        return []

    @property
    def follow_up_diagnostics(self):
        return []


from .config import ResponsibilityConfig

__all__ = [
    'AuditRequest',
    'AuditResult',
    'ClaimAssessmentComparison',
    'ConsolidatedClaimAssessments',
    'Criterion',
    'DocumentClaimRecord',
    'DocumentarySynthesis',
    'DocumentarySynthesisCoverage',
    'DocumentarySynthesisIssue',
    'LocalClaimAssessment',
    'ResponsibilityCandidate',
    'ResponsibilityClaimAssessment',
    'ResponsibilityConfig',
    'ResponsibilityFinding',
    'ResponsibilityInvestigationCandidate',
    'ResponsibilityInvestigationResult',
    'ResponsibilityInvestigationTurn',
    'ResponsibilityPlan',
    'ResponsibilityPlanSelection',
    'ResponsibilityRequest',
    'ResponsibilityResult',
    'ResponsibilityToolQuery',
]

AuditRequest = ResponsibilityRequest
Finding = ResponsibilityFinding
ResponsibilityResult.model_rebuild()
