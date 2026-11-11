"""Dispatch-only tests, using real request/tool interfaces and simulated children."""

import asyncio
from copy import deepcopy
from typing import ClassVar

import pytest
from test_architecture_boundary_planning import tools_for
from test_maintainability_v2_plan_audit import Model

from config.agents import InvestigationConfig
from server.agents.maintainability.v2.manager import (
    MaintainabilityManager,
    MaintainabilityRequest,
    delegation,
)
from server.agents.maintainability.v2.manager.config import MaintainabilityConfig
from server.agents.maintainability.v2.manager.execution import (
    MaintainabilityManagerExecution,
)
from server.agents.maintainability.v2.manager.registry import (
    CoordinatorSpec,
    registered_coordinators,
)
from server.agents.maintainability.v2.manager.schemas import (
    AuditPlan,
    CoordinatorAssignment,
    CoordinatorCapability,
    CoordinatorExecutionRecord,
)
from server.agents.maintainability.v2.modularity.coordinator import (
    AssessmentRequest,
    ModularityConfig,
)
from server.contracts.audit import Consumption


class Tracing:
    def __init__(self):
        self.events = []

    async def wrap_stage(self, operation, **metadata):
        self.events.append(metadata)
        return await operation


@pytest.fixture
def tools(tmp_path):
    return tools_for(tmp_path, {"Checkout/api.py": "class API: pass\n", "Inventory/api.py": "class Inventory: pass\n"})


def assignment(key="one", **changes):
    return CoordinatorAssignment(**({"coordinator_id": key, "objective": "Examine the requested Checkout concern exactly.",
        "scope": ["Checkout"], "constraints": ["Retain uncertainty."], "rationale": "Original request asks about Checkout."} | changes))


def output(tools, delegated_request, **changes):
    repo = tools.accessible_snapshot.repository
    return {"repository_id": repo.name, "commit": repo.commit, "snapshot_hash": repo.snapshot_hash,
        "request": delegated_request.model_dump(mode="json"), "status": "completed", "plan": {"objective": delegated_request.objective},
        "limitations": ["Child limitation."], "consumption": Consumption(model_calls=1, accounted_tokens=30).model_dump(),
        "nested_complete_payload": {"findings": [], "extra_fields": [1, {"retained": True}]}} | changes


def spec(key="one", run=None, *, kind="assessment"):
    class SimulatedCoordinator:
        config_type = ModularityConfig
        instances: ClassVar[list] = []

        def __init__(self, model, config, *, provider_pacer, tracing_backend):
            self.config, self.model = config, model
            self.instances.append(self)

        async def run(self, tools, request):
            self.tools, self.request = tools, request
            return await run(self, tools, request) if run else output(tools, request)

    return CoordinatorSpec(SimulatedCoordinator, AssessmentRequest,
        CoordinatorCapability(id=key, agent_name=key, capability="Registered test capability.", constraints=["Read only."]), kind)


def execution(tools, monkeypatch, specs, assignments, **config):
    monkeypatch.setattr(delegation, "registered_coordinators", lambda: specs)
    model = Model(RuntimeError("The Manager must not call the LLM to delegate."))
    request = MaintainabilityRequest(objective="Original Checkout maintainability request.", targets=["Checkout"],
        constraints=["Do not inspect Inventory."], repository_context="Original repository context.")
    runtime = MaintainabilityManagerExecution(model, MaintainabilityConfig(provider_request_interval_seconds=0,
        investigation_start_interval_seconds=0, **config), tools, request)
    runtime.tracing = Tracing()
    state = runtime.initial_state() | {"coordinator_catalog": [value.capability for value in specs.values()],
        "plan": AuditPlan(objective=request.objective, assignments=assignments), "limitations": ["Prior limitation."]}
    return runtime, state, model


