"""Contracts for the abstraction investigator."""

from typing import Any, ClassVar, Literal

from pydantic import Field

from server.agents.architecture_context.schemas import ArchitectureContextResult
from server.contracts.audit import (
    AuditResult,
    CandidateFinding,
    Contract,
    Criterion,
    Finding,
    InvestigationPlan,
)
from server.services.document_indexing import IndexReference


class AbstractionDocumentClaim(Contract):
    """Positional documentary ID; normalized context revision, not a global hash."""

    id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    related_subjects: list[str] = Field(default_factory=list)
    certainty: str | None = None
    constraint: str = "unspecified"
    section_ids: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    document_index: IndexReference | None = None
    section_paths: dict[str, str] = Field(default_factory=dict)


class AbstractionCandidate(Contract):
    """A bounded abstraction-purpose question; never a violation or a finding."""

    id: str
    priority: Literal["high", "medium", "low"] = "medium"
    scope: list[str] = Field(min_length=1)
    primary_component: str = Field(min_length=1)
    abstraction_name: str = Field(min_length=1)
    abstraction_kind: Literal["interface", "protocol", "abstract_class", "documented_helper", "type_alias"]
    related_components: list[str] = Field(default_factory=list)
    documented_purpose: str | None = None
    purpose_basis: Literal["explicit", "inferred", "unknown"] = "unknown"
    observed_indicators: list[str] = Field(min_length=1)
    question: str = Field(min_length=1)
    evidence_needed: list[str] = Field(min_length=1)
    document_claim_ids: list[str] = Field(default_factory=list)


class AbstractionPlan(InvestigationPlan):
    limitations: list[str] = Field(default_factory=list)
    candidates: list[AbstractionCandidate] = Field(default_factory=list)
    document_claims: dict[str, AbstractionDocumentClaim] = Field(default_factory=dict)


class AbstractionPlanSelection(Contract):
    """The model ranks host-grounded opportunities, never inventing entities."""

    validation_feedback: ClassVar[dict[str, str]] = {
        "planning_size_limit": "Select at most budget.max_investigations candidate_ids.",
        "planning_unknown_candidate": "Select unique candidate_ids from the menu only.",
        "planning_invalid_question": "Each selected candidate needs a question naming its primary component.",
        "planning_requirements_unknown_candidate": "Obligation requirements can only attach to selected candidate_ids.",
        "planning_requirements_invalid": "Requirements: 12-400 chars, unique per candidate, 2-5 each, anchored; one obligation per requirement.",
        "planning_requirements_compound": "Each requirement checks one obligation on one object. Do not bundle multiple claim_ids, or more than one related component, into a single requirement.",
    }
    candidate_ids: list[str] = Field(max_length=32)
    questions: dict[str, str] = Field(default_factory=dict)
    evidence_requirements: dict[str, list[str]] = Field(default_factory=dict, max_length=32)


class AbstractionToolQuery(Contract):
    tool: Literal["list_files", "find_symbols", "list_relationships", "get_source_excerpt",
        "search_repository_text", "get_evidence", "get_infrastructure"]
    arguments: dict = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=1000)
    scope_expansion: str = Field(default="", max_length=1000)


class AbstractionClaimAssessment(Contract):
    claim_id: str = Field(min_length=1)
    status: Literal["supported", "contradicted", "not_applicable", "inconclusive"]
    rationale: str = Field(min_length=1, max_length=4000)
    code_evidence_ids: list[str] = Field(default_factory=list, max_length=80)
    scope_paths: list[str] = Field(default_factory=list, max_length=40)
    limitations: list[str] = Field(default_factory=list, max_length=20)


class AbstractionInvestigationCandidate(CandidateFinding):
    symbol_ids: list[str] = Field(default_factory=list, max_length=80)
    relationship_ids: list[str] = Field(default_factory=list, max_length=80)
    document_claim_ids: list[str] = Field(default_factory=list)
    guarantees: list[str] = Field(min_length=1, max_length=6)
    implementers: list[str] = Field(default_factory=list, max_length=20)
    consumers: list[str] = Field(default_factory=list, max_length=20)


class AbstractionEvidenceAssessment(Contract):
    """Source-backed answer to one host-supplied evidence requirement."""

    requirement_index: int = Field(ge=0)
    status: Literal["resolved", "not_applicable", "inconclusive"]
    rationale: str = Field(min_length=1, max_length=4000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=80)
    scope_paths: list[str] = Field(default_factory=list, max_length=40)


class AbstractionInvestigationResult(Contract):
    investigation_id: str = Field(min_length=1)
    status: Literal["finding_candidate", "no_finding", "inconclusive"]
    summary: str = Field(min_length=1, max_length=2000)
    justification: str = Field(min_length=1, max_length=4000)
    components: list[str] = Field(default_factory=list, max_length=40)
    symbol_ids: list[str] = Field(default_factory=list, max_length=80)
    relationship_ids: list[str] = Field(default_factory=list, max_length=80)
    evidence_ids: list[str] = Field(default_factory=list, max_length=80)
    candidates: list[AbstractionInvestigationCandidate] = Field(default_factory=list, max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=40)
    claim_assessments: list[AbstractionClaimAssessment] = Field(default_factory=list)
    evidence_assessments: list[AbstractionEvidenceAssessment] = Field(default_factory=list)


