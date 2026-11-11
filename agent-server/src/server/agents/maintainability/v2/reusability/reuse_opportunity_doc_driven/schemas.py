"""Native contracts for the reuse-opportunity investigator shell."""

from typing import Any, ClassVar, Literal

from pydantic import Field

from server.agents.architecture_context import ArchitectureContextResult
from server.contracts.audit import (
    AuditResult,
    CandidateFinding,
    Contract,
    Criterion,
    Hypothesis,
    InvestigationPlan,
)


class ReuseInvestigationProposal(Contract):
    capability: str = Field(min_length=1, max_length=500)
    question: str = Field(min_length=1, max_length=2000)
    document_claim_ids: list[str] = Field(min_length=1, max_length=20)
    initial_targets: list[str] = Field(default_factory=list, max_length=20,
        description="Repository-relative indexed files or directories containing indexed files; optional exploration hints, not investigation boundaries. Leave empty if localization is unknown.")
    objectives: list[str] = Field(min_length=1, max_length=12)
    reuse_criteria: list[str] = Field(min_length=1, max_length=12)
    independent_implementation_criteria: list[str] = Field(min_length=1, max_length=12)
    priority: Literal["high", "medium", "low"] = "medium"
    rationale: str = Field(min_length=1, max_length=2000)
    documented_reuse_expectation: str = Field(min_length=1, max_length=2000,
        description="Concrete reuse expectation supported by the supplied original claims, not a proposed architectural rule.")
    providers: list[str] = Field(default_factory=list, max_length=20,
        description="Documented providers; empty when unknown, never invented from layer conventions.")
    consumers: list[str] = Field(default_factory=list, max_length=20,
        description="Documented consumers; empty when unknown.")
    implementation_uncertainty: str = Field(min_length=1, max_length=2000,
        description="Uncertainty about actual implementations or consumption that requires later source inspection.")


class ReusePlanningResponse(Contract):
    validation_feedback: ClassVar[dict[str, str]] = {
        "planning_unknown_document_claim": (
            "Cite only claim IDs from the current architecture_context.claims portion. "
            "Remove references to claims not supplied in this portion."
        ),
        "planning_unknown_target": (
            "initial_targets accepts repository-relative indexed files or directories containing indexed files. "
            "Remove nonexistent paths; use [] if localization is unknown. Targets are navigation hints only."
        ),
        "planning_insufficient_evidence_conflict": (
            "Return no investigations when insufficient_architectural_evidence is true."
        ),
        "planning_duplicate_investigation": (
            "Merge investigations about the same capability supported by the same claims."
        ),
        "planning_unknown_capability": "Use only capability IDs supplied in this phase; account for each exactly once.",
        "planning_incomplete_correlation": (
            "Every supplied capability ID must occur exactly once in a group or in excluded_capabilities with a reason."
        ),
    }

    investigations: list[ReuseInvestigationProposal] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=30)
    insufficient_architectural_evidence: bool = False


class ReuseToolQuery(Contract):
    tool: Literal["list_files", "find_symbols", "list_relationships", "get_source_excerpt",
        "search_repository_text", "get_evidence", "get_infrastructure"]
    arguments: dict = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=1000)
    scope_expansion: str = Field(default="", max_length=1000)


class ReuseClaimAssessment(Contract):
    claim_id: str = Field(min_length=1)
    status: Literal["supported", "contradicted", "not_applicable", "inconclusive"]
    rationale: str = Field(min_length=1, max_length=4000)
    code_evidence_ids: list[str] = Field(default_factory=list, max_length=80)
    scope_paths: list[str] = Field(default_factory=list, max_length=40)
    limitations: list[str] = Field(default_factory=list, max_length=20)


class ReuseOpportunityCandidate(CandidateFinding):
    symbol_ids: list[str] = Field(default_factory=list, max_length=80)
    relationship_ids: list[str] = Field(default_factory=list, max_length=80)
    document_claim_ids: list[str] = Field(default_factory=list, max_length=20)
    shared_component: str = Field(min_length=1, max_length=500)
    independent_implementations: list[str] = Field(min_length=1, max_length=20)
    shared_behavior: str = Field(min_length=1, max_length=2000)
    independent_behavior: str = Field(min_length=1, max_length=2000)
    behavior_comparison: str = Field(min_length=1, max_length=4000)
    shared_symbol_ids: list[str] = Field(min_length=1, max_length=20)
    independent_symbol_ids: list[str] = Field(min_length=1, max_length=20)
    reuse_hypothesis: Literal["functional_duplication", "underused_reuse", "incomplete_centralization"]