def test_single_assignment_preserves_inputs_output_provenance_and_usage(tools, monkeypatch):
    registered = spec()
    runtime, state, model = execution(tools, monkeypatch, {"one": registered}, [assignment()])
    state["consumption"] = Consumption(model_calls=1, accounted_tokens=12)
    before = deepcopy(state)
    update = asyncio.run(runtime.delegate_coordinators(state))
    record = update["coordinator_results"][0]
    child = registered.agent_class.instances[0]
    assert state == before and not model.contexts
    assert record.assignment == assignment() and record.status == "completed"
    assert child.request.objective == assignment().objective
    assert child.request.original_objective == state["request"].objective
    assert child.request.targets == assignment().scope
    assert child.request.repository_context == state["request"].repository_context
    assert set(child.request.constraints) == {"Do not inspect Inventory.", "Read only.", "Retain uncertainty."}
    assert child.tools.context.snapshot.repository == tools.context.snapshot.repository
    assert record.result == output(child.tools, child.request)
    assert record.request == child.request.model_dump(mode="json")
    assert record.consumption.accounted_tokens == 30 and record.limitations == ["Child limitation."]
    assert update["consumption"].model_calls == 2 and update["consumption"].accounted_tokens == 42
    assert update["delegation_status"] == "completed"
    assert runtime.tracing.events[0]["assignment_id"] == record.assignment_id
    assert runtime.tracing.events[0]["coordinator_id"] == record.assignment.coordinator_id
    assert CoordinatorExecutionRecord.model_validate_json(record.model_dump_json()) == record


def test_multiple_assignments_are_concurrent_isolated_and_stably_ordered(tools, monkeypatch):
    entered = []

    async def scenario():
        both_entered = asyncio.Event()

        async def run(child, child_tools, request):
            entered.append(child)
            if len(entered) == 2:
                both_entered.set()
            await asyncio.wait_for(both_entered.wait(), timeout=1)
            if child is entered[0]:
                child_tools._query_cache["child-local"] = "isolated state"
                await asyncio.sleep(0.01)  # First assignment completes last.
            else:
                assert child_tools.context.snapshot.files and not child_tools._query_cache
            return output(child_tools, request)

        specs = {"one": spec("one", run), "two": spec("two", run)}
        runtime, state, model = execution(tools, monkeypatch, specs, [assignment("one"), assignment("two")], max_parallel=2)
        update = await runtime.delegate_coordinators(state)
        assert [record.assignment.coordinator_id for record in update["coordinator_results"]] == ["one", "two"]
        assert len({record.assignment_id for record in update["coordinator_results"]}) == 2
        assert entered[0].tools is not entered[1].tools and entered[0].request is not entered[1].request
        assert entered[0].tools._query_cache is not entered[1].tools._query_cache
        assert entered[0].tools.token_budget is not entered[1].tools.token_budget
        assert entered[0].tools.token_budget.root is entered[1].tools.token_budget.root
        assert tools.context.snapshot.files and not tools._query_cache and not model.contexts
        assert update["consumption"].model_calls == 2, str([(record.status, record.failure) for record in update["coordinator_results"]])

    asyncio.run(scenario())


def test_empty_plan_does_not_resolve_or_invoke_children_or_llm(tools, monkeypatch):
    runtime, state, model = execution(tools, monkeypatch, {}, [])

    def forbidden():
        raise AssertionError("No registry resolution for an empty plan.")

    monkeypatch.setattr(delegation, "registered_coordinators", forbidden)
    update = asyncio.run(runtime.delegate_coordinators(state))
    assert update["coordinator_results"] == [] and update["delegation_status"] == "not_required"
    assert update["consumption"] == state["consumption"] and not model.contexts


def test_unknown_coordinator_retains_individual_failure_and_successful_sibling(tools, monkeypatch):
    runtime, state, _ = execution(tools, monkeypatch, {"one": spec()}, [assignment("missing"), assignment()])
    update = asyncio.run(runtime.delegate_coordinators(state))
    missing, success = update["coordinator_results"]
    assert missing.status == "skipped" and missing.failure.stage == "validate_assignment"
    assert missing.failure.code == "unknown_coordinator"
    assert success.status == "completed" and success.result
    assert update["delegation_status"] == "partial" and update["termination_reason"] == "coordinator_delegation_partial"


