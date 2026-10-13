"""Small functional-investigation LangGraph with deterministic planning/reporting."""

import asyncio
import json
from dataclasses import dataclass

from langchain_core.messages import RemoveMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from pydantic import Field

from ...benchmark.pacing import http_status
from ...services.repository_analysis.context import create_identifier
from .baseline_agent import incomplete_result, issue, notify
from .investigation import render_investigation
from .planning import PlanningLimits, admit_followups, select_deterministic_plan
from .schemas import (
    AnalysisContract,
    ArchitectureAnalysisInput,
    InvestigationObjective,
    InvestigationPlan,
    InvestigationResult,
    InvestigationTurn,
    OpenQuestion,
    ProjectAnalysisRunResult,
)
from .state import ProjectAnalysisState
from .telemetry import TextCallObserver
from .token_budget import (
    TokenBudgetExceeded,
    account_tokens,
    admit_request,
    input_ratio,
)
from .tools import RepositoryToolset
from .validation import (
    assemble_report,
    normalize_record_arrays,
    parse_json_value,
    salvage_finding,
    validate_finding,
    validate_report,
    validation_feedback,
)


class AnalysisLimits(AnalysisContract):
    max_prompt_characters: int = Field(default=20_000, ge=4000)
    max_response_characters: int = Field(default=40_000, ge=1000)
    max_model_calls_per_investigation: int = Field(default=6, ge=1)
    max_tool_calls_per_turn: int = Field(default=4, ge=1)
    max_context_findings: int = Field(default=3, ge=0)
    max_history_characters: int = Field(default=10_000, ge=0)


@dataclass(frozen=True)
class AnalysisRuntime:
    tools: RepositoryToolset
    generate: object
    planning_limits: PlanningLimits
    limits: AnalysisLimits
    on_event: object = None


def usage(state, runtime, **updates):
    measured = runtime.tools.budget_usage
    accounted, estimated = account_tokens(
        runtime.generate, runtime.tools.context.input.budget
    )
    values = {
        "tool_calls": measured.tool_calls,
        "retrieved_characters": measured.retrieved_characters,
        "elapsed_seconds": measured.elapsed_seconds,
        "accounted_tokens": accounted,
        "estimated_tokens": estimated,
        "token_budget_exhausted": accounted
        >= runtime.tools.context.input.budget.max_total_tokens,
    }
    if hasattr(runtime.generate, "usage_totals"):
        values.update(runtime.generate.usage_totals())
    else:
        measurements = getattr(runtime.generate, "measurements", ())
        values.update(
            reported_input_tokens=sum(
                record.input_tokens or 0 for record in measurements
            ),
            reported_output_tokens=sum(
                record.output_tokens or 0 for record in measurements
            ),
            unknown_usage_attempts=sum(
                record.unknown_usage_attempts for record in measurements
            ),
        )
    return state["budget_usage"].model_copy(update=values | updates)


def retain_incomplete(state, context, reason):
    if state.get("investigation_raw_result"):
        if state["validation_errors"]:
            reason += "; rejected fields: " + "; ".join(state["validation_errors"])
        return salvage_finding(
            context.tools,
            state["investigation_plan"],
            state["findings"],
            state["investigation_raw_result"],
            state["active_investigation"],
            state["investigation_evidence_ids"],
            reason,
        )
    return incomplete_result(state, reason)


