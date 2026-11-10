"""Canonical contracts for the reuse-parametrization investigator."""

from typing import Any, ClassVar, Literal

from pydantic import Field

from server.agents.architecture_context import ArchitectureContextResult
from server.contracts.audit import (
    AuditResult,
    CandidateFinding,
    Contract,
    Criterion,
    InvestigationPlan,
)
from server.services.document_indexing import IndexReference


class ParametrizationDocumentClaim(Contract):
    """Documentary provenance; never an entry in the code evidence ledger."""

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


class ParametrizationCandidate(Contract):
    """A bounded variation capability; never a violation or a finding."""

    id: str
    priority: Literal["high", "medium", "low"] = "medium"
    scope: list[str] = Field(min_length=1)
    primary_component: str = Field(min_length=1)
    symbol_id: str = ""
    symbol_name: str | None = None
    symbol_kind: str | None = None
    variation_mechanism: str = Field(min_length=1, max_length=120)
    alternatives: list[str] = Field(default_factory=list, max_length=6)
    documented_capability: str | None = None
    variation_basis: Literal["explicit", "inferred"] = "inferred"
    initial_locations: list[str] = Field(default_factory=list, max_length=10)
    observed_indicators: list[str] = Field(min_length=1)
    question: str = Field(min_length=1, max_length=2000)
    evidence_needed: list[str] = Field(min_length=1)
    document_claim_ids: list[str] = Field(default_factory=list)


class ParametrizationPlan(InvestigationPlan):
    limitations: list[str] = Field(default_factory=list)
    candidates: list[ParametrizationCandidate] = Field(default_factory=list)
    document_claims: dict[str, ParametrizationDocumentClaim] = Field(default_factory=dict)


class ParametrizationProposal(Contract):
    """One bounded variation point proposed semantically by the planner."""

    primary_component: str = Field(min_length=1, max_length=400)
    symbol_name: str | None = Field(default=None, max_length=120)
    variation_mechanism: str = Field(min_length=3, max_length=120)
    variation_basis: Literal["explicit", "inferred"] = "inferred"
    variation_status: Literal["documented", "planned", "unsupported"] = "documented"
    alternatives: list[str] = Field(default_factory=list, max_length=6)
    documented_capability: str = Field(min_length=10, max_length=500)
    question: str = Field(min_length=10, max_length=2000)
    evidence_needed: list[str] = Field(min_length=2, max_length=5)
    document_claim_ids: list[str] = Field(min_length=1, max_length=30)


class ParametrizationExclusion(Contract):
    """A plausible claim considered and rejected with a short reason."""

    claim_ids: list[str] = Field(min_length=1, max_length=30)
    reason: str = Field(min_length=10, max_length=500)


class ParametrizationPlanningResponse(Contract):
    """Semantic proposal from an LLM; host grounds and merges proposals."""

    validation_feedback: ClassVar[dict[str, str]] = {
        "planning_invalid_candidate": "Primary must be an indexed reference supplied to the model; symbol_name must be indexed in it.",
        "planning_unknown_claim": "document_claim_ids must be exact claim IDs supplied in this batch.",
        "planning_generic_variation": "Use a concrete variation, not a generic word such as configuration, behavior or options.",
        "planning_generic_alternatives": "Provide at least two distinct, concrete alternatives.",
        "planning_invalid_question": "Each question must name primary_component, its variation and one concrete alternative.",
        "planning_duplicate_candidate": "Combine proposals about the same component and variation instead of repeating them.",
    }
    candidates: list[ParametrizationProposal] = Field(default_factory=list, max_length=32)
    exclusions: list[ParametrizationExclusion] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=20)


class ConsolidationProposal(ParametrizationProposal):
    """A final consolidated capability derived from one or more proposals."""

    source_proposal_ids: list[str] = Field(min_length=1, max_length=32)


