"""Reusability V2 coordinator with an intentionally empty catalog."""

import asyncio

from test_architecture_boundary_planning import tools_for
from test_maintainability_v2_plan_audit import Model

from server.agents.maintainability.v2.manager.registry import registered_coordinators
from server.agents.maintainability.v2.reusability.coordinator import (
    ReusabilityConfig,
    ReusabilityCoordinator,
    ReusabilityRequest,
)
from server.agents.maintainability.v2.reusability.coordinator.registry import (
    investigator_catalog,
    registered_investigators,
)


class Tracing:
    async def wrap_stage(self, operation, **metadata):
        return await operation


def test_reusability_catalog_registers_planning_shells():
    assert set(registered_investigators()) == {
        "abstraction",
        "reuse_opportunity_doc_driven",
        "reuse_parametrization_doc_driven",
    }
    assert set(investigator_catalog()) == {
        "abstraction",
        "reuse_opportunity_doc_driven",
        "reuse_parametrization_doc_driven",
    }
    assert investigator_catalog([]) == {}
    assert "reusability" in registered_coordinators()
    spec = registered_coordinators()["reusability"]
    assert spec.agent_class is ReusabilityCoordinator
    assert spec.request_class is ReusabilityRequest
    assert spec.result_class is not None


def test_reusability_with_empty_selection_returns_not_applicable(tmp_path):
    tools = tools_for(tmp_path, {"app.py": "x = 1\n"})
    response = {"objective": "Assess reusability.", "assignments": [],
        "uncovered_requirements": ["No investigators selected."], "limitations": ["No investigators selected."]}
    model = Model(response)
    request = ReusabilityRequest(objective="Assess reusability in app.", investigator_selection=[])
    coordinator = ReusabilityCoordinator(model, ReusabilityConfig(provider_request_interval_seconds=0), tracing_backend=Tracing())
    result = asyncio.run(coordinator.run(tools, request))
    assert result.plan is not None
    assert result.plan.assignments == []
    assert result.status == "not_applicable"
    assert result.investigator_registry == []
    assert result.coverage.selected_investigation_ids == []
    assert result.consolidated_findings == []