class ReuseFunctionalComparison(Contract):
    """Source-backed semantic assessment, never inferred from an import alone."""

    shared_symbol_id: str
    other_symbol_id: str
    other_role: Literal["consumer", "independent_implementation"]
    outcome: Literal["equivalent_shareable", "correct_reuse", "justified_independence", "insufficient"]
    shared_evidence_ids: list[str] = Field(min_length=1, max_length=20)
    other_evidence_ids: list[str] = Field(min_length=1, max_length=20)
    responsibility: str = Field(min_length=1, max_length=1000)
    inputs_outputs: str = Field(min_length=1, max_length=1000)
    effects: str = Field(min_length=1, max_length=1000)
    rules_and_errors: str = Field(min_length=1, max_length=1000)
    architectural_constraints: str = Field(min_length=1, max_length=1500)
    rationale: str = Field(min_length=1, max_length=1500)


class ReuseInvestigationResult(Contract):
    investigation_id: str = Field(min_length=1)
    status: Literal["reuse_opportunity", "no_reuse_opportunity", "inconclusive"]
    summary: str = Field(min_length=1, max_length=2000)
    justification: str = Field(min_length=1, max_length=4000)
    components: list[str] = Field(default_factory=list, max_length=40)
    symbol_ids: list[str] = Field(default_factory=list, max_length=80)
    relationship_ids: list[str] = Field(default_factory=list, max_length=80)
    evidence_ids: list[str] = Field(default_factory=list, max_length=80)
    candidates: list[ReuseOpportunityCandidate] = Field(default_factory=list, max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=40)
    claim_assessments: list[ReuseClaimAssessment] = Field(default_factory=list, max_length=20)
    comparisons: list[ReuseFunctionalComparison] = Field(default_factory=list, max_length=40)
    scope: Literal["inspected", "repository"] = Field(default="inspected",
        description="Conclusions apply only to inspected evidence. Repository-wide claims are not admissible from samples.")
    inspected_scope: list[str] = Field(default_factory=list, max_length=40)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class ReuseInvestigationTurn(Contract):
    validation_feedback: ClassVar[dict[str, str]] = {
        "tools_requires_queries_without_conclusion": "action=tools needs queries and no conclusion.",
        "close_requires_current_investigation_conclusion": "action=close needs the current investigation_id.",
        "disabled_tool": "Use only enabled repository tools.",
        "tool_arguments_invalid": "Tool arguments are invalid: include every required argument with the correct type.",
        "scope_expansion_reason_required": "Explain why source outside the supplied targets must be inspected.",
        "candidate_status_mismatch": "Use reuse_opportunity only with at least one grounded candidate; use no_reuse_opportunity/inconclusive with no candidates.",
        "candidate_component_uninspected": "Candidate components must be inspected indexed files; no directories, uninspected paths, or components missing from conclusion.",
        "candidate_independent_implementation": "independent_implementations must name inspected exact paths or path#symbol entries resolving to indexed symbols; retain candidates in candidate.components and cite their source ranges.",
        "candidate_independent_implementation_source_required": "Each implementation needs candidate evidence whose source range covers that implementation; compare distinct symbols for behavior.",
        "candidate_symbol_mismatch": "shared_symbol_ids and independent_symbol_ids must be actual, disjoint source symbols delivered to the investigation.",
        "candidate_shared_component": "shared_component must be an inspected indexed source file.",
        "candidate_duplicate_implementation": "independent_implementations and components must be unique and include distinct inspected alternatives.",
        "unknown_or_undelivered_evidence": "Cite only evidence delivered by tools in this investigation.",
        "conclusion_requires_inspected_source": "A non-inconclusive conclusion needs source evidence and inspected components.",
        "uninspected_component": "Every component in the conclusion or candidates must have delivered source evidence.",
        "claim_evidence_not_in_conclusion": "Claim assessment evidence must belong to conclusion evidence.",
        "claim_assessment_requires_source": "Assessments with code evidence need source citations and scope_paths covered by them.",
        "candidate_document_claim_unassessed": "Candidates may cite only claims assessed in this investigation.",
        "duplicate_claim_assessment": "Assess each cited claim once.",
        "unexamined_relationship": "Cite only relationships returned by list_relationships.",
        "uninspected_symbol": "Cite only symbols in files delivered as source and overlapping the cited range.",
        "comparison_invalid": "Compare distinct actual symbols using source IDs delivered in this investigation. A consumer reusing a provider is not an independent implementation.",
        "coverage_incomplete": "Evidence is insufficient; request focused tools rather than regenerate the same conclusion.",
        "scope_not_supported": "Limit the conclusion to inspected_scope. Do not infer repository-wide absence or universal adoption from samples.",
        "inconclusive_requires_reason": "Explain the unresolved gap or operational blocker in limitations.",
    }

    action: Literal["tools", "close"]
    queries: list[ReuseToolQuery] = Field(default_factory=list, max_length=4)
    conclusion: ReuseInvestigationResult | None = None
    comparisons: list[ReuseFunctionalComparison] = Field(default_factory=list, max_length=20)
    read_document_claim_ids: list[str] = Field(default_factory=list, max_length=20,
        description="Retrieve original documentary claims from this task when their compact projection is insufficient.")


