"""Dispatch only: isolate invocations and retain outputs for future collection."""

import asyncio
from time import monotonic
from typing import Any

from pydantic import TypeAdapter

from server.agent_services.budgeting.shared_tokens import SharedTokenBudget
from server.agent_services.budgeting.timing import cancel_bounded, within_deadline
from server.blackboard.identity import AuditIdentity
from server.blackboard.publication import publication_for
from server.contracts.audit import Consumption
from server.infrastructure.llm.retry import RequestPacer
from server.infrastructure.tracing import LangSmithTracingBackend
from server.runtimes.coordination.execution import CoordinatorExecution
from server.runtimes.coordination.synthesis import stable_id
from server.runtimes.invocation_reporting import observe_invocation
from server.runtimes.repository.context import RepositoryContext
from server.runtimes.repository.schemas import ExecutionBudget
from server.runtimes.repository.tools import RepositoryToolset
from server.services.execution_failures import (
    ExecutionValidationError,
    failure_from_exception,
)

from .registry import registered_coordinators
from .schemas import AuditPlan, CoordinatorExecutionRecord
from .validation import validate_plan


def total_consumption(values):
    return Consumption(**{field: sum(getattr(value, field) for value in values)
        for field in ("model_calls", "tool_calls", "accounted_tokens", "estimated_tokens")},
        model_calls_estimated=any(value.model_calls_estimated for value in values))


def validate_output(result, request, state):
    if any(result.get(key) != state[key] for key in ("repository_id", "commit", "snapshot_hash")):
        raise ExecutionValidationError("repository_provenance_mismatch", "Coordinator output does not match the assigned repository/revision.")
    if "request" in result:
        matches = result["request"] == request
    else:
        matches = result.get("objective") == request["objective"] and result.get("targets") == request["targets"]
    if not matches:
        raise ExecutionValidationError("assignment_provenance_mismatch", "Coordinator output does not match its delegated request.")


def assignment_identifier(snapshot_hash, index, assignment):
    return stable_id("coordinator-assignment", [snapshot_hash, index, assignment.model_dump(mode="json")])


def coordinator_request(spec, request, assignment):
    values = {"objective": assignment.objective, "original_objective": request.objective,
        "targets": list(assignment.scope), "constraints": list(assignment.constraints), "repository_context": request.repository_context}
    if "documented_architecture" in spec.request_class.model_fields:
        values["documented_architecture"] = request.documented_architecture
    if "investigator_selection" in spec.request_class.model_fields:
        selection = getattr(request, "maintainability_selection", None)
        values["investigator_selection"] = selection.get(assignment.coordinator_id) if selection else None
    return spec.request_class(**values)


