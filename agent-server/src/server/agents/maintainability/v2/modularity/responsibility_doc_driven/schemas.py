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


class ResponsibilityResult(AuditResult):
    plan: ResponsibilityPlan | InvestigationPlan | None
    findings: list[ResponsibilityFinding]
    investigation_results: list["ResponsibilityInvestigationResult"] = Field(default_factory=list)
    candidates: list["ResponsibilityInvestigationCandidate"] = Field(default_factory=list)
    candidate_origins: dict[str, list[dict]] = Field(default_factory=dict)
    documentary_synthesis: dict = Field(default_factory=dict)


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
    limitations: list[str] = Field(default_factory=list, max_length=20)


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
    claim_assessments: list[ResponsibilityClaimAssessment] = Field(default_factory=list)


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
        "candidate_document_claim_mismatch": "Cited claims need independent change reasons.",
        "finding_requires_distinct_responsibilities": "finding_candidate needs at least two distinct observed responsibilities.",
        "documentary_no_finding_requires_resolution": "no_finding needs every claim resolved.",
        "no_finding_with_contradiction": "no_finding cannot contain contradicted claim assessments; use finding_candidate, inconclusive or correct the assessment.",
        "coverage_incomplete": "Finding/no_finding cannot close with uncovered symbols, tails or relationships: request tools or close inconclusive with the gap.",
    }
    action: Literal["tools", "close"]
    queries: list[ResponsibilityToolQuery] = Field(default_factory=list, max_length=4)
    conclusion: ResponsibilityInvestigationResult | None = None


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

__all__ = ['AuditRequest', 'AuditResult', 'Criterion', 'DocumentClaimRecord',
    'ResponsibilityCandidate', 'ResponsibilityClaimAssessment', 'ResponsibilityConfig', 'ResponsibilityFinding', 'ResponsibilityInvestigationCandidate',
    'ResponsibilityInvestigationResult', 'ResponsibilityInvestigationTurn', 'ResponsibilityPlan',
    'ResponsibilityPlanSelection', 'ResponsibilityRequest', 'ResponsibilityResult', 'ResponsibilityToolQuery']

AuditRequest = ResponsibilityRequest
Finding = ResponsibilityFinding
ResponsibilityResult.model_rebuild()
