"""Direct-registration contract for the finding-resolution agent."""

from server.agents.finding_resolution import (
    FindingResolutionDirectAgent,
    FindingResolutionRunRequest,
    FindingResolutionRunResult,
)
from server.app.execution_service import build_default_registry


def test_direct_agent_is_registered_for_http_dispatch():
    registry = build_default_registry()
    assert "finding_resolution" in registry.list_agents()
    assert registry.get("finding_resolution") is FindingResolutionDirectAgent


def test_direct_request_and_result_contracts_are_exported():
    assert FindingResolutionDirectAgent.input_schema is FindingResolutionRunRequest
    assert FindingResolutionDirectAgent.output_schema is FindingResolutionRunResult
