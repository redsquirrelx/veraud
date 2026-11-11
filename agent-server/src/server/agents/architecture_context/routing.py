"""Deterministic continuation only; no model calls or architectural judgment."""

from collections.abc import Callable

from langgraph.graph import END

from .schemas import RetrievalRecord
from .state import ArchitectureContextState


def route_after_extraction(
    state: ArchitectureContextState, *, trace: Callable[..., None] | None = None
) -> str:
    reason = state.get("context_stop_reason")
    latest_count = len(state["retrieval_plan"].tasks) if state.get("retrieval_plan") else 0
    latest = state.get("retrieval_history", [])[-latest_count:] if latest_count else []
    if not reason and any(
        isinstance(record, RetrievalRecord) and record.status in {"error", "limited"}
        for record in latest
    ):
        reason = "retrieval_incomplete"
    if reason:
        destination = END
    elif state.get("coverage_assessment_status") != "completed":
        destination = END
        reason = "coverage_not_evaluated"
    elif state.get("pending_categories"):
        destination = "plan_retrieval"
        reason = "pending_categories"
    else:
        destination = END
        reason = "coverage_complete"
    if trace:
        trace(
            "route", node="extract_knowledge", destination=destination,
            round=state.get("retrieval_round", 0), reason=reason,
        )
    return destination


def route_after_plan(
    state: ArchitectureContextState, *, trace: Callable[..., None] | None = None
) -> str:
    destination = "retrieve_documents" if state["retrieval_plan"].tasks else END
    if trace:
        trace(
            "route",
            node="plan_retrieval",
            round=state.get("retrieval_round", 0),
            destination=destination,
            reason=state.get("context_stop_reason")
            or ("planned_tasks" if destination != END else "no_useful_tasks"),
        )
    return destination