class ReuseCapability(Contract):
    """A provisional documentary capability, not an investigation or code observation."""

    capability: str = Field(min_length=1, max_length=500)
    documented_reuse_expectation: str = Field(min_length=1, max_length=2000)
    document_claim_ids: list[str] = Field(min_length=1, max_length=20)
    providers: list[str] = Field(default_factory=list, max_length=20)
    consumers: list[str] = Field(default_factory=list, max_length=20)
    uncertainty: str = Field(min_length=1, max_length=2000)


class ReuseDiscoveryResponse(Contract):
    validation_feedback: ClassVar = ReusePlanningResponse.validation_feedback
    capabilities: list[ReuseCapability] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=30)


class ReuseCapabilityGroup(Contract):
    capability: str = Field(min_length=1, max_length=500)
    capability_ids: list[str] = Field(min_length=1, max_length=100)
    additional_document_claim_ids: list[str] = Field(default_factory=list, max_length=40,
        description="Complementary claim IDs from the global locator catalog to read in full before formulation.")
    rationale: str = Field(min_length=1, max_length=2000,
        description="Must name the common functional capability and shared reuse intention; those two facts are required for merging.")


class ReuseCorrelationResponse(Contract):
    validation_feedback: ClassVar = ReusePlanningResponse.validation_feedback
    groups: list[ReuseCapabilityGroup] = Field(default_factory=list, max_length=24)
    excluded_capabilities: dict[str, str] = Field(default_factory=dict,
        description="Capability IDs not carried forward, each with an explicit reason.")
    limitations: list[str] = Field(default_factory=list, max_length=30)


class ReuseInvestigation(ReuseInvestigationProposal):
    id: str


class ReuseOpportunityPlan(InvestigationPlan):
    investigations: list[ReuseInvestigation] = Field(default_factory=list)
    document_claims: dict[str, dict[str, Any]] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    planning_diagnostics: dict[str, Any] = Field(default_factory=dict)


class ReuseOpportunityDocDrivenRequest(Contract):
    """Coordinator input; architectural context is investigator-only context."""

    objective: str = Field(
        default="Investigate source-supported opportunities for reusable behavior.",
        min_length=1,
    )
    targets: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    documented_architecture: ArchitectureContextResult | None = None

    @property
    def architectural_context(self):
        return ""

    @property
    def criteria(self):
        return [Criterion(
            id="reuse-opportunity",
            origin="design_principle",
            description="A documented shared or common capability must remain a viable reusable implementation for its consumers unless documented domain, contract, security, migration or exception constraints justify separate implementations.",
            provenance="Auditor design heuristic for maintainability; not a normative project constraint or Architecture Context finding.",
        )]

    @property
    def follow_up(self):
        return []

    @property
    def follow_up_diagnostics(self):
        return []


class ReuseOpportunityDocDrivenResult(AuditResult):
    """Evidence-backed investigation result; final synthesis is intentionally absent."""

    plan: ReuseOpportunityPlan | InvestigationPlan | None
    hypotheses: list[Hypothesis]
    investigation_results: list[ReuseInvestigationResult] = Field(default_factory=list)
    candidates: list[ReuseOpportunityCandidate] = Field(default_factory=list)
    status: Literal["planning_only", "planning_partial", "planning_blocked",
        "investigation_complete", "investigation_partial", "investigation_blocked"] = "planning_only"
    planning_diagnostics: dict[str, Any] = Field(default_factory=dict)
    investigation_diagnostics: dict[str, Any] = Field(default_factory=dict)
