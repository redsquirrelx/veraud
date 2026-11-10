"""Documentary V2 obeys the global switch and always accounts resource usage."""

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import test_architecture_boundary_doc_driven_investigation as investigation
from test_architecture_boundary_doc_driven_planning import claim, context

from config.agents.budgets import BudgetPolicy
from server.agent_services.budgeting import policy
from server.agents.maintainability.v2.modularity.architecture_boundary.config import (
    BoundaryConfig as StructuralConfig,
)
from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.config import (
    BoundaryConfig,
)
from server.runtimes.repository.context import RepositoryContext
from server.runtimes.repository.schemas import ExecutionBudget, RepositoryInput
from server.runtimes.repository.shared_tokens import SharedTokenBudget
from server.runtimes.repository.tools import RepositoryToolset


@pytest.fixture
def tools(tmp_path):
    return investigation.verified_tools(tmp_path, {
        "app/__init__.py": "", "app/api.py": "from .store import Store\ndef use(): return Store()\n",
        "app/store.py": "class Store: pass\n"})


def test_global_switch_disables_task_and_parent_caps_but_accounts_usage(tools, monkeypatch):
    monkeypatch.setattr(policy, "token_budget_policy", lambda: BudgetPolicy(budgets_enabled=False))
    original = investigation.Model.ainvoke

    async def expensive(self, messages, **kwargs):
        answer = await original(self, messages, **kwargs)
        return answer.model_copy(update={"usage_metadata": {
            "input_tokens": 1200, "output_tokens": 300, "total_tokens": 1500}})

    monkeypatch.setattr(investigation.Model, "ainvoke", expensive)
    shared = SharedTokenBudget(1000)
    tools.token_budget = shared
    state, model, execution = investigation.run(tools, context(tools, [claim()]), investigation.assess_all,
        max_total_tokens=1000, max_tokens_per_investigation=1000)
    result = state["result"]
    assert result.termination_reason == "investigations_completed"
    assert result.investigation_results[0].status == "no_finding"
    assert result.accounted_tokens == shared.used == 3000
    assert result.estimated_tokens == shared.estimated == 0
    assert result.consumption_by_phase["investigate"]["accounted_tokens"] == 1500
    assert result.tool_calls > 0 and len(model.contexts) == 2
    assert execution.output_limit == 1800  # Per-response limit is not disabled.
    budget = execution._new_task_budget(state | {"current_investigation": 0})
    assert budget["token_end"] is None and budget["token_share_end"] is None
    json.dumps(budget, allow_nan=False)


def test_global_enabled_policy_enforces_cumulative_limits(tools):
    state, _, _ = investigation.run(tools, context(tools, [claim()]), investigation.assess_all,
        max_total_tokens=1000)
    assert state["result"].termination_reason == "token_limit"
    assert state["result"].model_calls == 0
    assert "unlimited_token_budget" not in BoundaryConfig.model_fields
    assert "unlimited_token_budget" not in StructuralConfig.model_fields


def test_reenabled_per_task_limit_remains_effective(tools):
    state, _, _ = investigation.run(tools, context(tools, [claim()]), investigation.assess_all,
        max_tokens_per_investigation=1000)
    result = state["result"]
    assert result.model_calls == 1  # Planning succeeded; task admission did not.
    assert "investigation_token_limit" in result.investigation_results[0].limitations


def test_global_enabled_policy_retains_input_limit(tools):
    snapshot = tools.accessible_snapshot
    limited = RepositoryToolset(RepositoryContext(snapshot, RepositoryInput(snapshot_hash=snapshot.repository.snapshot_hash,
        budget=ExecutionBudget(max_input_tokens_per_call=500))), workspace_root=Path(snapshot.repository.root_path).parent)
    state, _, _ = investigation.run(limited, context(limited, [claim()]), investigation.assess_all)
    assert state["result"].model_calls == 0
    result = state["result"].investigation_results[0]
    assert result.status == "inconclusive"
    assert set(result.limitations) & {"input_token_limit", "context_limit"}


def test_runner_rejects_local_budget_switch(tmp_path, monkeypatch):
    path = Path(__file__).parents[1] / "src/test-agents/run_architecture_boundary_doc_driven.py"
    spec = importlib.util.spec_from_file_location("doc_token_runner", path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    config = tmp_path / "config.json"
    config.write_text('{"unlimited_token_budget": false}', encoding="utf-8")
    audit = AsyncMock()
    monkeypatch.setattr(runner, "run_audit", audit)
    monkeypatch.setattr(runner, "load_test_model", lambda _: (object(), SimpleNamespace()))
    monkeypatch.setattr(runner, "close_model_clients", AsyncMock())
    with pytest.raises(ValueError):
        asyncio.run(runner.run(SimpleNamespace(repository=str(tmp_path), request=None, architecture_context=None,
            config=str(config), agent_config="dummy")))
    audit.assert_not_awaited()