class AbstractionInvestigationTurn(Contract):
    validation_feedback: ClassVar[dict[str, str]] = {
        "evidence_requirements_unresolved": "Assess every evidence requirement exactly once by requirement_index. Definitive closures require resolved or source-justified not_applicable assessments; otherwise request tools or close inconclusive.",
        "evidence_requirement_source_required": "Each resolved/not_applicable evidence assessment needs source IDs and scope_paths covered by those citations and included in conclusion.components. Explain how they answer the question, not just what files exist.",
        "substitution_assessment_requires_implementer_or_consumer_scope": "Substitution-related requirements need implementer or consumer source evidence, not the primary component alone.",
        "no_finding_guarantee_requires_reachable_scope": "no_finding with an architectural guarantee needs evidence from an implementer or consumer for every guarantee-related requirement. Reach it with tools or close inconclusive.",
        "documentary_claims_unresolved": "no_finding cannot close with inconclusive documentary claims. Obtain the missing evidence or close inconclusive.",
        "disabled_tool": "Use only enabled tools.",
        "tool_arguments_invalid": "Tool arguments are invalid: include every required argument for the chosen tool with the correct type; consult the tool schema in the supplied context.",
        "scope_expansion_reason_required": "Justify expanding beyond the implementation.",
        "tools_requires_queries_without_conclusion": "action=tools needs queries and no conclusion.",
        "close_requires_current_investigation_conclusion": "action=close needs current investigation_id.",
        "candidate_status_mismatch": "finding_candidate needs candidates; no_finding/inconclusive need none.",
        "inconclusive_requires_limitations": "inconclusive needs concrete limitations.",
        "conclusion_requires_inspected_primary_component": "no_finding must include the primary component.",
        "unknown_or_undelivered_evidence": "Cite only delivered evidence IDs.",
        "unexamined_relationship": "Cite only examined relationship IDs.",
        "candidate_evidence_not_in_conclusion": "Include every citation used by a candidate.",
        "conclusion_requires_inspected_source_and_components": "finding/no_finding need source evidence and components.",
        "unverified_source_provenance": "Do not cite unverified source provenance.",
        "uninspected_component": "Components must be exact inspected FILE paths.",
        "uninspected_symbol": "Cite only symbols overlapping delivered source.",
        "invalid_document_claim_assessment": "Assess each delivered claim once with its exact ID.",
        "claim_evidence_not_in_conclusion": "Claim assessment evidence must appear in conclusion.",
        "claim_assessment_requires_source": "supported/contradicted and code-backed not_applicable assessments need cited source and scope_paths.",
        "claim_exclusion_requires_rationale": "Explain why the documentary claim is outside the architectural question; exclusion is not evidence of compliance.",
        "claim_assessment_requires_uninspected_source": "Each scope_path must be a path delivered via get_source_excerpt in this investigation; get_source_excerpt the missing paths or remove them from scope_paths.",
        "claim_evidence_not_specific": "Source evidence for a claim must come from the abstraction's files: the primary component or its indexed related files (implementers/consumers).",
        "candidate_document_claim_unassessed": "Referenced claims must all be assessed.",
        "candidate_document_claim_mismatch": "Candidate claims need matching in-candidate evidence.",
        "finding_requires_implementer_or_consumer": "finding needs at least one implementer or consumer inspected.",
        "documentary_no_finding_requires_resolution": "no_finding needs every claim resolved.",
        "no_finding_with_contradiction": "no_finding cannot contain contradicted claim assessments; use finding_candidate, inconclusive or correct the assessment.",
        "coverage_incomplete": "Finding/no_finding cannot close with uncovered symbols, tails or relationships: request tools or close inconclusive with the gap.",
    }
    action: Literal["tools", "close"]
    queries: list[AbstractionToolQuery] = Field(default_factory=list, max_length=4)
    conclusion: AbstractionInvestigationResult | None = None


class AbstractionFinding(Finding):
    """Consolidated provisional candidate; documentary IDs are never evidence IDs."""

    document_claim_ids: list[str] = Field(default_factory=list)


class AbstractionRequest(Contract):
    """Structured scope/document input; investigation instructions remain internal."""

    documented_architecture: ArchitectureContextResult | None = None
    targets: list[str] = Field(default_factory=list, max_length=12)
    constraints: list[str] = Field(default_factory=list, max_length=40)
    continuation: Any = None

    @property
    def objective(self):
        return "Investigate whether implemented abstractions deliver their documented or inferable architectural purposes."

    @property
    def architectural_context(self):
        return ""

    @property
    def criteria(self):
        return [Criterion(id="abstraction-purpose", origin="design_principle",
            description="An abstraction should deliver the purpose — independence, substitutability, encapsulation, "
                "extensibility or reuse — supported by its contract and its implementations and consumers.",
            provenance="Auditor design heuristic, not a normative ISO rule or a documented project constraint.")]

    @property
    def follow_up(self):
        return []

    @property
    def follow_up_diagnostics(self):
        return []


class AbstractionResult(AuditResult):
    plan: AbstractionPlan | InvestigationPlan | None
    findings: list[AbstractionFinding] = Field(default_factory=list)
    investigation_results: list[AbstractionInvestigationResult] = Field(default_factory=list)
    candidates: list[AbstractionInvestigationCandidate] = Field(default_factory=list)
    candidate_origins: dict[str, list[dict]] = Field(default_factory=dict)
    documentary_synthesis: dict = Field(default_factory=dict)
    synthesis: dict[str, Any] = Field(default_factory=dict)
