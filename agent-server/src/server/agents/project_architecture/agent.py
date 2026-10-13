"""Focused in-memory architecture LangGraph with bounded evidence investigation."""

import asyncio
import json
from dataclasses import dataclass
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from ...services.repository_analysis.context import create_identifier
from ..project_orientation.schemas import OrientationResult
from ..repository_runtime.responses import (
    normalize_record_arrays,
    parse_json_value,
    validation_feedback,
)
from ..repository_runtime.schemas import ExecutionIssue, RepositoryToolCall
from ..repository_runtime.telemetry import (
    TextCallObserver,
)
from ..repository_runtime.token_budget import (
    TokenBudgetExceeded,
    admit_request,
    input_ratio,
)
from ..repository_runtime.tools import RepositoryToolset
from ..repository_runtime.working_context import (
    rejection_details,
    source_arguments,
    source_view,
)
from .context import (
    normalize_source_references,
    validate_orientation_input,
    validate_report,
)
from .coverage import EvidenceGap, application_coverage, validate_closure
from .projection import representation_view
from .prompting import ALLOWED_TOOLS, prepare_prompt
from .results import assemble_result
from .schemas import (
    ArchitectureLimits,
    ArchitectureReport,
    ArchitectureResult,
    ArchitectureTurn,
)


class ArchitectureState(TypedDict):
    representation: dict
    responses: list[dict]
    calls: int
    tool_calls: int
    pending: tuple[RepositoryToolCall, ...]
    raw: dict | None
    architecture: ArchitectureReport | None
    errors: tuple[str, ...]
    issues: tuple[ExecutionIssue, ...]
    corrected: bool
    evidence_recovery: bool
    recovery_tool_calls: int
    finalizing: bool
    reference_repairs: dict[str, str]
    route: str
    result: ArchitectureResult


@dataclass(frozen=True)
class ArchitectureRuntime:
    tools: RepositoryToolset
    generate: object
    limits: ArchitectureLimits
    orientation: OrientationResult | None = None
    on_event: object = None
    feedback: dict | None = None
    objective_id: str = "architecture"


