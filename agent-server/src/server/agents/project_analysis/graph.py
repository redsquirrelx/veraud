"""Phase-three planning subgraph, usable alone or inside the future analyst."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from ...services.repository_analysis.context import create_identifier
from .planning import (
    CandidateCatalog,
    PlanningLimits,
    build_investigation_candidates,
    validate_and_prioritize_plan,
)
from .prompts import render_planning_prompt
from .schemas import ExecutionIssue, InvestigationProposal
from .state import ProjectAnalysisState
from .telemetry import TextCallObserver
from .tools import RepositoryToolset


class PlanningModel(Protocol):
    async def generate(self, message: str) -> str: ...


@dataclass(frozen=True)
class PlanningRuntime:
    tools: RepositoryToolset
    generate: Callable[[str], Awaitable[str]]
    limits: PlanningLimits


def catalog_from_state(state) -> CandidateCatalog:
    return CandidateCatalog(state["candidates"], state["offered_candidate_ids"])


def planning_issue(state, category, message):
    return ExecutionIssue(
        id=create_identifier(
            "issue", "planning", category, state["budget_usage"].model_calls
        ),
        stage="planning",
        category=category,
        message=message,
    )


def build_candidates_node(state, runtime):
    context = runtime.context.tools.context
    context.require_snapshot(state["snapshot_hash"])
    catalog = build_investigation_candidates(
        runtime.context.tools, runtime.context.limits
    )
    # Bound the actual prompt catalog before exposing it to the model.
    try:
        _, catalog = render_planning_prompt(
            runtime.context.tools, catalog, runtime.context.limits
        )
    except ValueError:
        return {
            "candidates": catalog.candidates,
            "offered_candidate_ids": (),
            "planning_status": "failed",
            "execution_issues": (
                planning_issue(
                    state,
                    "prompt_budget_exhausted",
                    "Planning instructions/schema cannot fit the prompt budget.",
                ),
            ),
        }
    return {
        "candidates": catalog.candidates,
        "offered_candidate_ids": catalog.offered_candidate_ids,
        "planning_status": "pending",
        "validation_errors": (),
        "plan_proposal": None,
    }


async def propose_plan_node(state, runtime):
    if state.get("planning_status") == "failed":
        return {}
    tools = runtime.context.tools
    budget = tools.context.input.budget
    usage = state["budget_usage"]
    remaining_seconds = budget.max_elapsed_seconds - tools.context.elapsed_seconds
    if (
        usage.model_calls >= budget.max_model_calls - budget.reserved_report_model_calls
        or remaining_seconds <= 0
        or not state["offered_candidate_ids"]
    ):
        category = (
            "no_accessible_candidates"
            if not state["offered_candidate_ids"]
            else "planning_budget_exhausted"
        )
        return {
            "planning_status": "failed",
            "execution_issues": (
                planning_issue(
                    state,
                    category,
                    "Planning cannot proceed within accessible candidates and reserved execution budgets.",
                ),
            ),
        }
    prompt, catalog = render_planning_prompt(
        tools,
        catalog_from_state(state),
        runtime.context.limits,
        state.get("validation_errors", ()),
    )
    usage = usage.model_copy(update={"model_calls": usage.model_calls + 1})
    update = {
        "budget_usage": usage,
        "offered_candidate_ids": catalog.offered_candidate_ids,
        "plan_proposal": None,
    }
    try:
        answer = await asyncio.wait_for(
            runtime.context.generate(prompt),
            timeout=max(0, budget.max_elapsed_seconds - tools.context.elapsed_seconds),
        )
    except Exception as error:  # noqa: BLE001 - isolate provider-specific SDK failures
        # External cancellation propagates; the caller owns provider cleanup.
        category = "model_timeout" if isinstance(error, TimeoutError) else "model_error"
        from ...benchmark.pacing import http_status

        status = http_status(error)
        return update | {
            "planning_status": "failed",
            "execution_issues": (
                planning_issue(
                    state,
                    category,
                    f"Planning provider failed: {type(error).__name__}"
                    + (f" (HTTP {status})." if status else "."),
                ),
            ),
            "budget_usage": usage.model_copy(
                update={"elapsed_seconds": tools.context.elapsed_seconds}
            ),
        }
    if tools.context.elapsed_seconds >= budget.max_elapsed_seconds:
        return update | {
            "planning_status": "failed",
            "execution_issues": (
                planning_issue(
                    state,
                    "planning_budget_exhausted",
                    "The execution time budget expired before plan delivery.",
                ),
            ),
            "budget_usage": usage.model_copy(
                update={"elapsed_seconds": tools.context.elapsed_seconds}
            ),
        }
    try:
        if (
            not isinstance(answer, str)
            or len(answer) > runtime.context.limits.max_response_characters
        ):
            raise ValueError("Planning response must be bounded JSON text.")

        # Reject nonstandard numeric values and duplicate object keys.
        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Planning JSON contains duplicate keys.")
                result[key] = value
            return result

        def reject_constant(_value):
            raise ValueError("Planning JSON contains a nonstandard numeric constant.")

        data = json.loads(
            answer, object_pairs_hook=unique_object, parse_constant=reject_constant
        )
        proposal = InvestigationProposal.model_validate(data)
        update.update(plan_proposal=proposal, validation_errors=())
    except (ValueError, ValidationError) as error:
        # Feedback is bounded and does not echo arbitrary model output.
        message = (
            "Planning output did not match the proposal schema."
            if isinstance(error, ValidationError)
            else str(error)[:500]
        )
        update.update(validation_errors=(message,))
    update["budget_usage"] = usage.model_copy(
        update={"elapsed_seconds": tools.context.elapsed_seconds}
    )
    return update


def validate_plan_node(state, runtime):
    if state.get("planning_status") == "failed":
        return failed_plan_update(state)
    errors = state.get("validation_errors", ())
    proposal = state.get("plan_proposal")
    if proposal is not None:
        try:
            plan = validate_and_prioritize_plan(
                runtime.context.tools, catalog_from_state(state), proposal
            )
            return {
                "investigation_plan": plan,
                "investigation_queue": plan.objectives,
                "planning_decisions": plan.decisions,
                "planning_status": "ready",
                "validation_errors": (),
            }
        except ValueError as error:
            errors = (str(error)[:500],)
    budget = runtime.context.tools.context.input.budget
    if (
        state["plan_corrections"] < budget.max_plan_corrections
        and state["budget_usage"].model_calls
        < budget.max_model_calls - budget.reserved_report_model_calls
    ):
        return {
            "plan_corrections": state["plan_corrections"] + 1,
            "validation_errors": errors,
            "planning_status": "correcting",
        }
    return failed_plan_update(state) | {
        "planning_status": "failed",
        "validation_errors": errors,
        "execution_issues": (
            planning_issue(
                state,
                "invalid_plan",
                "Planning failed after bounded corrections: " + "; ".join(errors),
            ),
        ),
    }


def failed_plan_update(state):
    from .schemas import InvestigationPlan, PlanningDecision

    decisions = tuple(
        PlanningDecision(
            id=create_identifier("planning_decision", candidate.id, "planning_failed"),
            candidate_id=candidate.id,
            disposition="deferred",
            reason="Planning failed before this candidate could be scheduled.",
        )
        for candidate in state["candidates"]
    )
    plan = InvestigationPlan(candidates=state["candidates"], decisions=decisions)
    return {
        "investigation_plan": plan,
        "planning_decisions": decisions,
        "investigation_queue": (),
    }


def after_validation(state):
    return (
        "propose_investigation_plan"
        if state.get("planning_status") == "correcting"
        else END
    )


def build_planning_graph():
    graph = StateGraph(ProjectAnalysisState, context_schema=PlanningRuntime)
    graph.add_node("build_investigation_candidates", build_candidates_node)
    graph.add_node("propose_investigation_plan", propose_plan_node)
    graph.add_node("validate_and_prioritize_plan", validate_plan_node)
    graph.add_edge(START, "build_investigation_candidates")
    graph.add_edge("build_investigation_candidates", "propose_investigation_plan")
    graph.add_edge("propose_investigation_plan", "validate_and_prioritize_plan")
    graph.add_conditional_edges(
        "validate_and_prioritize_plan",
        after_validation,
        {"propose_investigation_plan": "propose_investigation_plan", END: END},
    )
    return graph.compile()


class InvestigationPlanner:
    """Caller owns the model/client; optional generate wrapper supports tracing."""

    def __init__(
        self,
        model: PlanningModel,
        *,
        limits: PlanningLimits | None = None,
        generate: Callable[[str], Awaitable[str]] | None = None,
    ):
        self.model = model
        self.limits = limits or PlanningLimits()
        self.generate = generate or model.generate
        self.graph = build_planning_graph()

    async def plan(
        self, tools: RepositoryToolset, state: ProjectAnalysisState | None = None
    ) -> ProjectAnalysisState:
        initial = state if state is not None else tools.initial_state()
        if initial["input"] != tools.context.input:
            raise ValueError("Planning state must use the bound execution input.")
        generate = (
            self.generate
            if hasattr(self.generate, "telemetry")
            else TextCallObserver(self.generate)
        )
        result = await self.graph.ainvoke(
            initial,
            context=PlanningRuntime(tools, generate, self.limits),
            config={
                "recursion_limit": 6
                + 2 * tools.context.input.budget.max_plan_corrections
            },
        )
        result["telemetry"] = generate.telemetry(tools.tool_measurements)
        return result
