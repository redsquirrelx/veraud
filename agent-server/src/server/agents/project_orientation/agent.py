"""Small in-memory LangGraph: prepare, inspect, tools, validate, finish."""

import asyncio
import json
from dataclasses import dataclass
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from ...services.repository_analysis.context import create_identifier
from ..project_analysis.investigation import tool_signatures
from ..project_analysis.schemas import BudgetUsage, ExecutionIssue
from ..project_analysis.telemetry import TextCallObserver, measure_json, measured_prompt
from ..project_analysis.token_budget import account_tokens, admit_request, input_ratio
from ..project_analysis.validation import (
    normalize_record_arrays,
    parse_json_value,
    validation_feedback,
)
from .context import (
    prompt_template,
    representation_view,
    retain_valid_sections,
    validate_orientation,
)
from .schemas import OrientationLimits, OrientationResult, OrientationTurn

ALLOWED_TOOLS = {
    "list_files",
    "find_symbols",
    "get_source_excerpt",
    "list_relationships",
    "search_repository_text",
}


class OrientationState(TypedDict):
    representation: dict
    responses: list[dict]
    calls: int
    tool_calls: int
    pending: tuple
    raw: dict | None
    orientation: object
    errors: tuple[str, ...]
    issues: tuple[ExecutionIssue, ...]
    corrected: bool
    route: str
    result: OrientationResult


@dataclass(frozen=True)
class OrientationRuntime:
    tools: object
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
        responses = list(state["responses"])
        omitted = 0
        cap = min(
            context.limits.max_prompt_characters,
            int(budget.max_input_tokens_per_call / input_ratio(context.generate)) - 128,
        )
        while True:
            data = {
                "representation": state["representation"],
                "tool_results": responses,
                "omitted_tool_results": omitted,
                "remaining_model_calls": max_calls - state["calls"],
                "remaining_tool_calls": min(
                    context.limits.max_tool_calls, budget.max_tool_calls
                )
                - state["tool_calls"],
                "validation_errors": state["errors"],
            }
            text, sizes = measure_json(
                data,
                fields={"tool_results": "history", "validation_errors": "feedback"},
            )
            prompt = measured_prompt(
                [
                    (prompt_template("system"), "instructions"),
                    (
                        prompt_template(
                            "correction" if state["errors"] else "investigation"
                        ),
                        "instructions",
                    ),
                    (
                        "\nOUTPUT_SCHEMA\n"
                        + json.dumps(
                            OrientationTurn.model_json_schema(), separators=(",", ":")
                        ),
                        "contracts",
                    ),
                    (
                        "\nTOOLS\n"
                        + json.dumps(
                            {
                                key: value
                                for key, value in tool_signatures().items()
                                if key in ALLOWED_TOOLS
                            }
                        ),
                        "contracts",
                    ),
                    ("\nORIENTATION_DATA\n", "framing"),
                    (text, sizes),
                ],
                stage="investigation",
                objective_id="orientation",
                correction=bool(state["errors"]),
            )
            if len(prompt) <= cap or not responses:
                break
            responses.pop(0)
            omitted += 1
        event(context, "orientation_turn", turn=state["calls"] + 1, max_turns=max_calls)
        submitted = False
        try:
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
        update = {"calls": state["calls"] + 1, "raw": None, "orientation": None}
        try:
            value = normalize_record_arrays(
                parse_json_value(answer, 30000), OrientationTurn.model_json_schema()
            )
            update["raw"] = (
                value.get("orientation") if isinstance(value, dict) else None
            )
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
            response = context.tools.execute(
                call.name,
                call.arguments,
                tool_call_id=create_identifier(
                    "tool_call", "orientation", state["calls"], index
                ),
            )
            view = context.tools.model_view(response)
            # Replace equivalent results while preserving full delivered provenance internally.
            signature = json.dumps([call.name, call.arguments], sort_keys=True)
            responses = [item for item in responses if item["signature"] != signature]
            responses.append(
                {"signature": signature, "role": "tool", "content": json.dumps(view)}
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
        orientation = retain_valid_sections(context.tools, state["raw"])
        evidence = context.tools.retrieved_evidence
        inspected = tuple(
            sorted({record.file_id for record in evidence if record.kind == "source"})
        )
        complete = bool(
            orientation
            and orientation.project_type
            and orientation.purpose
            and orientation.project_type.status != "unresolved"
            and orientation.purpose.status != "unresolved"
            and orientation.starting_points
            and inspected
            and not state["issues"]
            and not state["errors"]
        )
        status = "complete" if complete else "partial" if orientation else "failed"
        limitations = (
            "Orientation covers selected technical files, not the entire repository. Source access validation does not prove semantic sufficiency.",
        )
        if not complete:
            limitations += (
                "Missing, invalid, or uninspected sections remain unresolved.",
            )
        counts, estimates = account_tokens(
            context.generate, context.tools.context.input.budget
        )
        totals = (
            context.generate.usage_totals()
            if hasattr(context.generate, "usage_totals")
            else {"unknown_usage_attempts": state["calls"]}
        )
        usage = BudgetUsage(
            model_calls=state["calls"],
            tool_calls=context.tools.budget_usage.tool_calls,
            retrieved_characters=context.tools.budget_usage.retrieved_characters,
            elapsed_seconds=context.tools.context.elapsed_seconds,
            accounted_tokens=counts,
            estimated_tokens=estimates,
            token_budget_exhausted=any(
                issue.category == "token_budget_exhausted" for issue in state["issues"]
            ),
            **totals,
        )
        result = OrientationResult(
            snapshot_hash=context.tools.context.input.snapshot_hash,
            completion_status=status,
            orientation=orientation,
            retrieved_evidence=evidence,
            inspected_file_ids=inspected,
            limitations=limitations,
            execution_issues=state["issues"],
            usage=usage,
            telemetry=context.generate.telemetry(context.tools.tool_measurements),
        )
        context.tools.context.require_snapshot(result.snapshot_hash)
        event(
            context,
            "finished",
            status=status,
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