def build_architecture_graph():
    def event(context, name, **values):
        if context.on_event:
            context.on_event(name, values)

    def issue(state, category, message):
        return ExecutionIssue(
            id=create_identifier("issue", "architecture", state["calls"], category),
            stage="architecture",
            category=category,
            message=message[:2000],
        )

    def prepare(state, runtime):
        context = runtime.context
        validate_orientation_input(context.tools, context.orientation)
        view = representation_view(context.tools, context.orientation)
        event(
            context,
            "architecture_prepared",
            candidate_files=len(view["candidate_files"]),
        )
        return {"representation": view}

    async def inspect(state, runtime):
        context = runtime.context
        budget = context.tools.context.input.budget
        maximum = min(context.limits.max_model_calls, budget.max_model_calls)
        if getattr(context.generate, "stopped", False):
            return {
                "route": "finish",
                "issues": (
                    *state["issues"],
                    issue(
                        state,
                        "provider_unavailable",
                        "Provider stopped after a terminal failure.",
                    ),
                ),
            }
        if state["calls"] >= maximum:
            return {
                "route": "finish",
                "issues": (
                    *state["issues"],
                    issue(
                        state, "call_limit", "Architecture model-call limit reached."
                    ),
                ),
            }
        prompt, need_source = prepare_prompt(state, context, maximum)
        event(context, "architecture_turn", turn=state["calls"] + 1, max_turns=maximum)

        def request_guard(text, attempts):
            try:
                admit_request(
                    context.generate, budget, text, context.objective_id, attempts
                )
            except TokenBudgetExceeded as error:
                if not context.limits.soft_token_budgets:
                    raise
                event(
                    context,
                    "budget_advisory",
                    reason=str(error),
                    previous_attempts=attempts,
                    **rejection_details(
                        context.generate, budget, text, context.objective_id
                    ),
                )

        submitted = False
        try:
            if len(prompt) > context.limits.max_prompt_characters:
                if not context.limits.soft_token_budgets:
                    raise TokenBudgetExceeded(
                        "Prompt exceeds the fixed context character limit."
                    )
                event(
                    context,
                    "budget_advisory",
                    reason="Prompt exceeds the target context character limit.",
                    **rejection_details(
                        context.generate, budget, prompt, context.objective_id
                    ),
                )
            request_guard(prompt, 0)
            context.generate.request_guard = request_guard
            submitted = True
            answer = await asyncio.wait_for(
                context.generate(prompt),
                max(
                    0,
                    budget.max_elapsed_seconds - context.tools.context.elapsed_seconds,
                ),
            )
        except Exception as error:  # noqa: BLE001 - provider boundary; external cancellation propagates
            if isinstance(error, TokenBudgetExceeded):
                event(
                    context,
                    "context_rejected",
                    reason=str(error),
                    **rejection_details(
                        context.generate, budget, prompt, context.objective_id
                    ),
                )
            return {
                "calls": state["calls"] + int(submitted),
                "route": "finish",
                "issues": (
                    *state["issues"],
                    issue(
                        state,
                        getattr(error, "category", type(error).__name__),
                        str(error)
                        if hasattr(error, "category")
                        else type(error).__name__,
                    ),
                ),
            }
        update = {
            "calls": state["calls"] + 1,
            "raw": state["raw"],
            "architecture": None,
            "reference_repairs": state["reference_repairs"],
        }
        try:
            value = normalize_record_arrays(
                parse_json_value(answer, 40000), ArchitectureTurn.model_json_schema()
            )
            value, repairs = normalize_source_references(context.tools, value)
            update["reference_repairs"] = state["reference_repairs"] | repairs
            if repairs:
                event(context, "architecture_reference_normalized", aliases=repairs)
            if isinstance(value, dict) and "architecture" in value:
                update["raw"] = value["architecture"]
            turn = ArchitectureTurn.model_validate(value)
            if turn.architecture is not None and need_source:
                raise ValueError(
                    "No sufficient architect source has been inspected. Return tool_calls with get_source_excerpt for relevant candidate files; do not invent evidence IDs."
                )
            if any(call.name not in ALLOWED_TOOLS for call in turn.tool_calls):
                raise ValueError("Use only offered architecture tools.")
            remaining = (
                min(context.limits.max_tool_calls, budget.max_tool_calls)
                - state["tool_calls"]
            )
            if len(turn.tool_calls) > remaining:
                raise ValueError(
                    "Tool budget exhausted; return a scoped architecture with explicit uncertainty."
                )
            return update | {
                "architecture": turn.architecture,
                "pending": turn.tool_calls,
                "route": "tools" if turn.tool_calls else "validate",
                "errors": (),
            }
        except ValueError as error:
            return update | {"errors": validation_feedback(error), "route": "validate"}

    def tools_node(state, runtime):
        context = runtime.context
        responses = list(state["responses"])
        source_cap = min(
            context.limits.max_source_characters,
            max(
                400,
                int(
                    context.tools.context.input.budget.max_input_tokens_per_call
                    / input_ratio(context.generate)
                    * 0.105
                ),
            ),
        )
        for index, call in enumerate(state["pending"]):
            event(
                context,
                "tool_started",
                tool=call.name,
                target=call.arguments.get("path"),
            )
            arguments, requested_end = source_arguments(
                context.tools,
                call.name,
                call.arguments,
                max_characters=source_cap,
            )
            response = context.tools.execute(
                call.name,
                arguments,
                tool_call_id=create_identifier(
                    "tool_call", context.objective_id, state["calls"], index
                ),
            )
            view = source_view(context.tools, response, requested_end)
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
        evidence_gap = False
        if state["architecture"] is not None:
            try:
                validate_report(context.tools, state["architecture"])
                validate_closure(context.tools, state["architecture"])
            except ValueError as error:
                errors = validation_feedback(error)
                evidence_gap = isinstance(error, EvidenceGap)
                if evidence_gap:
                    pending_coverage = [
                        f"{item['path']}: {item['reason']}"
                        for item in application_coverage(
                            context.tools, state["architecture"]
                        )
                        if item["status"] != "explained"
                    ]
                    if pending_coverage:
                        errors = (
                            *errors,
                            "Pending application coverage: "
                            + "; ".join(pending_coverage),
                        )
            else:
                return {"route": "finish", "errors": ()}
        if (
            evidence_gap
            and not state["finalizing"]
            and state["tool_calls"] > state["recovery_tool_calls"]
            and state["calls"]
            < min(
                context.limits.max_model_calls,
                context.tools.context.input.budget.max_model_calls,
            )
            and state["tool_calls"]
            < min(
                context.limits.max_tool_calls,
                context.tools.context.input.budget.max_tool_calls,
            )
        ):
            event(context, "architecture_evidence_needed", errors=list(errors))
            return {
                "errors": errors,
                "route": "inspect",
                "evidence_recovery": True,
                "recovery_tool_calls": state["tool_calls"],
            }
        if (
            evidence_gap
            and not state["finalizing"]
            and state["calls"]
            < min(
                context.limits.max_model_calls,
                context.tools.context.input.budget.max_model_calls,
            )
        ):
            event(context, "architecture_final_assessment", errors=list(errors))
            return {
                "errors": errors,
                "route": "inspect",
                "finalizing": True,
                "evidence_recovery": False,
            }
        if (
            not evidence_gap
            and not state["corrected"]
            and state["calls"]
            < min(
                context.limits.max_model_calls,
                context.tools.context.input.budget.max_model_calls,
            )
        ):
            event(context, "architecture_correction", errors=list(errors))
            return {
                "errors": errors,
                "corrected": True,
                "route": "inspect",
                "evidence_recovery": False,
            }
        return {
            "errors": errors,
            "route": "finish",
            "issues": (
                *state["issues"],
                issue(state, "invalid_architecture", "; ".join(errors)),
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

    graph = StateGraph(ArchitectureState, context_schema=ArchitectureRuntime)
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


class ProjectArchitectureAgent:
    def __init__(self, model, *, generate=None, limits=None, on_event=None):
        self.generate = generate or model.generate
        self.limits = limits or ArchitectureLimits()
        self.on_event = on_event
        self.graph = build_architecture_graph()

    async def compose_diagram(
        self, tools, original_result, *, objective_id="diagram_composition"
    ):
        from .diagram_composition import compose_diagram

        return await compose_diagram(
            self, tools, original_result, objective_id=objective_id
        )

    async def run(
        self, tools, orientation=None, *, feedback=None, objective_id="architecture"
    ):
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
                "architecture": None,
                "errors": (),
                "issues": (),
                "corrected": False,
                "evidence_recovery": False,
                "recovery_tool_calls": -1,
                "finalizing": False,
                "reference_repairs": {},
            },
            context=ArchitectureRuntime(
                tools,
                generate,
                self.limits,
                orientation,
                self.on_event,
                feedback,
                objective_id,
            ),
            config={"recursion_limit": 40},
        )
        return state["result"]
