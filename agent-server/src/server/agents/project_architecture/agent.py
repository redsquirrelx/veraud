"""Focused in-memory architecture LangGraph with bounded evidence investigation."""

import asyncio
import json
from dataclasses import dataclass
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from ...services.repository_analysis.context import create_identifier
from ..project_analysis.investigation import tool_signatures
from ..project_analysis.schemas import BudgetUsage, ExecutionIssue
from ..project_analysis.telemetry import (
    TextCallObserver,
    execution_telemetry,
    measure_json,
    measured_prompt,
)
from ..project_analysis.token_budget import account_tokens, admit_request, input_ratio
from ..project_analysis.validation import (
    normalize_record_arrays,
    parse_json_value,
    validation_feedback,
)
from .context import (
    citations_for,
    contract_view,
    prompt_template,
    representation_view,
    retain_valid_sections,
    validate_orientation_input,
    validate_report,
)
from .schemas import ArchitectureLimits, ArchitectureResult, ArchitectureTurn

ALLOWED_TOOLS = {
    "list_files",
    "find_symbols",
    "get_source_excerpt",
    "list_relationships",
    "search_repository_text",
    "get_infrastructure",
    "get_evidence",
}


class ArchitectureState(TypedDict):
    representation: dict
    responses: list[dict]
    calls: int
    tool_calls: int
    pending: tuple
    raw: dict | None
    architecture: object
    errors: tuple[str, ...]
    issues: tuple[ExecutionIssue, ...]
    corrected: bool
    route: str
    result: ArchitectureResult


