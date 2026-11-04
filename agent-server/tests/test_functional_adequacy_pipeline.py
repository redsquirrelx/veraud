"""The domain pipeline uses main's unmodified executor for model-backed runs."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from server.agents.functional_adequacy.schemas import FunctionalAdequacyOutput
from server.api.schemas import ExecutionConfig
from server.app import functional_adequacy_definition as definition
from server.app.pipeline_service import GenericPipelineService
from server.infrastructure.tracing import NoOpTracingBackend


def test_pipeline_runs_exploratory_without_building_a_model():
    executor = SimpleNamespace(run=AsyncMock(side_effect=AssertionError("No executor/model for exploration")))
    service = GenericPipelineService(execution_service=executor, callbacks_factory=lambda: None,
        tracing_backend=NoOpTracingBackend())
    result = asyncio.run(service.run("functional-adequacy", {"code_fragments": [
        {"fragment_id": "1", "file_path": "app.py:1-2", "code": "def items():\n    return []"},
    ]}, ExecutionConfig(), timeout_seconds=30))
    assert result["audit_mode"] == "exploratory"
    assert result["score_applicable"] is False
    assert result["capabilities"]
    executor.run.assert_not_awaited()


def test_pipeline_requirements_mode_uses_main_executor_contract_and_blackboard():
    executor = SimpleNamespace(run=AsyncMock(return_value=FunctionalAdequacyOutput(
        score=0, total_requirements=1, fulfilled_requirements=0)))
    parsed = definition.parse_functional_input({"requirements": [
        {"requirement_id": "REQ-001", "description": "List items."}]})
    config = ExecutionConfig()
    agents, ctx = asyncio.run(definition.build_functional_agents(executor, config, None, parsed, 30))
    ctx["blackboard"] = board = object()
    pipeline = definition.create_functional_pipeline(agents, None, ctx)
    asyncio.run(definition.run_functional_pipeline(pipeline, parsed, ctx))
    kwargs = executor.run.await_args.kwargs
    assert set(kwargs) == {"agent_type", "config", "payload", "blackboard"}
    assert kwargs["config"] is config and kwargs["blackboard"] is board
    assert kwargs["payload"]["requirements"][0]["requirement_id"] == "REQ-001"