def test_partial_failure_preserves_success_and_failed_usage_without_leaking_payload(tools, monkeypatch):
    async def fail(child, child_tools, request):
        reservation = child_tools.token_budget.reserve(90)
        reservation.settle(70)
        raise RuntimeError("secret provider payload")

    runtime, state, _ = execution(tools, monkeypatch, {"one": spec(), "two": spec("two", fail)}, [assignment(), assignment("two")])
    update = asyncio.run(runtime.delegate_coordinators(state))
    success, failure = update["coordinator_results"]
    assert success.result["nested_complete_payload"]["extra_fields"][1]["retained"]
    assert failure.status == "failed" and failure.failure.exception_type == "RuntimeError"
    assert failure.consumption.accounted_tokens == 70 and failure.consumption.model_calls_estimated
    assert update["consumption"].accounted_tokens == 100 and update["consumption"].model_calls_estimated
    assert update["delegation_status"] == "partial"
    assert "secret provider payload" not in str(update)


@pytest.mark.parametrize("field,value", [("repository_id", "other"), ("snapshot_hash", "stale"), ("commit", "other")])
def test_mismatched_result_identity_is_failed_but_full_output_is_retained(tools, monkeypatch, field, value):
    async def mismatch(child, child_tools, request):
        return output(child_tools, request, **{field: value})

    runtime, state, _ = execution(tools, monkeypatch, {"one": spec(run=mismatch)}, [assignment()])
    update = asyncio.run(runtime.delegate_coordinators(state))
    record = update["coordinator_results"][0]
    assert record.status == "failed" and record.result[field] == value
    assert record.failure.code == "repository_provenance_mismatch"
    assert record.consumption.accounted_tokens == 30 and update["delegation_status"] == "failed"


def test_invalid_assignment_scope_skips_without_constructing_a_coordinator(tools, monkeypatch):
    registered = spec()
    runtime, state, _ = execution(tools, monkeypatch, {"one": registered}, [assignment(scope=["Inventory"])])
    update = asyncio.run(runtime.delegate_coordinators(state))
    assert update["coordinator_results"][0].status == "skipped"
    assert not registered.agent_class.instances


def test_exact_duplicate_not_executed_twice_and_has_distinct_trace_record(tools, monkeypatch):
    registered = spec()
    runtime, state, _ = execution(tools, monkeypatch, {"one": registered}, [assignment(), assignment()])
    update = asyncio.run(runtime.delegate_coordinators(state))
    first, second = update["coordinator_results"]
    assert len(registered.agent_class.instances) == 1
    assert first.assignment_id != second.assignment_id and second.failure.code == "duplicate_assignment"
    assert update["delegation_status"] == "partial"


def test_wrong_manager_snapshot_does_not_dispatch(tools, monkeypatch):
    registered = spec()
    runtime, state, _ = execution(tools, monkeypatch, {"one": registered}, [assignment()])
    state["snapshot_hash"] = "stale"
    update = asyncio.run(runtime.delegate_coordinators(state))
    assert update["delegation_status"] == "failed" and not registered.agent_class.instances


def test_insufficient_call_budget_does_not_start_children(tools, monkeypatch):
    registered = spec()
    runtime, state, _ = execution(tools, monkeypatch, {"one": registered}, [assignment()])
    state["consumption"] = Consumption(model_calls=8)
    update = asyncio.run(runtime.delegate_coordinators(state))
    assert update["coordinator_results"][0].failure.code == "execution_budget_exhausted"
    assert not registered.agent_class.instances