@dataclass(frozen=True)
class ArchitectureRuntime:
    tools: object
    generate: object
    limits: ArchitectureLimits
    orientation: object = None
    on_event: object = None


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
        responses = list(state["responses"])
        representation = json.loads(json.dumps(state["representation"]))
        inspected = {
            record.file_id
            for record in context.tools.retrieved_evidence
            if record.kind == "source"
        }
        need_source = len(inspected) < min(
            2, len(context.tools.accessible_snapshot.files)
        )
        paths = {
            source.id: source.path for source in context.tools.accessible_snapshot.files
        }
        evidence_ledger = [
            {
                "id": record.id,
                "file_id": record.file_id,
                "path": paths[record.file_id],
                "start_line": record.start_line,
                "end_line": record.end_line,
            }
            for record in context.tools.retrieved_evidence
            if record.kind == "source"
        ]
        draft_units = (
            state["raw"].get("organization", [])
            if isinstance(state["raw"], dict)
            else []
        )
        if not isinstance(draft_units, list):
            draft_units = []
        contract = contract_view(ArchitectureTurn.model_json_schema())
        if need_source:
            contract = {
                "response_fields": {"tool_calls": "[RepositoryToolCall]"},
                "types": {
                    "RepositoryToolCall": contract["types"]["RepositoryToolCall"]
                },
                "tool_call_example": {
                    "tool_calls": [
                        {
                            "id": "read-1",
                            "name": "get_source_excerpt",
                            "arguments": {"path": "<candidate path>"},
                        }
                    ]
                },
                "rules": "Request source inspection now. No architecture response until relevant implementation has been inspected.",
            }
        omitted = 0
        cap = min(
            context.limits.max_prompt_characters,
            int(budget.max_input_tokens_per_call / input_ratio(context.generate)) - 128,
        )
        while True:
            data = {
                "representation": representation,
                "tool_results": responses,
                "omitted_tool_results": omitted,
                "remaining_model_calls": maximum - state["calls"],
                "remaining_tool_calls": min(
                    context.limits.max_tool_calls, budget.max_tool_calls
                )
                - state["tool_calls"],
                "validation_errors": state["errors"],
                "required_action": "tool_calls: inspect implementation from different responsibilities"
                if need_source
                else "tool_calls OR architecture",
                "architect_inspected_file_count": len(inspected),
                "source_evidence_ledger": evidence_ledger,
                "draft_unit_names": [
                    item.get("name") for item in draft_units if isinstance(item, dict)
                ][:8],
            }
            text, sizes = measure_json(
                data,
                fields={"tool_results": "history", "validation_errors": "feedback"},
            )
            prompt = measured_prompt(
                [
                    (prompt_template("system"), "instructions"),
                    (prompt_template("architecture_criteria"), "instructions"),
                    (
                        prompt_template(
                            "correction" if state["errors"] else "investigation"
                        ),
                        "instructions",
                    ),
                    (
                        "\nOUTPUT_SCHEMA\n"
                        + json.dumps(
                            contract,
                            separators=(",", ":"),
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
                            },
                            separators=(",", ":"),
                        ),
                        "contracts",
                    ),
                    ("\nARCHITECTURE_DATA\n", "framing"),
                    (text, sizes),
                ],
                stage="investigation",
                objective_id="architecture",
                correction=bool(state["errors"]),
            )
            if len(prompt) <= cap:
                break
            reducible = next(
                (
                    key
                    for key in (
                        "relationship_signals",
                        "entrypoints",
                        "technologies",
                        "candidate_files",
                        "infrastructure_signals",
                        "configuration_files",
                    )
                    if len(representation.get(key, []))
                    > (2 if key == "candidate_files" else 0)
                ),
                None,
            )
            if reducible:
                representation[reducible].pop()
                omissions = representation.setdefault("prompt_metadata_omissions", {})
                omissions[reducible] = omissions.get(reducible, 0) + 1
            elif representation.get("orientation_guidance") is not None:
                representation["orientation_guidance"] = None
                representation.setdefault("prompt_metadata_omissions", {})[
                    "orientation_guidance"
                ] = 1
            elif responses:
                source_results = [
                    item
                    for item in responses
                    if json.loads(item["content"]).get("data", {}).get("content")
                    is not None
                ]
                protected = {item["signature"] for item in source_results[-2:]}
                removable = next(
                    (
                        index
                        for index, item in enumerate(responses)
                        if item["signature"] not in protected
                    ),
                    None,
                )
                if removable is None:
                    break
                responses.pop(removable)
                omitted += 1
            else:
                break
        event(context, "architecture_turn", turn=state["calls"] + 1, max_turns=maximum)
        submitted = False
        try:
            admit_request(context.generate, budget, prompt, "architecture")
            context.generate.request_guard = lambda text, attempts: admit_request(
                context.generate, budget, text, "architecture", attempts
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
        }
        try:
            value = normalize_record_arrays(
                parse_json_value(answer, 40000), ArchitectureTurn.model_json_schema()
            )
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
        for index, call in enumerate(state["pending"]):
            event(
                context,
                "tool_started",
                tool=call.name,
                target=call.arguments.get("path"),
            )
            response = context.tools.execute(
                call.name,
                call.arguments,
                tool_call_id=create_identifier(
                    "tool_call", "architecture", state["calls"], index
                ),
            )
            view = context.tools.model_view(response)
            if call.name == "get_source_excerpt" and response.status == "ok":
                view["data"].pop("content_hash", None)
                view["evidence"] = [
                    {
                        key: value
                        for key, value in record.items()
                        if key in {"id", "kind", "file_id"}
                    }
                    for record in view["evidence"]
                ]
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
        if state["architecture"] is not None:
            try:
                validate_report(context.tools, state["architecture"])
            except ValueError as error:
                errors = validation_feedback(error)
            else:
                return {"route": "finish", "errors": ()}
        if not state["corrected"] and state["calls"] < min(
            context.limits.max_model_calls,
            context.tools.context.input.budget.max_model_calls,
        ):
            event(context, "architecture_correction", errors=list(errors))
            return {"errors": errors, "corrected": True, "route": "inspect"}
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
        report = retain_valid_sections(context.tools, state["raw"])
        evidence = context.tools.retrieved_evidence
        inspected = tuple(
            sorted({record.file_id for record in evidence if record.kind == "source"})
        )
        complete = bool(
            report
            and report.organization
            and report.closest_architecture
            and report.explanation
            and report.closest_architecture.assessment.status != "unresolved"
            and report.explanation.status != "unresolved"
            and len(inspected) >= 2
            and not state["issues"]
            and not state["errors"]
        )
        status = "complete" if complete else "partial" if report else "failed"
        records = tuple(
            record
            for record in context.generate.measurements
            if record.objective_id == "architecture"
        )
        unknown = sum(record.unknown_usage_attempts for record in records)

        def total(field):
            return (
                sum(getattr(record, field) for record in records)
                if records
                and not unknown
                and all(getattr(record, field) is not None for record in records)
                else None
            )

        accounted, estimated = account_tokens(
            context.generate, context.tools.context.input.budget, "architecture"
        )
        usage = BudgetUsage(
            model_calls=state["calls"],
            tool_calls=context.tools.budget_usage.tool_calls,
            retrieved_characters=context.tools.budget_usage.retrieved_characters,
            elapsed_seconds=context.tools.context.elapsed_seconds,
            input_tokens=total("input_tokens"),
            output_tokens=total("output_tokens"),
            reported_input_tokens=sum(record.input_tokens or 0 for record in records),
            reported_output_tokens=sum(record.output_tokens or 0 for record in records),
            unknown_usage_attempts=unknown,
            provider_attempts=sum(record.attempts for record in records),
            provider_retries=sum(max(0, record.attempts - 1) for record in records),
            provider_wait_seconds=sum(record.wait_seconds for record in records),
            accounted_tokens=accounted,
            estimated_tokens=estimated,
            token_budget_exhausted=any(
                item.category == "token_budget_exhausted" for item in state["issues"]
            ),
        )
        limitations = (
            "Architecture describes inspected scope, not global compliance. Source-reference validation is not semantic validation.",
            "Infrastructure configuration is intended execution, not verified production deployment.",
        )
        if not complete:
            limitations += ("Incomplete or rejected sections remain unresolved.",)
        result = ArchitectureResult(
            snapshot_hash=context.tools.context.input.snapshot_hash,
            completion_status=status,
            architecture=report,
            citations=citations_for(context.tools, report),
            retrieved_evidence=evidence,
            inspected_file_ids=inspected,
            limitations=limitations,
            execution_issues=state["issues"],
            usage=usage,
            telemetry=execution_telemetry(records, context.tools.tool_measurements),
        )
        event(
            context,
            "finished",
            status=status,
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

    async def run(self, tools, orientation=None):
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
            },
            context=ArchitectureRuntime(
                tools, generate, self.limits, orientation, self.on_event
            ),
            config={"recursion_limit": 40},
        )
        return state["result"]
