"""Small in-memory LangGraph: prepare, inspect, tools, validate, finish."""

import asyncio
import json
from dataclasses import dataclass
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from ...services.repository_analysis.context import create_identifier
from ..repository_runtime.responses import (
    normalize_record_arrays,
    parse_json_value,
    validation_feedback,
)
from ..repository_runtime.schemas import ExecutionIssue, RepositoryToolCall
from ..repository_runtime.telemetry import TextCallObserver
from ..repository_runtime.token_budget import (
    TokenBudgetExceeded,
    admit_request,
)
from ..repository_runtime.tools import RepositoryToolset
from ..repository_runtime.working_context import (
    rejection_details,
    source_arguments,
    source_view,
)
from .context import (
    representation_view,
    validate_orientation,
)
from .prompting import ALLOWED_TOOLS, prepare_prompt
from .results import assemble_result
from .schemas import Orientation, OrientationLimits, OrientationResult, OrientationTurn


class OrientationState(TypedDict):
    representation: dict
    responses: list[dict]
    calls: int
    tool_calls: int
    pending: tuple[RepositoryToolCall, ...]
    raw: dict | None
    orientation: Orientation | None
    errors: tuple[str, ...]
    issues: tuple[ExecutionIssue, ...]
    corrected: bool
    route: str
    result: OrientationResult


@dataclass(frozen=True)
class OrientationRuntime:
    tools: RepositoryToolset
    generate: object
    limits: OrientationLimits
    on_event: object = None


