"""Offline tests of the isolated manager planning node, with real shared calls."""

import asyncio
import json

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError
from test_architecture_boundary_planning import tools_for

from server.agents.maintainability.v2.manager import (
    AuditPlan,
    CoordinatorCapability,
    MaintainabilityManager,
    MaintainabilityRequest,
)
from server.agents.maintainability.v2.manager.config import MaintainabilityConfig
from server.agents.maintainability.v2.manager.execution import (
    MaintainabilityManagerExecution,
)
from server.agents.maintainability.v2.manager.registry import coordinator_catalog


class Model:
    def __init__(self, response):
        self.response, self.contexts = response, []

    async def ainvoke(self, messages, **kwargs):
        self.contexts.append(json.loads(messages[1].content))
        if isinstance(self.response, Exception):
            raise self.response
        return AIMessage(content=self.response if isinstance(self.response, str) else json.dumps(self.response),
            usage_metadata={"input_tokens": 80, "output_tokens": 40, "total_tokens": 120})


def capability(identifier="boundaries"):
    return CoordinatorCapability(id=identifier, agent_name=identifier.title(),
        capability="Investigate architectural relationships." if identifier == "boundaries" else "Investigate reuse opportunities.",
        problem_types=["architectural boundaries"] if identifier == "boundaries" else ["reuse"],
        constraints=["Read-only investigation."])


def assignment(identifier="boundaries", **changes):
    return {"coordinator_id": identifier, "objective": "Examine requested architectural problems.",
        "scope": [], "constraints": [], "rationale": "The request asks for architectural relationships."} | changes


def plan(*assignments, **changes):
    return {"objective": "Interpret the requested maintainability audit.", "assignments": list(assignments),
        "uncovered_requirements": [], "limitations": []} | changes


@pytest.fixture
def tools(tmp_path):
    return tools_for(tmp_path, {"Checkout/api.py": "class Checkout: pass\n", "Checkout/store.py": "class Store: pass\n",
        "Inventory/api.py": "class Inventory: pass\n"})


def execute(tools, response, request=None, capabilities=None):
    request = request or MaintainabilityRequest(objective="Analyze repository maintainability.")
    model = Model(response)
    execution = MaintainabilityManagerExecution(model, MaintainabilityConfig(provider_request_interval_seconds=0), tools, request)
    state = execution.initial_state()
    state["coordinator_catalog"] = list(coordinator_catalog(capabilities if capabilities is not None else [capability()]).values())
    before = dict(state)
    update = asyncio.run(execution.plan_audit(state))
    assert state == before  # Node returns a delta, not mutations of caller state.
    assert tools.budget_usage.tool_calls == 0 and execution.graph is not None
    assert update["consumption"].model_calls == len(model.contexts) == 1
    if isinstance(response, Exception):
        assert update["consumption"].accounted_tokens > 0  # Failed calls keep estimated usage.
    else:
        assert update["consumption"].accounted_tokens == 120
    return update, model.contexts[0]


def test_specific_request_selects_one_from_dynamic_catalog(tools):
    request = MaintainabilityRequest(objective="Investigate architectural problems.", repository_context="A modular application.")
    update, context = execute(tools, plan(assignment()), request, [capability(), capability("reuse")])
    assert [item.coordinator_id for item in update["plan"].assignments] == ["boundaries"]
    assert context["request"] == request.model_dump(exclude={"documented_architecture", "maintainability_selection"})
    assert context["repository_id"] == tools.accessible_snapshot.repository.name
    assert context["snapshot_hash"] == tools.accessible_snapshot.repository.snapshot_hash
    assert {item["id"] for item in context["coordinator_catalog"]} == {"boundaries", "reuse"}
    assert not update["termination_reason"]


def test_multiple_coordinators_have_specific_independent_objectives(tools):
    update, _ = execute(tools, plan(assignment(), assignment("reuse", objective="Assess duplication and reuse.",
        rationale="Reuse is explicitly requested.")), capabilities=[capability(), capability("reuse")])
    assert len(update["plan"].assignments) == 2
    assert len({item.objective for item in update["plan"].assignments}) == 2


def test_general_request_does_not_force_all_registered_coordinators(tools):
    update, _ = execute(tools, plan(assignment("reuse")), capabilities=[capability(), capability("reuse")])
    assert [item.coordinator_id for item in update["plan"].assignments] == ["reuse"]
    assert update["plan"].assignments[0].scope == []


def test_component_scope_inherited_and_request_constraints_are_not_lost(tools):
    request = MaintainabilityRequest(objective="Investigate architecture in Checkout only.", targets=["Checkout"],
        constraints=["Do not inspect Inventory.", "Do not modify files."])
    update, context = execute(tools, plan(assignment(constraints=["Keep uncertainty explicit."])), request)
    item = update["plan"].assignments[0]
    assert item.scope == ["Checkout"]
    assert item.constraints == [*request.constraints, "Read-only investigation.", "Keep uncertainty explicit."]
    assert context["request"]["objective"] == request.objective


def test_narrower_scope_is_allowed_and_paths_normalized(tools):
    request = MaintainabilityRequest(objective="Investigate Checkout.", targets=["Checkout/"])
    update, _ = execute(tools, plan(assignment(scope=["Checkout\\api.py"])), request)
    assert update["plan"].assignments[0].scope == ["Checkout/api.py"]