def build_analysis_graph():
    def plan_node(state, runtime):
        context = runtime.context
        notify(context, "planning", mode="deterministic")
        try:
            plan = select_deterministic_plan(context.tools, context.planning_limits)
        except ValueError as error:
            return {
                "planning_status": "failed",
                "execution_issues": (
                    issue(state, "planning", "no_feasible_scope", str(error)),
                ),
            }
        notify(
            context,
            "planning_finished",
            status="ready",
            candidates=len(plan.candidates),
            objectives=len(plan.objectives),
            model_calls=0,
        )
        return {
            "investigation_plan": plan,
            "candidates": plan.candidates,
            "planning_decisions": plan.decisions,
            "investigation_queue": plan.objectives,
            "planning_status": "ready",
        }

    def select_node(state, runtime):
        context = runtime.context
        budget = context.tools.context.input.budget
        plan = state.get("investigation_plan") or InvestigationPlan()
        closed = {finding.investigation_id for finding in state["findings"]}
        queue = tuple(
            objective for objective in plan.objectives if objective.id not in closed
        )
        updated = usage(state, context)
        if (
            state["planning_status"] != "ready"
            or not queue
            or getattr(context.generate, "stopped", False)
            or updated.token_budget_exhausted
            or updated.model_calls >= budget.max_model_calls
            or updated.elapsed_seconds >= budget.max_elapsed_seconds
        ):
            notify(
                context,
                "investigation_queue_finished",
                accepted=len(closed),
                pending=len(queue),
                accounted_tokens=updated.accounted_tokens,
            )
            return {
                "active_investigation": None,
                "investigation_queue": queue,
                "budget_usage": updated,
            }
        objective = queue[0]
        notify(
            context,
            "investigation",
            number=updated.investigations_started + 1,
            planned=len(plan.objectives),
            objective=objective.objective,
            priority=objective.priority_tier,
        )
        return {
            "active_investigation": objective,
            "investigation_queue": queue[1:],
            "investigation_messages": [
                RemoveMessage(id=message.id)
                for message in state["investigation_messages"]
            ],
            "investigation_model_calls": 0,
            "finding_corrections": 0,
            "validation_errors": (),
            "investigation_evidence_ids": (),
            "query_ledger": (),
            "investigation_raw_result": None,
            "investigation_draft": None,
            "pending_tool_calls": (),
            "investigation_status": "pending",
            "budget_usage": updated.model_copy(
                update={"investigations_started": updated.investigations_started + 1}
            ),
        }

    async def investigate_node(state, runtime):
        context = runtime.context
        budget = context.tools.context.input.budget
        failure = None
        updated = usage(state, context)
        if (
            state["investigation_model_calls"]
            >= context.limits.max_model_calls_per_investigation
        ):
            failure = "Investigation turn limit reached."
        elif (
            updated.model_calls >= budget.max_model_calls
            or updated.elapsed_seconds >= budget.max_elapsed_seconds
        ):
            failure = "Model-call or elapsed-time budget exhausted."
        elif getattr(context.generate, "stopped", False):
            failure = "Provider unavailable after terminal failure."
        if failure:
            return {
                "investigation_draft": retain_incomplete(state, context, failure),
                "investigation_status": "validate",
                "budget_usage": updated,
            }
        cap = min(
            context.limits.max_prompt_characters,
            int(budget.max_input_tokens_per_call / input_ratio(context.generate)) - 128,
        )
        prompt = render_investigation(state, context, cap)
        objective_id = state["active_investigation"].id
        try:
            admit_request(context.generate, budget, prompt, objective_id)
        except TokenBudgetExceeded as error:
            notify(
                context,
                "token_budget_stop",
                reason=str(error),
                accounted_tokens=updated.accounted_tokens,
            )
            return {
                "investigation_draft": retain_incomplete(state, context, str(error)),
                "investigation_status": "validate",
                "budget_usage": updated,
                "execution_issues": (
                    issue(state, "investigation", "token_budget_exhausted", str(error)),
                ),
            }
        context.generate.request_guard = lambda text, attempts: admit_request(
            context.generate, budget, text, objective_id, attempts
        )
        notify(
            context,
            "investigation_turn",
            turn=state["investigation_model_calls"] + 1,
            max_turns=context.limits.max_model_calls_per_investigation,
            accounted_tokens=updated.accounted_tokens,
            max_total_tokens=budget.max_total_tokens,
        )
        update = {
            "investigation_model_calls": state["investigation_model_calls"] + 1,
            "budget_usage": updated.model_copy(
                update={"model_calls": updated.model_calls + 1}
            ),
        }
        try:
            answer = await asyncio.wait_for(
                context.generate(prompt),
                max(
                    0,
                    budget.max_elapsed_seconds - context.tools.context.elapsed_seconds,
                ),
            )
        except Exception as error:  # noqa: BLE001 - provider-specific boundary; cancellation propagates
            category = getattr(
                error,
                "category",
                "model_timeout"
                if isinstance(error, TimeoutError)
                else f"model_error:{type(error).__name__}",
            )
            if http_status(error):
                category += f":http_{http_status(error)}"
            return update | {
                "investigation_draft": retain_incomplete(state, context, category),
                "investigation_status": "validate",
                "execution_issues": (
                    issue(state, "investigation", category, category),
                ),
            }
        raw = None
        try:
            value = parse_json_value(answer, context.limits.max_response_characters)
            value = normalize_record_arrays(
                value, InvestigationTurn.model_json_schema()
            )
            raw = value.get("result") if isinstance(value, dict) else None
            turn = InvestigationTurn.model_validate(value)
            if turn.result and turn.followups:
                finding = turn.result
                requests = tuple(
                    InvestigationObjective(
                        id=create_identifier(
                            "investigation", "followup", objective_id, request.question
                        ),
                        project_id=state["active_investigation"].project_id,
                        objective=request.question,
                        questions=(request.question,),
                        seed_entity_ids=request.seed_entity_ids,
                        report_sections=state["active_investigation"].report_sections,
                        selection_reason="Material unanswered question from source investigation.",
                        priority_tier="material_uncertainty",
                        expected_deliverable="Resolve the question with inspected source or preserve explicit uncertainty.",
                        completion_criteria=("Inspect relevant implementation.",),
                        origin_finding_ids=(finding.id,),
                        blocked_investigation_ids=request.blocked_investigation_ids,
                    )
                    for request in turn.followups
                )
                questions = tuple(
                    OpenQuestion(
                        id=create_identifier(
                            "question", objective_id, request.question
                        ),
                        question=request.question,
                        reason="Material source-investigation follow-up requested.",
                        entity_ids=request.seed_entity_ids,
                        investigation_id=objective_id,
                    )
                    for request in turn.followups
                )
                finding = InvestigationResult.model_validate(
                    finding.model_dump()
                    | {
                        "suggested_followups": (
                            *finding.suggested_followups,
                            *requests,
                        ),
                        "open_questions": (*finding.open_questions, *questions),
                    }
                )
                turn = turn.model_copy(update={"result": finding})
            if len(turn.tool_calls) > context.limits.max_tool_calls_per_turn:
                raise ValueError("Too many tool calls; use at most four per turn.")
            if turn.result and turn.result.id != create_identifier(
                "finding", objective_id
            ):
                raise ValueError(
                    "result.id must equal the supplied finding_id; investigation_id must equal objective.id."
                )
            return update | {
                "investigation_draft": turn.result,
                "investigation_raw_result": raw,
                "pending_tool_calls": turn.tool_calls,
                "investigation_status": "tools" if turn.tool_calls else "validate",
                "validation_errors": (),
            }
        except ValueError as error:
            if (
                raw is not None
                and raw == state.get("investigation_raw_result")
                and state["validation_errors"]
            ):
                update["finding_corrections"] = budget.max_finding_corrections
            return update | {
                "investigation_draft": None,
                "investigation_raw_result": raw,
                "investigation_status": "validate",
                "validation_errors": validation_feedback(error),
            }

    def tools_node(state, runtime):
        context = runtime.context
        messages, identifiers, ledger = (
            [],
            list(state["investigation_evidence_ids"]),
            list(state.get("query_ledger", ())),
        )
        for ordinal, call in enumerate(state["pending_tool_calls"]):
            call_id = create_identifier(
                "tool_call",
                state["active_investigation"].id,
                state["budget_usage"].model_calls,
                ordinal,
            )
            notify(
                context,
                "tool_started",
                tool=call.name,
                target={
                    key: str(value)[:200]
                    for key, value in call.arguments.items()
                    if key in {"path", "symbol_id", "path_prefix", "name"}
                },
            )
            response = context.tools.execute(
                call.name, call.arguments, tool_call_id=call_id
            )
            view = context.tools.model_view(response)
            messages.append(
                ToolMessage(
                    id=create_identifier("message", call_id),
                    tool_call_id=call.id,
                    content=json.dumps(view),
                )
            )
            identifiers.extend(record.id for record in response.evidence)
            ledger.append(
                {
                    "tool": call.name,
                    "status": response.status,
                    "target": {
                        key: str(value)[:160]
                        for key, value in call.arguments.items()
                        if key
                        in {
                            "path",
                            "symbol_id",
                            "path_prefix",
                            "start_line",
                            "end_line",
                        }
                    },
                }
            )
            notify(
                context,
                "tool_finished",
                tool=call.name,
                status=response.status,
                cache_hit=context.tools.last_cache_hit,
                error=response.error.message if response.error else None,
                evidence_records=len(response.evidence),
                tool_calls=context.tools.budget_usage.tool_calls,
            )
        return {
            "investigation_messages": messages,
            "investigation_evidence_ids": tuple(dict.fromkeys(identifiers)),
            "query_ledger": tuple(ledger),
            "pending_tool_calls": (),
            "budget_usage": usage(state, context),
            "investigation_status": "pending",
        }

    def validate_node(state, runtime):
        context = runtime.context
        draft = state.get("investigation_draft")
        errors = state["validation_errors"]
        notify(context, "finding_validation")
        if draft is not None:
            try:
                validate_finding(
                    context.tools,
                    state["investigation_plan"],
                    state["findings"],
                    draft,
                    state["active_investigation"],
                    state["investigation_evidence_ids"],
                )
            except ValueError as error:
                errors = validation_feedback(error)
            else:
                return accept(state, context, draft)
        updated = usage(state, context)
        if (
            state["finding_corrections"]
            < context.tools.context.input.budget.max_finding_corrections
            and state["investigation_model_calls"]
            < context.limits.max_model_calls_per_investigation
            and not updated.token_budget_exhausted
        ):
            notify(
                context,
                "finding_correction",
                attempt=state["finding_corrections"] + 1,
                errors=list(errors),
            )
            return {
                "finding_corrections": state["finding_corrections"] + 1,
                "validation_errors": errors,
                "investigation_status": "correcting",
            }
        reason = "Finding validation failed: " + "; ".join(errors)
        retained = salvage_finding(
            context.tools,
            state["investigation_plan"],
            state["findings"],
            state.get("investigation_raw_result"),
            state["active_investigation"],
            state["investigation_evidence_ids"],
            reason,
        )
        validate_finding(
            context.tools,
            state["investigation_plan"],
            state["findings"],
            retained,
            state["active_investigation"],
            state["investigation_evidence_ids"],
        )
        notify(
            context,
            "finding_incomplete",
            reason=reason,
            retained_records=sum(
                len(getattr(retained, name))
                for name in ("components", "flows", "claims")
            ),
        )
        return accept(state, context, retained) | {
            "execution_issues": (
                issue(state, "finding_validation", "invalid_findings", reason),
            )
        }

    def accept(state, context, finding):
        plan = state["investigation_plan"]
        issues = ()
        if finding.suggested_followups and finding.open_questions:
            try:
                plan = admit_followups(
                    context.tools,
                    plan,
                    (*state["findings"], finding),
                    finding.suggested_followups,
                    usage=usage(state, context),
                )
            except ValueError as error:
                issues = (
                    issue(state, "followup", "invalid_followup", str(error)[:500]),
                )
        notify(
            context,
            "finding_accepted",
            status=finding.status,
            components=len(finding.components),
            flows=len(finding.flows),
            claims=len(finding.claims),
            open_questions=len(finding.open_questions),
        )
        return {
            "findings": (finding,),
            "open_questions": finding.open_questions,
            "investigation_status": "accepted",
            "investigation_plan": plan,
            "candidates": plan.candidates,
            "planning_decisions": plan.decisions,
            "execution_issues": issues,
            "validation_errors": (),
            "budget_usage": usage(state, context),
        }

    def finalize_node(state, runtime):
        context = runtime.context
        plan = state.get("investigation_plan") or InvestigationPlan()
        report = assemble_report(context.tools, plan, state["findings"])
        issues = state["execution_issues"]
        substantive = any(
            report.project_identification
            or report.functional_components
            or report.main_flows
            or report.integrations_and_state
            or report.testing
            or report.claims
        )
        if substantive:
            validate_report(context.tools, plan, state["findings"], report)
        else:
            issues = (
                *issues,
                issue(
                    state,
                    "finalization",
                    "no_valid_findings",
                    "No substantive validated findings are available.",
                ),
            )
        coverage = report.investigation_coverage
        updated = usage(state, context)
        status = (
            "failed"
            if not substantive
            else "partial"
            if coverage.incomplete_investigation_ids
            or coverage.pending_investigation_ids
            or issues
            else "complete"
        )
        result = ProjectAnalysisRunResult(
            completion_status=status,
            investigation_plan=plan,
            validated_findings=state["findings"],
            retrieved_evidence=context.tools.retrieved_evidence,
            report=report if substantive else None,
            investigation_coverage=coverage,
            unresolved_questions=report.open_questions,
            execution_issues=issues,
            usage=updated,
            telemetry=context.generate.telemetry(context.tools.tool_measurements),
        )
        context.tools.context.validate_result(result)
        if result.report:
            context.tools.context.validate_architecture_input(
                ArchitectureAnalysisInput.from_result(result)
            )
        notify(
            context,
            "finished",
            status=status,
            model_calls=updated.model_calls,
            accounted_tokens=updated.accounted_tokens,
        )
        return {"result": result, "completion_status": status, "budget_usage": updated}

    graph = StateGraph(ProjectAnalysisState, context_schema=AnalysisRuntime)
    for name, node in {
        "select_scope": plan_node,
        "select_investigation": select_node,
        "investigate_target": investigate_node,
        "execute_repository_tools": tools_node,
        "validate_findings": validate_node,
        "finalize_analysis": finalize_node,
    }.items():
        graph.add_node(name, node)
    graph.add_edge(START, "select_scope")
    graph.add_edge("select_scope", "select_investigation")
    graph.add_conditional_edges(
        "select_investigation",
        lambda state: (
            "investigate_target"
            if state.get("active_investigation")
            else "finalize_analysis"
        ),
    )
    graph.add_conditional_edges(
        "investigate_target",
        lambda state: (
            "execute_repository_tools"
            if state["investigation_status"] == "tools"
            else "validate_findings"
        ),
    )
    graph.add_edge("execute_repository_tools", "investigate_target")
    graph.add_conditional_edges(
        "validate_findings",
        lambda state: (
            "investigate_target"
            if state["investigation_status"] == "correcting"
            else "select_investigation"
        ),
    )
    graph.add_edge("finalize_analysis", END)
    return graph.compile()


class ProjectAnalysisAgent:
    def __init__(
        self, model, *, limits=None, planning_limits=None, generate=None, on_event=None
    ):
        self.model = model
        self.generate = generate or model.generate
        self.limits = limits or AnalysisLimits()
        self.planning_limits = planning_limits or PlanningLimits()
        self.on_event = on_event
        self.graph = build_analysis_graph()

    async def run(self, tools: RepositoryToolset) -> ProjectAnalysisRunResult:
        generate = (
            self.generate
            if hasattr(self.generate, "telemetry")
            else TextCallObserver(self.generate)
        )
        budget = tools.context.input.budget
        state = await self.graph.ainvoke(
            tools.initial_state(),
            context=AnalysisRuntime(
                tools, generate, self.planning_limits, self.limits, self.on_event
            ),
            config={
                "recursion_limit": 20
                + 4 * budget.max_model_calls
                + 4 * budget.max_investigations
            },
        )
        return state["result"]