def build_orientation_graph():
    def event(runtime, name, **values):
        if runtime.on_event:
            runtime.on_event(name, values)

    def problem(state, category, message):
        return ExecutionIssue(
            id=create_identifier("issue", "orientation", state["calls"], category),
            stage="orientation",
            category=category,
            message=message[:2000],
        )

    def prepare(state, runtime):
        view = representation_view(runtime.context.tools)
        event(
            runtime.context,
            "orientation_prepared",
            candidate_files=len(view["candidate_files"]),
        )
        return {"representation": view}

    async def inspect(state, runtime):
        context = runtime.context
        budget = context.tools.context.input.budget
        max_calls = min(context.limits.max_model_calls, budget.max_model_calls)
        if state["calls"] >= max_calls:
            return {
                "route": "finish",
                "issues": (
                    *state["issues"],
                    problem(state, "call_limit", "Orientation call limit reached."),
                ),
            }
        prompt = prepare_prompt(state, context, max_calls)
        event(context, "orientation_turn", turn=state["calls"] + 1, max_turns=max_calls)
        submitted = False
        try:
            if len(prompt) > context.limits.max_prompt_characters:
                raise TokenBudgetExceeded(
                    "Prompt exceeds the fixed context character limit."
                )
            admit_request(context.generate, budget, prompt, "orientation")
            context.generate.request_guard = lambda text, attempts: admit_request(
                context.generate, budget, text, "orientation", attempts
            )
            submitted = True
            answer = await asyncio.wait_for(
                context.generate(prompt),
                max(
                    0,
                    budget.max_elapsed_seconds - context.tools.context.elapsed_seconds,
                ),
            )
        except Exception as error:  # noqa: BLE001 - provider boundary; cancellation propagates
            if isinstance(error, TokenBudgetExceeded):
                event(
                    context,
                    "context_rejected",
                    reason=str(error),
                    **rejection_details(
                        context.generate, budget, prompt, "orientation"
                    ),
                )
            return {
                "calls": state["calls"] + int(submitted),
                "route": "finish",
                "issues": (
                    *state["issues"],
                    problem(
                        state,
                        getattr(error, "category", type(error).__name__),
                        str(error)
                        if hasattr(error, "category")
                        else type(error).__name__,
                    ),
                ),
            }
        update = {"calls": state["calls"] + 1, "raw": state["raw"], "orientation": None}
        try:
            value = normalize_record_arrays(
                parse_json_value(answer, 30000), OrientationTurn.model_json_schema()
            )
            if isinstance(value, dict) and "orientation" in value:
                update["raw"] = value["orientation"]
            turn = OrientationTurn.model_validate(value)
            if turn.tool_calls:
                if any(call.name not in ALLOWED_TOOLS for call in turn.tool_calls):
                    raise ValueError("Use only offered orientation tools.")
                remaining = (
                    min(context.limits.max_tool_calls, budget.max_tool_calls)
                    - state["tool_calls"]
                )
                if len(turn.tool_calls) > remaining:
                    raise ValueError(
                        "Tool budget exhausted; return orientation with explicit uncertainties."
                    )
            return update | {
                "orientation": turn.orientation,
                "pending": turn.tool_calls,
                "route": "tools" if turn.tool_calls else "validate",
                "errors": (),
            }
        except ValueError as error:
            return update | {"errors": validation_feedback(error), "route": "validate"}

    def tools_node(state, runtime):
        context = runtime.context
        responses = list(state["responses"])
        for index, call in enumerate(state["pending"]):
            event(context, "tool_started", tool=call.name)
            arguments, requested_end = source_arguments(
                context.tools, call.name, call.arguments
            )
            response = context.tools.execute(
                call.name,
                arguments,
                tool_call_id=create_identifier(
                    "tool_call", "orientation", state["calls"], index
                ),
            )
            view = source_view(context.tools, response, requested_end)
            # Replace equivalent results while preserving full delivered provenance internally.
            signature = json.dumps([call.name, call.arguments], sort_keys=True)
            responses = [item for item in responses if item["signature"] != signature]
            responses.append(
                {
                    "signature": signature,
                    "role": "tool",
                    "content": json.dumps(view, separators=(",", ":")),
                }
            )
            event(
                context,
                "tool_finished",
                tool=call.name,
                status=response.status,
                tool_calls=context.tools.budget_usage.tool_calls,
            )
        return {
            "responses": responses,
            "tool_calls": state["tool_calls"] + len(state["pending"]),
            "pending": (),
            "route": "inspect",
        }

    def validate(state, runtime):
        context = runtime.context
        errors = state["errors"]
        if state["orientation"] is not None:
            try:
                validate_orientation(context.tools, state["orientation"])
            except ValueError as error:
                errors = validation_feedback(error)
            else:
                return {"route": "finish", "errors": ()}
        if not state["corrected"] and state["calls"] < min(
            context.limits.max_model_calls,
            context.tools.context.input.budget.max_model_calls,
        ):
            event(context, "orientation_correction", errors=list(errors))
            return {"errors": errors, "corrected": True, "route": "inspect"}
        return {
            "errors": errors,
            "route": "finish",
            "issues": (
                *state["issues"],
                problem(state, "invalid_orientation", "; ".join(errors)),
            ),
        }

    def finish(state, runtime):
        context = runtime.context
        result = assemble_result(state, context)
        event(
            context,
            "finished",
            status=result.completion_status,
            model_calls=state["calls"],
            tool_calls=state["tool_calls"],
        )
        return {"result": result}

    graph = StateGraph(OrientationState, context_schema=OrientationRuntime)
    for name, node in {
        "prepare_context": prepare,
        "inspect": inspect,
        "tools": tools_node,
        "validate": validate,
        "finish": finish,
    }.items():
        graph.add_node(name, node)
    graph.add_edge(START, "prepare_context")
    graph.add_edge("prepare_context", "inspect")
    graph.add_conditional_edges("inspect", lambda state: state["route"])
    graph.add_edge("tools", "inspect")
    graph.add_conditional_edges("validate", lambda state: state["route"])
    graph.add_edge("finish", END)
    return graph.compile()


class ProjectOrientationAgent:
    def __init__(self, model, *, generate=None, limits=None, on_event=None):
        self.generate = generate or model.generate
        self.limits = limits or OrientationLimits()
        self.on_event = on_event
        self.graph = build_orientation_graph()

    async def run(self, tools):
        generate = (
            self.generate
            if hasattr(self.generate, "telemetry")
            else TextCallObserver(self.generate)
        )
        state = await self.graph.ainvoke(
            {
                "responses": [],
                "calls": 0,
                "tool_calls": 0,
                "pending": (),
                "raw": None,
                "orientation": None,
                "errors": (),
                "issues": (),
                "corrected": False,
            },
            context=OrientationRuntime(tools, generate, self.limits, self.on_event),
            config={"recursion_limit": 30},
        )
        return state["result"]
