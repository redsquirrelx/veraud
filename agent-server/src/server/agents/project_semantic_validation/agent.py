"""Independent, bounded LangGraph semantic investigation over claim batches."""

import asyncio
import json
from dataclasses import dataclass
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from ...services.repository_analysis.context import create_identifier
from ..project_architecture.schemas import ArchitectureResult
from ..repository_runtime.responses import (
    normalize_record_arrays,
    parse_json_value,
    validation_feedback,
)
from ..repository_runtime.schemas import ExecutionIssue, RepositoryToolCall
from ..repository_runtime.telemetry import TextCallObserver
from ..repository_runtime.token_budget import TokenBudgetExceeded, admit_request
from ..repository_runtime.tools import RepositoryToolset
from ..repository_runtime.working_context import (
    rejection_details,
    source_arguments,
    source_view,
)
from .context import report_hash, retain_findings, review_targets, validate_input
from .prompting import ALLOWED_TOOLS, prepare_prompt
from .results import assemble_result
from .schemas import (
    ReviewTarget,
    SemanticFinding,
    SemanticValidationResult,
    ValidationLimits,
    ValidationTurn,
)


class ValidationState(TypedDict):
    targets: tuple[ReviewTarget, ...]
    selected: tuple[ReviewTarget, ...]
    report_hash: str
    responses: list[dict]
    findings: dict[str, SemanticFinding]
    pending: tuple[RepositoryToolCall, ...]
    raw_findings: list[dict]
    active_ids: set[str]
    errors: tuple[str, ...]
    issues: tuple[ExecutionIssue, ...]
    calls: int
    repaired: bool
    route: str
    result: SemanticValidationResult


@dataclass(frozen=True)
class ValidationRuntime:
    tools: RepositoryToolset
    original: ArchitectureResult
    generate: object
    limits: ValidationLimits
    on_event: object = None
    objective_id: str = "semantic_validation"
    soft_token_budgets: bool = False


