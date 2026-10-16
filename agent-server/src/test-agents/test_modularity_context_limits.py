"""Offline: uv run pytest src/test-agents/test_modularity_context_limits.py -q."""

import asyncio

import pytest
from langchain_core.messages import HumanMessage
from test_architecture_boundary import ScriptedModel, toolset

from server.agents.maintainability.modularity.architecture_boundary import (
    ArchitectureBoundaryAgent,
)
from server.agents.maintainability.modularity.dependency_impact import DependencyImpactAgent
from server.agents.maintainability.modularity.coordinator import ModularityConfig
from server.agents.maintainability.modularity.responsibility import ResponsibilityAgent
from server.runtimes.investigation.schemas import Review


@pytest.mark.parametrize("agent_class", [ArchitectureBoundaryAgent, ResponsibilityAgent, DependencyImpactAgent])
@pytest.mark.parametrize("legacy_limit", [None, 60_000])
def test_larger_context_reaches_model_without_disabling_guards(tmp_path, agent_class, legacy_limit):
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "main.py").write_text("value = 1\n", encoding="utf-8")
    config = agent_class.config_type()
    if legacy_limit is not None:
        config = config.model_copy(update={"max_context_characters": legacy_limit})
    model = ScriptedModel([{"findings": [], "limitations": []}])
    execution = agent_class.execution_type(model, config, toolset(root), agent_class.request_type())
    state = execution.initial_state()
    state["messages"] = [HumanMessage(content="x" * 65_000)]
    result = asyncio.run(execution.call("review_findings", state, Review))
    if legacy_limit:
        assert result is None and execution.stop == "context_limit"
        assert not model.history
    else:
        assert config.max_context_characters == 100_000
        assert result is not None and not execution.stop
        assert len(model.history) == 1


def test_coordinator_context_defaults_preserve_other_budgets():
    config = ModularityConfig()
    assert config.max_context_characters == 100_000
    assert config.invocation_limits.max_context_characters == 100_000
    assert config.max_total_tokens == 300_000
    assert config.invocation_limits.max_total_tokens == 60_000
    assert config.max_rounds == 2
    assert config.timeout_seconds == 600