def test_real_modularity_planner_is_invoked_and_explicitly_remains_partial(tools):
    assignment_value = assignment("modularity")
    # Only the actual child planner calls this offline model. Delegation does not.
    model = Model({"objective": assignment_value.objective, "assignments": [],
        "uncovered_requirements": ["No technical assessment was executed."], "limitations": ["Planner only."]})
    manager = MaintainabilityManager(model, MaintainabilityConfig(provider_request_interval_seconds=0,
        invocation_limits=ModularityConfig(provider_request_interval_seconds=0, max_schema_retries=0)), tracing_backend=Tracing())
    request = MaintainabilityRequest(objective="Original Checkout request.", targets=["Checkout"])
    runtime = manager._execution(tools, request)
    state = runtime.initial_state() | {"plan": AuditPlan(objective=request.objective, assignments=[assignment_value])}
    result = asyncio.run(manager.delegate_coordinators(tools, state))
    record = result["coordinator_results"][0]
    assert registered_coordinators()["modularity"].result_kind == "assessment"
    assert record.status == result["delegation_status"] == "partial"
    assert record.result["plan"]["uncovered_requirements"] == ["No technical assessment was executed."]
    assert record.result["request"]["original_objective"] == request.objective
    assert record.consumption.model_calls == len(model.contexts) == 1
    assert record.result["status"] == "not_applicable"
    assert tools.budget_usage.tool_calls == 0


def test_manager_keeps_existing_planning_budget_defaults():
    config = MaintainabilityConfig()
    for field in ("max_model_calls", "max_tool_calls", "max_total_tokens", "timeout_seconds"):
        assert getattr(config, field) == getattr(InvestigationConfig(), field)
    assert config.max_parallel == 3


def test_planning_only_registration_cannot_claim_a_completed_assessment(tools, monkeypatch):
    runtime, state, _ = execution(tools, monkeypatch, {"one": spec(kind="planning")}, [assignment()])
    update = asyncio.run(runtime.delegate_coordinators(state))
    record = update["coordinator_results"][0]
    assert record.result["status"] == "completed"  # Raw output retained, not trusted as final.
    assert record.status == update["delegation_status"] == "partial"


@pytest.mark.parametrize("changes", [{"plan": None, "status": "failed", "termination_reason": "model_or_schema_error"},
    {"request": {}}, {"consumption": {"model_calls": -1}}])
def test_invalid_or_failed_output_retained_without_false_success(tools, monkeypatch, changes):
    async def invalid(child, child_tools, request):
        return output(child_tools, request, **changes)

    runtime, state, _ = execution(tools, monkeypatch, {"one": spec(run=invalid, kind="planning")}, [assignment()])
    update = asyncio.run(runtime.delegate_coordinators(state))
    record = update["coordinator_results"][0]
    assert record.status == update["delegation_status"] == "failed"
    assert record.result and record.failure
    for key, value in changes.items():
        assert record.result[key] == value
    assert CoordinatorExecutionRecord.model_validate_json(record.model_dump_json()) == record


def test_non_structured_output_retained_as_invalid_raw_response(tools, monkeypatch):
    async def invalid(child, child_tools, request):
        return ["not a coordinator output"]

    runtime, state, _ = execution(tools, monkeypatch, {"one": spec(run=invalid)}, [assignment()])
    record = asyncio.run(runtime.delegate_coordinators(state))["coordinator_results"][0]
    assert record.status == "failed" and record.result == ["not a coordinator output"]
    assert record.failure.code == "result_contract_invalid"
    assert CoordinatorExecutionRecord.model_validate_json(record.model_dump_json()) == record


def test_timeout_is_an_individual_error_not_a_success(tools, monkeypatch):
    async def timeout(child, child_tools, request):
        raise TimeoutError

    runtime, state, _ = execution(tools, monkeypatch, {"one": spec(run=timeout)}, [assignment()])
    record = asyncio.run(runtime.delegate_coordinators(state))["coordinator_results"][0]
    assert record.status == "timeout" and record.failure.code == "execution_timeout"


def test_registered_assessment_output_does_not_require_a_planner_state(tools, monkeypatch):
    async def assessment(child, child_tools, request):
        result = output(child_tools, request)
        result.pop("plan")
        result.pop("request")
        return result | {"objective": request.objective, "targets": request.targets,
            "termination_reason": "assessments_completed"}

    runtime, state, _ = execution(tools, monkeypatch, {"one": spec(run=assessment)}, [assignment()])
    record = asyncio.run(runtime.delegate_coordinators(state))["coordinator_results"][0]
    assert record.status == "completed" and record.failure is None
    assert record.result["termination_reason"] == "assessments_completed"
