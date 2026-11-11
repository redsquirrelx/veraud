"""Documentary boundary accepts structured data, never external task prompts."""

import asyncio

import pytest
from pydantic import ValidationError

from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven import (
    ArchitectureBoundaryAgent,
    AuditRequest,
    BoundaryConfig,
)
from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.execution import (
    BoundaryExecution,
)
from server.contracts.audit import AuditRequest as CommonAuditRequest


@pytest.mark.parametrize("field,value", [
    ("objective", "External task"), ("architectural_context", "External instructions"),
    ("prompt", "External prompt"), ("criteria", []), ("follow_up", []),
    ("follow_up_diagnostics", ["External recovery instructions"]),
])
def test_external_prompt_channels_are_rejected_not_silently_ignored(field, value):
    assert field not in AuditRequest.model_json_schema()["properties"]
    with pytest.raises(ValidationError):
        AuditRequest.model_validate({field: value})


def test_agent_rejects_even_a_common_typed_prompt_envelope_before_execution():
    agent = ArchitectureBoundaryAgent(object(), BoundaryConfig())
    with pytest.raises(ValidationError):
        asyncio.run(agent.run(object(), CommonAuditRequest(objective="External objective")))
    with pytest.raises(ValidationError):
        asyncio.run(agent.run(object(), {"objective": "External objective"}))
    with pytest.raises(ValidationError):
        BoundaryExecution(object(), BoundaryConfig(), object(), CommonAuditRequest(objective="External objective"))


def test_only_internal_prompts_and_read_only_internal_objective_are_used():
    with pytest.raises(ValidationError, match="internal prompts"):
        BoundaryConfig(prompts={"investigate": "External instructions"})
    request = AuditRequest(targets=["Checkout"], constraints=["Read only."])
    assert set(request.model_dump()) == {"targets", "constraints", "documented_architecture", "continuation"}
    assert request.objective == AuditRequest().objective
    assert request.criteria == AuditRequest().criteria
    with pytest.raises((AttributeError, ValueError)):
        request.objective = "External objective"
