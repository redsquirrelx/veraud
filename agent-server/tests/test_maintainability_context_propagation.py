"""Context transport is lossless, opt-in and invisible to orchestration models."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic import Field
from test_architecture_boundary_doc_driven_investigation import verified_tools
from test_architecture_boundary_doc_driven_planning import claim, context
from test_maintainability_v2_plan_audit import Model
from test_maintainability_v2_plan_audit import plan as audit_plan
from test_modularity_v2_plan_assessment import plan as assessment_plan

from server.agents.maintainability.v2.manager import MaintainabilityRequest
from server.agents.maintainability.v2.manager.config import MaintainabilityConfig
from server.agents.maintainability.v2.manager.delegation import coordinator_request
from server.agents.maintainability.v2.manager.execution import (
    MaintainabilityManagerExecution,
)
from server.agents.maintainability.v2.manager.registry import registered_coordinators
from server.agents.maintainability.v2.manager.schemas import CoordinatorAssignment
from server.agents.maintainability.v2.modularity.coordinator import (
    AssessmentRequest,
    ModularityConfig,
)
from server.agents.maintainability.v2.modularity.coordinator.dispatch import (
    investigator_request,
)
from server.agents.maintainability.v2.modularity.coordinator.execution import (
    ModularityExecution,
)
from server.agents.maintainability.v2.modularity.coordinator.registry import (
    registered_investigators,
)
from server.agents.maintainability.v2.modularity.coordinator.schemas import (
    InvestigationAssignment,
)
from server.contracts.audit import Contract

MARKER = "INVESTIGATOR_ONLY_DOCUMENTARY_CLAIM"


@pytest.fixture
def inputs(tmp_path):
    tools = verified_tools(tmp_path, {"app/api.py": "from .store import Store\n", "app/store.py": "class Store: pass\n"})
    documented = context(tools, [claim(statement=MARKER)])
    return tools, documented


def test_manager_plans_without_documentary_json_while_retaining_transport(inputs):
    tools, documented = inputs
    request = MaintainabilityRequest(objective="Inspect architectural boundaries.", targets=["app"], documented_architecture=documented)
    model = Model(audit_plan(uncovered_requirements=["No applicable assignment."]))
    execution = MaintainabilityManagerExecution(model, MaintainabilityConfig(provider_request_interval_seconds=0), tools, request)
    state = execution.initial_state()
    original = documented.model_dump(mode="json")
    asyncio.run(execution.plan_audit(state))
    assert len(model.contexts) == 1
    assert "documented_architecture" not in model.contexts[0]["request"]
    assert MARKER not in json.dumps(model.contexts)
    assert "Documented obligation" not in json.dumps(model.contexts)
    assert state["request"].documented_architecture.model_dump(mode="json") == original


def test_coordinator_plans_without_documentary_json_while_retaining_transport(inputs):
    tools, documented = inputs
    request = AssessmentRequest(objective="Inspect architectural boundaries.", documented_architecture=documented)
    model = Model(assessment_plan(uncovered_requirements=["No applicable assignment."]))
    execution = ModularityExecution(model, ModularityConfig(provider_request_interval_seconds=0), tools, request)
    state = execution.initial_state()
    asyncio.run(execution.plan_assessment(state))
    assert len(model.contexts) == 1
    assert "documented_architecture" not in model.contexts[0]["request"]
    assert MARKER not in json.dumps(model.contexts)
    assert "Documented obligation" not in json.dumps(model.contexts)
    assert state["request"].documented_architecture == documented


def test_manager_coordinator_investigator_transport_preserves_full_canonical_context(inputs):
    tools, documented = inputs
    request = MaintainabilityRequest(objective="External manager objective must not reach investigator.", documented_architecture=documented)
    delegated = coordinator_request(registered_coordinators()["modularity"], request,
        CoordinatorAssignment(coordinator_id="modularity", objective="Inspect boundaries.", scope=["app"], rationale="Architectural scope."))
    sent = investigator_request(registered_investigators()["architecture_boundary"],
        InvestigationAssignment(investigator_id="architecture_boundary", objective="External coordinator objective must not reach investigator.",
                                targets=["app"], rationale="Documented scope."), delegated, tools.accessible_snapshot.repository)
    assert sent.documented_architecture.model_dump(mode="json") == documented.model_dump(mode="json")
    assert sent.documented_architecture.execution_status == "partial"
    assert sent.documented_architecture.pending_categories == documented.pending_categories
    assert sent.targets == ["app"]
    assert "External" not in sent.model_dump_json()
    assert "objective" not in type(sent).model_fields


@pytest.mark.parametrize("textual", [False, True])
def test_investigator_without_explicit_field_never_receives_documentary_context(inputs, textual):
    class PlainRequest(Contract):
        targets: list[str] = Field(default_factory=list)

    class TextRequest(PlainRequest):
        architectural_context: str = ""

    tools, documented = inputs
    request = AssessmentRequest(objective="Inspect boundaries.", documented_architecture=documented)
    assignment = InvestigationAssignment(investigator_id="example", objective="Inspect boundaries.", targets=["app"], rationale="Scope.")
    sent = investigator_request(SimpleNamespace(request_class=TextRequest if textual else PlainRequest),
                                assignment, request, tools.accessible_snapshot.repository)
    assert "documented_architecture" not in sent.model_dump_json()
    assert MARKER not in sent.model_dump_json()
    assert "Documented obligation" not in sent.model_dump_json()