def build_validation_graph():
    def event(context, name, **values):
        if context.on_event:
            context.on_event(name, values)

    def issue(state, category, message):
        return ExecutionIssue(
            id=create_identifier(
                "issue", "semantic_validation", state["calls"], category
            ),
            stage="semantic_validation",
            category=category,
            message=message[:2000],
        )

    def prepare(state, runtime):
        context = runtime.context
        validate_input(context.tools, context.original)
        targets = review_targets(context.tools, context.original)
        selected = targets[: context.limits.max_claims]
        event(
            context,
            "semantic_validation_prepared",
            claims=len(targets),
            selected=len(selected),
        )
        return {
            "targets": targets,
            "selected": selected,
            "report_hash": report_hash(context.original),
        }

    async def inspect(state, runtime):
        context = runtime.context
        budget = context.tools.context.input.budget
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
        if all(target.id in state["findings"] for target in state["selected"]):
            return {"route": "finish"}
        if state["calls"] >= min(
            context.limits.max_model_calls, budget.max_model_calls
        ):
            return {
                "route": "finish",
                "issues": (
                    *state["issues"],
                    issue(
                        state, "call_limit", "Semantic review model-call limit reached."
                    ),
                ),
            }
        prompt, active = prepare_prompt(state, context)
        submitted = False
        try:
            if len(prompt) > context.limits.max_prompt_characters:
                raise TokenBudgetExceeded(
                    "Semantic review exceeds its context character limit."
                )

            def admission(text, attempts=0):
                try:
                    admit_request(
                        context.generate, budget, text, context.objective_id, attempts
                    )
                except TokenBudgetExceeded as error:
                    if not context.soft_token_budgets:
                        raise
                    event(
                        context,
                        "budget_advisory",
                        reason=str(error),
                        **rejection_details(
                            context.generate, budget, text, context.objective_id
                        ),
                    )

            admission(prompt)
            context.generate.request_guard = admission
            event(
                context,
                "semantic_validation_turn",
                turn=state["calls"] + 1,
                targets=sorted(active),
            )
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
                "route": "finish",
                "calls": state["calls"] + int(submitted),
                "issues": (
                    *state["issues"],
                    issue(
                        state,
                        getattr(error, "category", type(error).__name__),
                        str(error)
                        if isinstance(error, TokenBudgetExceeded)
                        else type(error).__name__,
                    ),
                ),
            }
        update = {"calls": state["calls"] + 1, "active_ids": active, "raw_findings": []}
        try:
            value, pruned = normalize_record_arrays(
                parse_json_value(answer, 40000), ValidationTurn.model_json_schema()
            )
            if pruned:
                event(context, "model_response_pruned", dropped=list(pruned))
            if (
                isinstance(value, dict)
                and value.get("findings")
                and not value.get("tool_calls")
            ):
                if (
                    not isinstance(value["findings"], list)
                    or len(value["findings"]) > context.limits.batch_size
                ):
                    raise ValueError("Return at most the active batch's findings.")
                if set(value) != {"findings"}:
                    raise ValueError("Finding responses cannot contain extra fields.")
                return update | {"raw_findings": value["findings"], "route": "validate"}
            turn = ValidationTurn.model_validate(value)
            if any(call.name not in ALLOWED_TOOLS for call in turn.tool_calls):
                raise ValueError("Use only offered semantic validation tools.")
            if (
                len(turn.tool_calls)
                > min(context.limits.max_tool_calls, budget.max_tool_calls)
                - context.tools.budget_usage.tool_calls
            ):
                raise ValueError(
                    "Tool budget exhausted; close claims with explicit missing evidence."
                )
            return update | {"pending": turn.tool_calls, "route": "tools", "errors": ()}
        except ValueError as error:
            return update | {"route": "validate", "errors": validation_feedback(error)}

    def tools_node(state, runtime):
        context = runtime.context
        responses = list(state["responses"])
        for index, call in enumerate(state["pending"]):
            event(
                context,
                "tool_started",
                tool=call.name,
                target=call.arguments.get("path"),
            )
            arguments, requested_end = source_arguments(
                context.tools, call.name, call.arguments, max_characters=2400
            )
            response = context.tools.execute(
                call.name,
                arguments,
                tool_call_id=create_identifier(
                    "tool_call", context.objective_id, state["calls"], index
                ),
            )
            signature = json.dumps([call.name, call.arguments], sort_keys=True)
            responses = [item for item in responses if item["signature"] != signature]
            responses.append(
                {
                    "signature": signature,
                    "role": "tool",
                    "content": json.dumps(
                        source_view(context.tools, response, requested_end),
                        separators=(",", ":"),
                    ),
                }
            )
            event(
                context,
                "tool_finished",
                tool=call.name,
                status=response.status,
                tool_calls=context.tools.budget_usage.tool_calls,
            )
        return {"responses": responses, "pending": (), "route": "inspect"}

    def validate(state, runtime):
        context = runtime.context
        active = {
            target.id: target
            for target in state["selected"]
            if target.id in state["active_ids"]
        }
        accepted, errors = retain_findings(context.tools, state["raw_findings"], active)
        errors = errors or (state["errors"] if not state["raw_findings"] else ())
        findings = state["findings"] | accepted
        if accepted:
            event(context, "semantic_findings_accepted", targets=list(accepted))
        if errors and state["repaired"] and not accepted:
            return {
                "findings": findings,
                "errors": errors,
                "route": "finish",
                "issues": (
                    *state["issues"],
                    issue(state, "invalid_findings", "; ".join(errors)),
                ),
            }
        return {
            "findings": findings,
            "errors": errors,
            "repaired": bool(errors),
            "route": "inspect",
        }

    def finish(state, runtime):
        result = assemble_result(state, runtime.context)
        event(
            runtime.context,
            "semantic_validation_finished",
            status=result.completion_status,
            verdict=result.verdict,
            reviewed=len(result.findings),
            pending=len(result.pending_target_ids),
        )
        return {"result": result}

    graph = StateGraph(ValidationState, context_schema=ValidationRuntime)
    for name, node in {
        "prepare": prepare,
        "inspect": inspect,
        "tools": tools_node,
        "validate": validate,
        "finish": finish,
    }.items():
        graph.add_node(name, node)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "inspect")
    graph.add_conditional_edges("inspect", lambda state: state["route"])
    graph.add_edge("tools", "inspect")
    graph.add_conditional_edges("validate", lambda state: state["route"])
    graph.add_edge("finish", END)
    return graph.compile()


class ProjectSemanticValidationAgent:
    def __init__(self, model, *, generate=None, limits=None, on_event=None):
        self.generate = generate or model.generate
        self.limits = limits or ValidationLimits()
        self.on_event = on_event
        self.graph = build_validation_graph()

    async def run(
        self,
        tools,
        original_result,
        *,
        objective_id="semantic_validation",
        soft_token_budgets=False,
    ):
        generate = (
            self.generate
            if hasattr(self.generate, "telemetry")
            else TextCallObserver(self.generate)
        )
        state = await self.graph.ainvoke(
            {
                "responses": [],
                "findings": {},
                "pending": (),
                "raw_findings": [],
                "active_ids": set(),
                "errors": (),
                "issues": (),
                "calls": 0,
                "repaired": False,
            },
            context=ValidationRuntime(
                tools,
                original_result,
                generate,
                self.limits,
                self.on_event,
                objective_id,
                soft_token_budgets,
            ),
            config={"recursion_limit": 60},
        )
        return state["result"]