@pytest.mark.parametrize("scope", [["Inventory"], ["CheckoutOther"], ["../Checkout"], ["/Checkout"], ["Checkout/missing.py"]])
def test_scope_expansion_or_inaccessible_scope_is_rejected(tools, scope):
    update, _ = execute(tools, plan(assignment(scope=scope)),
        MaintainabilityRequest(objective="Checkout only.", targets=["Checkout"]))
    assert update["plan"] is None and update["termination_reason"] == "invalid_plan"
    assert any("scope" in limitation for limitation in update["limitations"])


@pytest.mark.parametrize("capabilities", [[], [capability()]])
def test_no_compatible_coordinator_allows_explained_empty_plan(tools, capabilities):
    update, _ = execute(tools, plan(uncovered_requirements=["No registered coordinator covers testability."]),
        MaintainabilityRequest(objective="Investigate testability."), capabilities)
    assert update["plan"].assignments == []
    assert update["plan"].uncovered_requirements == ["No registered coordinator covers testability."]


def test_empty_plan_without_explanation_is_not_a_valid_plan(tools):
    update, _ = execute(tools, plan())
    assert update["plan"] is None
    assert "plan_audit: empty_plan_without_explanation" in update["limitations"]


def test_fictitious_coordinator_rejected_without_silently_replacing_it(tools):
    update, _ = execute(tools, plan(assignment("invented")))
    assert update["plan"] is None
    assert "plan_audit: unknown_coordinator" in update["limitations"]


def test_exact_duplicates_removed_but_distinct_objectives_preserved(tools):
    update, _ = execute(tools, plan(assignment(), assignment(), assignment(objective="A different requested concern.")))
    assert len(update["plan"].assignments) == 2
    assert {item.objective for item in update["plan"].assignments} == {
        "Examine requested architectural problems.", "A different requested concern."}


def test_order_is_deterministic_and_model_limitations_are_preserved(tools):
    model = Model(plan(assignment("reuse"), assignment(), limitations=["Only two dimensions available."]))
    execution = MaintainabilityManagerExecution(model, MaintainabilityConfig(provider_request_interval_seconds=0), tools,
        MaintainabilityRequest(objective="Analyze maintainability."))
    state = execution.initial_state() | {"coordinator_catalog": [capability("reuse"), capability()], "limitations": ["Prior limitation."]}
    first = asyncio.run(execution.plan_audit(state))
    model.response["assignments"].reverse()
    second = asyncio.run(execution.plan_audit(state))
    assert first["plan"] == second["plan"]
    assert first["limitations"] == ["Prior limitation.", "Only two dimensions available."]
    assert AuditPlan.model_validate_json(first["plan"].model_dump_json()) == first["plan"]


@pytest.mark.parametrize("response", ["not json", {"assignments": []}, plan(assignment(objective="")),
    plan(assignment(investigator_ids=["private"])), RuntimeError("secret-provider-payload")])
def test_invalid_model_response_or_provider_failure_is_explicit(tools, response):
    update, _ = execute(tools, response)
    assert update["plan"] is None and update["termination_reason"]
    assert update["limitations"]
    assert "secret-provider-payload" not in str(update["limitations"])


def test_duplicate_catalog_ids_fail_before_calling_model():
    with pytest.raises(ValueError, match="Duplicate coordinator"):
        coordinator_catalog([capability(), capability()])


def test_planner_config_rejects_tools_and_other_prompt_nodes():
    with pytest.raises(ValidationError):
        MaintainabilityConfig(tools=["list_files"])
    with pytest.raises(ValidationError):
        MaintainabilityConfig(prompts={"investigate": "Inspect code"})


def test_public_entry_point_runs_only_plan_audit(tools):
    class Tracing:
        async def wrap_stage(self, operation, **metadata):
            assert metadata["name"] == "plan_audit"
            return await operation

    manager = MaintainabilityManager(Model(plan(assignment())), MaintainabilityConfig(provider_request_interval_seconds=0),
        tracing_backend=Tracing())
    state = asyncio.run(manager.plan_audit(tools, {"objective": "Analyze architecture."}, capabilities=[capability()]))
    assert state["plan"].assignments
    assert state["request"].objective == "Analyze architecture."
    assert state["consumption"].model_calls == 1 and tools.budget_usage.tool_calls == 0


def test_native_structured_output_is_locally_validated(tools):
    class NativeModel(Model):
        def with_structured_output(self, schema, **kwargs):
            assert schema is AuditPlan
            assert kwargs == {"method": "json_schema", "include_raw": True}
            return self

        async def ainvoke(self, messages, **kwargs):
            raw = await super().ainvoke(messages, **kwargs)
            return {"raw": raw, "parsed": self.response, "parsing_error": None}

    model = NativeModel(plan(assignment("not_registered")))
    execution = MaintainabilityManagerExecution(model, MaintainabilityConfig(provider_request_interval_seconds=0), tools,
        MaintainabilityRequest(objective="Analyze architecture."))
    state = execution.initial_state() | {"coordinator_catalog": [capability()]}
    update = asyncio.run(execution.plan_audit(state))
    assert update["plan"] is None and update["termination_reason"] == "invalid_plan"
    assert update["consumption"].accounted_tokens == 120


def test_per_call_context_limit_returns_explicit_failure_without_provider_call(tools):
    model = Model(plan(assignment()))
    execution = MaintainabilityManagerExecution(model,
        MaintainabilityConfig(provider_request_interval_seconds=0, max_context_characters=4000), tools,
        MaintainabilityRequest(objective="Analyze architecture.", repository_context="x" * 5000))
    update = asyncio.run(execution.plan_audit(execution.initial_state() | {"coordinator_catalog": [capability()]}))
    assert update["plan"] is None and update["termination_reason"] == "context_limit"
    assert update["consumption"].model_calls == 0 and not model.contexts
