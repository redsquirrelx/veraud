"""Canonical contracts for the reuse-parametrization investigator."""

from typing import Any, ClassVar, Literal

from pydantic import Field

from server.agents.architecture_context import ArchitectureContextResult
from server.agents.architecture_context.schemas import KnowledgeClaim
from server.contracts.audit import (
    AuditResult,
    CandidateFinding,
    Contract,
    Criterion,
    InvestigationPlan,
)
from server.services.document_indexing import IndexReference


class DocumentClaimRecord(Contract):
    """Documentary provenance, never an entry in the code evidence ledger."""

    claim: KnowledgeClaim
    document_index: IndexReference | None
    section_paths: dict[str, str]
    status: Literal["applicable", "not_applicable", "uncertain", "unmapped"]
    reason: str = Field(min_length=1)
    scope_paths: list[str] = Field(default_factory=list)


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
    document_claims: dict[str, DocumentClaimRecord] = Field(default_factory=dict)


class ParametrizationPlanSelection(Contract):
    """The model ranks host-grounded opportunities, never inventing entities."""

    validation_feedback: ClassVar[dict[str, str]] = {
        "planning_size_limit": "Select at most budget.max_investigations candidate_ids.",
        "planning_unknown_candidate": "Select unique candidate_ids from the menu only.",
        "planning_invalid_question": "Each selected candidate needs a question naming its primary component.",
    }
    candidate_ids: list[str] = Field(max_length=32)
    questions: dict[str, str] = Field(default_factory=dict)


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
    exceptions_examined: list[str] = Field(default_factory=list, max_length=20)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    assessment_origin: Literal["investigator", "host_pending", "unknown"] = "unknown"


class ParametrizationEvidenceAssessment(Contract):
    """Source-backed answer to one plan obligation."""

    requirement_index: int = Field(ge=0)
    status: Literal["resolved", "not_applicable", "inconclusive"]
    rationale: str = Field(min_length=1, max_length=4000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=80)
    scope_paths: list[str] = Field(default_factory=list, max_length=40)
    exclusion_basis: Literal["not_code_dependent", "code_verified"] | None = Field(
        default=None,
        description="Required for not_applicable: code_verified needs cited source; not_code_dependent is only valid when the exclusion does not depend on inspecting code.",
    )


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
    claim_assessments: list[ParametrizationClaimAssessment] = Field(default_factory=list,
        description="Independent local assessments only; supported never establishes repository-wide compliance. Missing assessments are retained as inconclusive by the host.")
    evidence_assessments: list[ParametrizationEvidenceAssessment] = Field(default_factory=list)
    document_claim_delivery: dict[str, Literal["delivered", "unavailable", "not_delivered"]] = Field(default_factory=dict,
        description="Host-recorded prompt delivery, not applicability or evaluation. Absent entries in legacy results mean unknown.")
    selection_phase: SelectionPhase = "unknown"
    selection_sites: list[str] = Field(default_factory=list, max_length=20)
    consumer_impact: Literal["not_required", "required", "not_verified"] = "not_verified"


class ParametrizationInvestigationTurn(Contract):
    validation_feedback: ClassVar[dict[str, str]] = {
        "investigation_validation": "Correct every listed field/index and regenerate the complete investigation conclusion. Preserve valid evidence IDs and unchanged fields.",
        "evidence_requirements_unresolved": "Assess every evidence requirement exactly once by requirement_index. Definitive closures require a source-backed resolved or source-justified not_applicable assessment; otherwise request tools or close inconclusive.",
        "evidence_requirement_source_required": "Each resolved evidence assessment needs source evidence and scope_paths that are cited, delivered, and included in conclusion.components. code_verified not_applicable assessments need the same source traceability.",
        "evidence_requirement_exclusion_basis_required": "Set exclusion_basis for not_applicable: code_verified when source establishes the exclusion, not_code_dependent only when the exclusion does not require code inspection.",
        "evidence_requirement_explanation_required": "not_applicable needs a concrete rationale naming what makes the obligation inapplicable; a restatement or empty explanation is rejected.",
        "evidence_requirement_not_applicable_unjustified": "This obligation is code-dependent; not_code_dependent cannot exclude it. Cite inspected source or close inconclusive.",
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
        "finding_requires_variation_scope": "A parametrization finding needs inspected source for the primary component or for a cited implementation/consumer, plus selected alternatives verified in that scope.",
        "uninspected_variation_scope": "Every implementation or consumer named by a finding must be delivered as inspected source; inspect it or remove it from the finding.",
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