class ParametrizationConsolidationResponse(Contract):
    """Final semantic consolidation of existing provisional candidates by an LLM."""

    validation_feedback: ClassVar[dict[str, str]] = {
        "consolidation_invalid_candidate": "Return only candidates based on the supplied provisional proposals; do not invent new variation points.",
        "consolidation_unknown_claim": "document_claim_ids must be exact claim IDs supplied to the consolidator.",
        "consolidation_unverified_status": "Use only the proposal IDs supplied by the host.",
    }
    candidates: list[ConsolidationProposal] = Field(default_factory=list, max_length=32)
    exclusions: list[ParametrizationExclusion] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=20)


class ParametrizationToolQuery(Contract):
    tool: Literal["list_files", "find_symbols", "list_relationships", "get_source_excerpt",
        "search_repository_text", "get_evidence", "get_infrastructure"]
    arguments: dict = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=1000)
    scope_expansion: str = Field(
        default="", max_length=1000,
        description="Required only when path/file_path expands a source query beyond initial locations; state why it is required for this capability.",
    )


class ParametrizationClaimAssessment(Contract):
    claim_id: str = Field(min_length=1)
    status: Literal["supported", "contradicted", "not_applicable", "inconclusive"]
    rationale: str = Field(min_length=1, max_length=4000)
    code_evidence_ids: list[str] = Field(default_factory=list, max_length=80)
    scope_paths: list[str] = Field(default_factory=list, max_length=40)
    limitations: list[str] = Field(default_factory=list, max_length=20)


class ParametrizationEvidenceAssessment(Contract):
    """Source-backed answer to one plan obligation."""

    requirement_index: int = Field(ge=0)
    status: Literal["resolved", "not_applicable", "inconclusive"]
    rationale: str = Field(min_length=1, max_length=4000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=80)
    scope_paths: list[str] = Field(default_factory=list, max_length=40)


class ParametrizationInvestigationCandidate(CandidateFinding):
    symbol_ids: list[str] = Field(default_factory=list, max_length=80)
    relationship_ids: list[str] = Field(default_factory=list, max_length=80)
    document_claim_ids: list[str] = Field(default_factory=list)
    variation_mechanism: str = Field(min_length=1, max_length=120)
    selected_alternatives: list[str] = Field(min_length=1, max_length=6)
    implementations: list[str] = Field(default_factory=list, max_length=20)
    consumers: list[str] = Field(default_factory=list, max_length=20)


SelectionPhase = Literal["assembly", "startup", "runtime", "mixed", "unknown"]


class ParametrizationInvestigationResult(Contract):
    investigation_id: str = Field(min_length=1)
    status: Literal["finding_candidate", "no_finding", "inconclusive"]
    summary: str = Field(min_length=1, max_length=2000)
    justification: str = Field(min_length=1, max_length=4000)
    components: list[str] = Field(default_factory=list, max_length=40)
    symbol_ids: list[str] = Field(default_factory=list, max_length=80)
    relationship_ids: list[str] = Field(default_factory=list, max_length=80)
    evidence_ids: list[str] = Field(default_factory=list, max_length=80)
    candidates: list[ParametrizationInvestigationCandidate] = Field(default_factory=list, max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=40)
    claim_assessments: list[ParametrizationClaimAssessment] = Field(default_factory=list)
    evidence_assessments: list[ParametrizationEvidenceAssessment] = Field(default_factory=list)
    selection_phase: SelectionPhase = "unknown"
    selection_sites: list[str] = Field(default_factory=list, max_length=20)
    consumer_impact: Literal["not_required", "required", "not_verified"] = "not_verified"


