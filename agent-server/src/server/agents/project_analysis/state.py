"""LangGraph state channels and explicit, immutable accumulation semantics."""

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from ...services.repository_analysis.schemas import RepositoryOverview
from .schemas import (
    AnalysisContract,
    BudgetUsage,
    CompletionStatus,
    ExecutionIssue,
    InvestigationCandidate,
    InvestigationObjective,
    InvestigationPlan,
    InvestigationProposal,
    InvestigationResult,
    InvestigationTurn,
    OpenQuestion,
    PlanningDecision,
    ProjectAnalysisInput,
    ProjectAnalysisReport,
    ProjectAnalysisRunResult,
    ReportSelection,
    RepositoryToolCall,
    RetrievedEvidence,
)
from .telemetry import ExecutionTelemetry


def merge_records_by_id[Record: AnalysisContract](
    existing: tuple[Record, ...],
    incoming: tuple[Record, ...],
) -> tuple[Record, ...]:
    """Append new IDs, ignore exact replay, and reject conflicting rewrites.

    Accepted evidence/findings are immutable. Corrections belong in draft channels
    before acceptance. Return a new tuple without mutating either input.
    """
    merged = {}
    for record in (*existing, *incoming):
        previous = merged.get(record.id)
        if previous is not None and previous != record:
            raise ValueError(f"Conflicting accumulated record: {record.id}")
        merged[record.id] = record
    return tuple(merged.values())


class ProjectAnalysisState(TypedDict, total=False):
    """Accumulated records use reducers; queues, drafts, and counters replace.

    Only the sequential scheduler updates queue and cumulative BudgetUsage.
    investigation_messages uses LangGraph's message-ID merge/removal semantics;
    the scheduler must explicitly remove old messages when switching targets.
    The snapshot/query service belong to runtime context, not serializable state.
    """

    telemetry: ExecutionTelemetry
    query_ledger: tuple[dict, ...]
    investigation_raw_result: dict | None

    input: ProjectAnalysisInput
    snapshot_hash: str
    repository_overview: RepositoryOverview
    candidates: Annotated[tuple[InvestigationCandidate, ...], merge_records_by_id]
    planning_decisions: Annotated[tuple[PlanningDecision, ...], merge_records_by_id]
    investigation_plan: InvestigationPlan | None
    offered_candidate_ids: tuple[str, ...]
    plan_proposal: InvestigationProposal | None
    planning_status: str
    investigation_queue: tuple[InvestigationObjective, ...]
    active_investigation: InvestigationObjective | None
    investigation_messages: Annotated[list[AnyMessage], add_messages]
    investigation_draft: InvestigationResult | None
    investigation_turn: InvestigationTurn | None
    pending_tool_calls: tuple[RepositoryToolCall, ...]
    investigation_model_calls: int
    investigation_status: str
    investigation_evidence_ids: tuple[str, ...]
    retrieved_evidence: Annotated[tuple[RetrievedEvidence, ...], merge_records_by_id]
    findings: Annotated[tuple[InvestigationResult, ...], merge_records_by_id]
    open_questions: Annotated[tuple[OpenQuestion, ...], merge_records_by_id]
    execution_issues: Annotated[tuple[ExecutionIssue, ...], merge_records_by_id]
    budget_usage: BudgetUsage
    plan_corrections: int
    finding_corrections: int
    report_repairs: int
    report_draft: ProjectAnalysisReport | None
    report_selection: ReportSelection | None
    report_status: str
    validation_errors: tuple[str, ...]
    completion_status: CompletionStatus | None
    result: ProjectAnalysisRunResult | None