async def delegate_coordinators(execution, state):
    execution.logger.info("maintainability manager node=delegate_coordinators")
    prior = Consumption.model_validate(state.get("consumption", Consumption()))
    repository = execution.tools.accessible_snapshot.repository
    records, prepared, seen = {}, [], set()
    try:
        if any(state.get(key) != getattr(repository, "name" if key == "repository_id" else key)
            for key in ("repository_id", "commit", "snapshot_hash")) or state["request"] != execution.request:
            raise ExecutionValidationError("repository_provenance_mismatch", "Manager state does not match its request/repository revision.")
        raw_plan = state["plan"]
        plan = AuditPlan.model_validate(raw_plan.model_dump() if isinstance(raw_plan, AuditPlan) else raw_plan)
    except (ValueError, KeyError) as error:
        failure = failure_from_exception(error, "validate_delegation", AuditPlan)
        return {"coordinator_results": [], "delegation_status": "failed", "consumption": prior,
            "termination_reason": state.get("termination_reason") or "invalid_delegation", "limitations": [*state.get("limitations", []), failure.summary]}
    specs = registered_coordinators() if plan.assignments else {}
    available = {item.id for item in state["coordinator_catalog"]}
    catalog = {key: spec.capability for key, spec in specs.items() if key in available}
    paths = {file.path for file in execution.tools.accessible_snapshot.files}
    for index, assignment in enumerate(plan.assignments):
        identifier = assignment_identifier(state["snapshot_hash"], index, assignment)
        record = CoordinatorExecutionRecord(assignment_id=identifier, assignment=assignment, status="skipped")
        try:
            key = assignment.model_dump_json()
            if key in seen:
                raise ExecutionValidationError("duplicate_assignment", "Identical assignment was already scheduled.")
            seen.add(key)
            if assignment.coordinator_id not in catalog:
                raise ExecutionValidationError("unknown_coordinator", "Coordinator is not registered and available in this plan's catalog.")
            validated = validate_plan(plan.model_copy(update={"assignments": [assignment]}), state["request"], catalog, paths).assignments[0]
            spec = specs[assignment.coordinator_id]
            request = coordinator_request(spec, state["request"], validated)
            record = record.model_copy(update={"request": request.model_dump(mode="json")})
            prepared.append((index, record, spec, request))
        except (ValueError, KeyError) as error:
            if type(error) is ValueError:
                error = ExecutionValidationError("invalid_assignment", "Coordinator assignment failed deterministic scope validation.")
            records[index] = record.model_copy(update={"failure": failure_from_exception(error, "validate_assignment")})

    from server.agent_services.budgeting.policy import budgets_enabled

    limits, global_budget = execution.config.invocation_limits, execution.tools.context.input.budget
    calls = max(0, min(execution.config.max_model_calls, global_budget.max_model_calls) - prior.model_calls)
    tools = max(0, min(execution.config.max_tool_calls, global_budget.max_tool_calls) - prior.tool_calls)
    ledger = execution.tools.token_budget
    token_exhausted = False
    if ledger is None:
        ledger = SharedTokenBudget(execution.token_limit)
        if prior.accounted_tokens:
            reservation = ledger.reserve(prior.accounted_tokens)
            token_exhausted = reservation is None
            if reservation is not None:
                reservation.settle(prior.accounted_tokens)
    semaphore = asyncio.Semaphore(execution.config.max_parallel)
    pacer = RequestPacer(interval=execution.config.investigation_start_interval_seconds)
    tracing = getattr(execution, "tracing", None) or LangSmithTracingBackend()
    tasks = []

    async def invoke(record, spec, request, budget, tool_allowance):
        async with semaphore:
            execution.timing.check_cancellation()
            started, child, timing = monotonic(), None, None
            scope, result, usage = ledger.fork(), None, Consumption()
            failure, status, limitations = None, "failed", []
            try:
                async def start_slot():
                    async with pacer.lock:
                        await pacer.wait()
                        pacer.completed_attempt()
                await within_deadline(start_slot(), execution.timing)
                timing = execution.timing.fork(min(limits.timeout_seconds, execution.remaining_seconds()),
                    label=record.assignment.coordinator_id, invocation_id=record.assignment_id,
                    max_wall_time_seconds=limits.max_wall_time_seconds, cancellation_grace_seconds=limits.cancellation_grace_seconds)
                child = RepositoryToolset(RepositoryContext(execution.tools.context.snapshot.model_copy(deep=True),
                    execution.tools.context.input.model_copy(deep=True, update={"budget": budget})),
                    workspace_root=execution.tools.policy.workspace_root, limits=execution.tools.limits.model_copy(deep=True),
                    token_budget=scope, timing=timing, retrieval_budget=execution.tools.retrieval_budget)
                config = spec.agent_class.config_type.model_validate(limits.model_dump(exclude={"tools", "prompts"}) | {
                    "max_model_calls": budget.max_model_calls, "max_tool_calls": tool_allowance})
                owner = getattr(execution, "owner", None)
                models = getattr(owner, "agent_models", {})
                outputs = getattr(owner, "agent_output_limits", {})
                if record.assignment.coordinator_id in outputs:
                    config = type(config).model_validate(config.model_dump() | {"max_output_tokens": outputs[record.assignment.coordinator_id]})
                coordinator = spec.agent_class(models.get(record.assignment.coordinator_id, execution.model), config,
                    provider_pacer=execution.provider_pacer, tracing_backend=tracing)
                coordinator.agent_models = models
                coordinator.agent_output_limits = outputs
                publication = publication_for(owner) if owner is not None else None
                if publication is not None:
                    coordinator.blackboard = publication.blackboard
                    coordinator.audit_identity = AuditIdentity(run_id=publication.run_id, invocation_id=record.assignment_id)
                    coordinator._blackboard_publication = publication.child(record.assignment_id, record.assignment.coordinator_id)
                # If a child raises without returning usage, retain a conservative
                # call estimate, as the shared coordinator runtime does.
                usage = Consumption(model_calls=budget.max_model_calls, model_calls_estimated=True)
                value = await observe_invocation(within_deadline(within_deadline(tracing.wrap_stage(
                    coordinator.run(child, request.model_copy(deep=True)), name="delegate_coordinator",
                    assignment_id=record.assignment_id, coordinator_id=record.assignment.coordinator_id,
                    repository_id=state["repository_id"], commit=state["commit"], snapshot_hash=state["snapshot_hash"]), timing), execution.timing),
                    agent_id=record.assignment.coordinator_id, invocation_id=record.assignment_id,
                    run_id=execution.audit_identity.run_id if getattr(execution, "audit_identity", None) else "unscoped")
                result = TypeAdapter(Any).dump_python(value, mode="json")
                if not isinstance(result, dict):
                    raise ExecutionValidationError("result_contract_invalid", "Coordinator did not return a structured result.")
                raw_usage = result.get("consumption")
                if not isinstance(raw_usage, dict) or any(type(raw_usage.get(field)) is not int or raw_usage[field] < 0
                    for field in ("model_calls", "tool_calls", "accounted_tokens", "estimated_tokens")):
                    raise ExecutionValidationError("result_consumption_invalid", "Coordinator did not return valid consumption metrics.")
                usage = Consumption.model_validate(raw_usage)
                limitations = TypeAdapter(list[str]).validate_python(result.get("limitations", []))
                validate_output(result, record.request, state)
                if spec.result_kind == "planning" and result.get("plan") is None:
                    raise ExecutionValidationError("coordinator_execution_failed", "Coordinator produced no plan; its unsuccessful output is preserved.")
                if result.get("status") in {"failed", "timeout"}:
                    raise ExecutionValidationError("coordinator_execution_failed", "Coordinator returned an unsuccessful execution; its output is preserved.")
                status = "completed" if spec.result_kind == "assessment" and result.get("status") == "completed" else "partial"
                if spec.result_kind == "planning":
                    limitations.append("Coordinator currently implements planning only; no final assessment was produced.")
            except Exception as error:  # noqa: BLE001 - child boundary; cancellation propagates
                failure = failure_from_exception(error, "delegate_coordinator")
                status = "timeout" if isinstance(error, TimeoutError) else "failed"
            finally:
                if timing is not None:
                    timing.close()
            usage = usage.model_copy(update={"accounted_tokens": max(usage.accounted_tokens, scope.used),
                "estimated_tokens": max(usage.estimated_tokens, scope.estimated),
                "tool_calls": max(usage.tool_calls, child.budget_usage.tool_calls if child else 0)})
            evidence = []
            try:
                evidence = CoordinatorExecution.references(child) if child else []
            except Exception as error:  # noqa: BLE001 - preserve siblings if child evidence is invalid
                failure, status = failure_from_exception(error, "retain_child_evidence"), "failed"
            execution.logger.info("coordinator_delegated assignment=%s coordinator=%s status=%s", record.assignment_id,
                record.assignment.coordinator_id, status)
            return record.model_copy(update={"budget": budget, "status": status, "result": result, "failure": failure,
                "consumption": usage, "limitations": limitations, "duration_seconds": monotonic() - started,
                "evidence": evidence})

    for offset, (index, record, spec, request) in enumerate(prepared):
        count = len(prepared) - offset
        reserved_calls = min(limits.max_model_calls, calls // count) if budgets_enabled() else limits.max_model_calls
        reserved_tools = min(limits.max_tool_calls, tools // count) if budgets_enabled() else limits.max_tool_calls
        if budgets_enabled() and (token_exhausted or offset >= execution.config.max_invocations or reserved_calls < 4 or execution.remaining_seconds() <= 0):
            error = ExecutionValidationError("execution_budget_exhausted", "Coordinator was not started: invocation, call or time budget exhausted.")
            records[index] = record.model_copy(update={"failure": failure_from_exception(error, "reserve_coordinator")})
            continue
        budget = ExecutionBudget(max_model_calls=reserved_calls, max_tool_calls=max(1, reserved_tools),
            max_total_tokens=min(limits.max_total_tokens, ledger.limit), max_tokens_per_objective=min(limits.max_total_tokens, ledger.limit),
            max_input_tokens_per_call=min(global_budget.max_input_tokens_per_call, limits.max_context_characters // 2),
            max_output_tokens_per_call=min(global_budget.max_output_tokens_per_call, limits.max_output_tokens),
            max_elapsed_seconds=min(execution.timing.wall_remaining, global_budget.max_elapsed_seconds),
            max_retrieved_characters=global_budget.max_retrieved_characters)
        calls, tools = calls - reserved_calls, tools - reserved_tools
        tasks.append((index, asyncio.create_task(invoke(record, spec, request, budget, reserved_tools))))
    try:
        values = await asyncio.gather(*(task for _, task in tasks))
        records.update({index: value for (index, _), value in zip(tasks, values, strict=True)})
    finally:
        await asyncio.gather(*(cancel_bounded(task, execution.config.cancellation_grace_seconds) for _, task in tasks if not task.done()))
    ordered = [records[index] for index in sorted(records)]
    status = ("not_required" if not ordered else "completed" if all(record.status == "completed" for record in ordered)
        else "partial" if any(record.status in {"completed", "partial"} for record in ordered) else "failed")
    diagnostics = [f"{record.assignment_id}/{record.assignment.coordinator_id}: {message}" for record in ordered
        for message in [*record.limitations, *([record.failure.summary] if record.failure else [])]]
    return {"coordinator_results": ordered, "delegation_status": status,
        "consumption": total_consumption([prior, *(record.consumption for record in ordered)]),
        "limitations": list(dict.fromkeys([*state.get("limitations", []), *diagnostics])),
        "termination_reason": state.get("termination_reason", "") if status in {"completed", "not_required"} else f"coordinator_delegation_{status}"}
