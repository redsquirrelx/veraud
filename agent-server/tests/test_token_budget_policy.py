import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from server.config import token_budget as policy
from server.runtimes.coordination.execution import CoordinatorExecution
from server.runtimes.repository.budgeted_model import BudgetedModel
from server.runtimes.repository.shared_tokens import SharedTokenBudget
from server.runtimes.repository.token_budget import TokenBudgetExceeded, admit_request


@pytest.fixture
def launch_policy(tmp_path, monkeypatch):
    path = tmp_path / "launch.json"
    monkeypatch.setattr(policy, "LAUNCH_PATH", path)

    def configure(values):
        path.write_text(json.dumps(values), encoding="utf-8")
        policy.token_budget_policy.cache_clear()

    yield configure
    policy.token_budget_policy.cache_clear()


def test_unlimited_launch_mode_keeps_usage_and_estimates_across_scopes(launch_policy):
    launch_policy({"unlimited_token_budget": True, "max_model_calls": 24})
    ledger = SharedTokenBudget(1000)
    scope = ledger.fork()
    first = scope.reserve(2000)
    second = ledger.fork().reserve(3000)
    assert first is not None and second is not None
    first.settle(1500)
    assert scope.used == 1500 and ledger.used == 4500
    assert ledger.estimated == 3000
    second.settle(2500)
    assert ledger.used == 4000 and ledger.estimated == 0


def test_unlimited_admission_ignores_total_and_objective_caps_but_retains_context_limit(launch_policy):
    launch_policy({"unlimited_token_budget": True})
    budget = SimpleNamespace(max_input_tokens_per_call=100, max_output_tokens_per_call=2000,
        max_total_tokens=1000, max_tokens_per_objective=1000)
    assert admit_request(SimpleNamespace(measurements=[]), budget, "inspect", "objective") > 0
    with pytest.raises(TokenBudgetExceeded, match="per-call context"):
        admit_request(SimpleNamespace(measurements=[]), budget, "x" * 1000, "objective")


@pytest.mark.parametrize("values", [{}, {"unlimited_token_budget": False}])
def test_finite_mode_still_enforces_caps(launch_policy, values):
    launch_policy(values)
    ledger = SharedTokenBudget(1000)
    assert ledger.reserve(1001) is None
    assert policy.token_budget_exceeded(1001, 1000)


def test_launch_rejects_ambiguous_boolean(launch_policy):
    launch_policy({"unlimited_token_budget": "false"})
    with pytest.raises(ValidationError):
        policy.token_budget_policy()


def test_unlimited_hierarchy_can_dispatch_after_tokens_are_spent_but_not_after_calls(launch_policy):
    launch_policy({"unlimited_token_budget": True})
    limits = SimpleNamespace(max_model_calls=4, max_tool_calls=2, max_total_tokens=1000)
    resources = {"calls": 4, "tools": 2, "tokens": -2000}
    coordinator = SimpleNamespace(resources=lambda: resources, baseline_count=0,
        config=SimpleNamespace(invocation_limits=limits, max_invocations=2),
        remaining=lambda: 10, token_budget=None)
    assert CoordinatorExecution.can_dispatch(coordinator, [])
    resources["calls"] = 3
    assert not CoordinatorExecution.can_dispatch(coordinator, [])


def test_unlimited_managed_model_keeps_context_and_call_admission(launch_policy):
    launch_policy({"unlimited_token_budget": True})
    runtime = SimpleNamespace(limits=SimpleNamespace(max_context_characters=100, max_model_calls=1,
        max_total_tokens=1000), output_limit=2000, attempts=0, tokens=SharedTokenBudget(1000))
    BudgetedModel.guard(runtime, "inspect", 0)
    assert runtime.reservation is not None and runtime.tokens.used > 1000
    with pytest.raises(ValueError, match="model_call_budget_exhausted"):
        BudgetedModel.guard(runtime, "inspect", 0)
    with pytest.raises(ValueError, match="context_budget_exhausted"):
        BudgetedModel.guard(runtime, "x" * 101, 0)