class ParametrizationInvestigationTurn(Contract):
    validation_feedback: ClassVar[dict[str, str]] = {
        "evidence_requirements_unresolved": "Assess every evidence requirement exactly once by requirement_index. Definitive closures require a source-backed resolved or source-justified not_applicable assessment; otherwise request tools or close inconclusive.",
        "evidence_requirement_source_required": "Each resolved/not_applicable evidence assessment needs source evidence and scope_paths that are cited, delivered, and included in conclusion.components. Explain how those sources answer the obligation.",
        "no_finding_requires_reachable_scope": "A no_finding conclusion needs source evidence from an adjacent implementation or consumer when the plan supplied related locations; inspect them or close inconclusive.",
        "disabled_tool": "Use only enabled tools.",
        "tool_arguments_invalid": "Tool arguments are invalid: include every required argument for the chosen tool with the correct type; consult the tool schema in the supplied context.",
        "scope_expansion_reason_required": "Justify expanding beyond the supplied capability scope.",
        "invalid_queries_only": "No query survived scope and tool validation. Keep in-scope queries, or expand only when the query inspects required contract, implementation, consumer, test or selector source and scope_expansion states why it is needed.",
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
        "uninspected_component": "Components must be exact inspected file paths.",
        "uninspected_symbol": "Cite only symbols overlapping delivered source.",
        "invalid_document_claim_assessment": "Assess each delivered claim exactly once with its exact ID.",
        "claim_evidence_not_in_conclusion": "Assessment evidence must appear in conclusion evidence_ids.",
        "claim_assessment_requires_source": "supported/contradicted and code-backed assessments need cited source and scope_paths.",
        "claim_assessment_requires_uninspected_source": "Each scope_path must be a path delivered as source in this investigation; get_source_excerpt the missing paths or remove them from scope_paths.",
        "claim_evidence_not_specific": "Source evidence for a claim must come from the candidate variation frontier: the primary component or a supplied related location.",
        "candidate_document_claim_unassessed": "Referenced claims must all be assessed.",
        "candidate_document_claim_mismatch": "Candidate claims need matching claim assessments and relevant source evidence.",
        "finding_requires_variation_scope": "A parametrization finding needs source evidence from an adjacent implementation or consumer and selected alternatives verified in the inspected scope.",
        "selection_phase_unresolved": "Definitive closure must classify the current selection phase and cite the inspected source path(s) that establish it.",
        "selection_phase_uninspected": "Every selection_site must be delivered as source and listed in conclusion.components.",
        "consumer_impact_unresolved": "A parametrization finding must state whether current consumer code must change to select an alternative.",
        "documentary_no_finding_requires_resolution": "no_finding needs every claim resolved.",
        "no_finding_with_contradiction": "no_finding cannot contain contradicted assessments; use finding_candidate, inconclusive, or correct the assessment.",
        "coverage_incomplete": "finding/no_finding cannot close with an uncovered capability frontier: request tools or close inconclusive with the gap.",
    }
    action: Literal["tools", "close"]
    queries: list[ParametrizationToolQuery] = Field(default_factory=list, max_length=4)
    conclusion: ParametrizationInvestigationResult | None = None


class ReuseParametrizationDocDrivenRequest(Contract):
    """Coordinator input; architectural context is investigator-only context."""

    objective: str = Field(
        default="Investigate source-supported opportunities to parametrize reusable behavior.",
        min_length=1,
    )
    targets: list[str] = Field(default_factory=list, max_length=12)
    constraints: list[str] = Field(default_factory=list, max_length=40)
    documented_architecture: ArchitectureContextResult | None = None

    @property
    def architectural_context(self):
        # The architecture context is data, not an instruction or source evidence.
        return ""

    @property
    def criteria(self):
        return [Criterion(
            id="parametrized-reuse",
            origin="design_principle",
            description=(
                "Behavior shared by consumers should remain reusable through explicit parameters "
                "when its responsibility is stable, without erasing justified domain differences."
            ),
            provenance=(
                "Auditor design heuristic for maintainability; not a normative project constraint "
                "or an architecture-context claim."
            ),
        )]

    @property
    def follow_up(self):
        return []

    @property
    def follow_up_diagnostics(self):
        return []


class ReuseParametrizationDocDrivenResult(AuditResult):
    """Investigator result; synthesis and final findings are intentionally absent."""

    plan: ParametrizationPlan | InvestigationPlan | None
    investigation_results: list[ParametrizationInvestigationResult] = Field(default_factory=list)
    status: Literal["planning_only", "investigation_completed"] = "planning_only"
    planning_diagnostics: dict[str, Any] = Field(default_factory=dict)
