"""Deterministic selection of the coordinators a planner may dispatch."""

import asyncio
import json

import pytest
from langchain_core.messages import AIMessage
from test_architecture_boundary_planning import tools_for

from server.agents.maintainability.v2.manager import MaintainabilityRequest
from server.agents.maintainability.v2.manager.config import MaintainabilityConfig
from server.agents.maintainability.v2.manager.execution import (
    MaintainabilityManagerExecution,
)
from server.agents.maintainability.v2.manager.registry import (
    coordinator_catalog,
    selected_coordinators,
)


class Model:
    def __init__(self, response):
        self.response, self.contexts = response, []

    async def ainvoke(self, messages, **kwargs):
        self.contexts.append(json.loads(messages[1].content))
        return AIMessage(content=self.response if isinstance(self.response, str) else json.dumps(self.response),
            usage_metadata={"input_tokens": 80, "output_tokens": 40, "total_tokens": 120})


def assignment(identifier, objective="Examine requested architectural problems.", **changes):
    return {"coordinator_id": identifier, "objective": objective, "scope": [], "constraints": [],
        "rationale": "The request asks for architectural relationships."} | changes


def plan(*assignments, **changes):
    return {"objective": "Interpret the requested maintainability audit.",
        "assignments": list(assignments), "uncovered_requirements": [], "limitations": []} | changes


@pytest.fixture
def tools(tmp_path):
    return tools_for(tmp_path, {"Checkout/api.py": "class Checkout: pass\n",
        "Inventory/api.py": "class Inventory: pass\n"})


def execute(tools, response, request):
    model = Model(response)
    execution = MaintainabilityManagerExecution(model, MaintainabilityConfig(provider_request_interval_seconds=0), tools, request)
    state = execution.initial_state()
    before = dict(state)
    update = asyncio.run(execution.plan_audit(state))
    assert state == before
    return update, model.contexts[0]


def test_planner_catalog_is_restricted_to_the_selection(tools):
    request = MaintainabilityRequest(objective="Investigate architecture.",
        maintainability_selection={"modularity": ["responsibility"]})
    update, context = execute(tools, plan(assignment("modularity")), request)
    assert {item["id"] for item in context["coordinator_catalog"]} == {"modularity"}
    assert "maintainability_selection" not in context["request"]
    assert [item.coordinator_id for item in update["plan"].assignments] == ["modularity"]


def test_assignment_to_an_unselected_coordinator_is_rejected_deterministically(tools):
    request = MaintainabilityRequest(objective="Investigate architecture.",
        maintainability_selection={"modularity": ["responsibility"]})
    update, _ = execute(tools, plan(assignment("reusability")), request)
    assert update["plan"] is None
    assert update["termination_reason"] == "invalid_plan"
    assert "plan_audit: unknown_coordinator" in update["limitations"]


def test_selection_may_enumerate_several_coordinators(tools):
    request = MaintainabilityRequest(objective="Investigate architecture.",
        maintainability_selection={"modularity": ["responsibility"],
            "reusability": ["abstraction"]})
    update, context = execute(tools, plan(assignment("reusability")), request)
    assert {item["id"] for item in context["coordinator_catalog"]} == {"modularity", "reusability"}
    assert [item.coordinator_id for item in update["plan"].assignments] == ["reusability"]


def test_no_selection_preserves_the_legacy_full_catalog(tools):
    request = MaintainabilityRequest(objective="Investigate architecture.")
    update, context = execute(
        tools, plan(assignment("modularity"), assignment("reusability")), request)
    assert {item["id"] for item in context["coordinator_catalog"]} == {"modularity", "reusability"}
    assert update["plan"].assignments != []


def test_selected_coordinators_ignores_unregistered_keys():
    only_modularity = MaintainabilityRequest(
        maintainability_selection={"modularity": ["responsibility"], "not_a_coordinator": ["x"]})
    assert set(selected_coordinators(only_modularity, None)) == {"modularity"}
    assert set(selected_coordinators(MaintainabilityRequest(
        maintainability_selection={"not_a_coordinator": ["x"]}), None)) == set()
    assert set(selected_coordinators(MaintainabilityRequest(), None)) == set(coordinator_catalog())
