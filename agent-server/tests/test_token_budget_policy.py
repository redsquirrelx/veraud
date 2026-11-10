"""One global budget switch; accounting and cancellation never switch off."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from config.agents import InvestigationConfig
from config.agents.budgets import BudgetPolicy
from server.agent_services.budgeting import policy
from server.agent_services.budgeting.shared_tokens import SharedTokenBudget
from server.agent_services.budgeting.timing import ActiveDeadline, within_deadline
from server.agent_services.budgeting.tokens import admit_request
from server.runtimes.coordination.execution import CoordinatorExecution
from server.runtimes.repository.budgeted_model import BudgetedModel


@pytest.fixture
def launch_policy(tmp_path, monkeypatch):
    path = tmp_path / "launch.json"
    monkeypatch.setattr(policy, "LAUNCH_PATH", path)
    monkeypatch.setattr(policy, "token_budget_policy", policy.load_budget_policy)

    def configure(values):
        path.write_text(json.dumps(values), encoding="utf-8")
        policy.load_budget_policy.cache_clear()

    yield configure
    policy.load_budget_policy.cache_clear()


def test_disabled_switch_keeps_usage_and_estimates_across_scopes(launch_policy):
    launch_policy({"budgets_enabled": False})
    ledger = SharedTokenBudget(1000)
    scope = ledger.fork()
    first = scope.reserve(2000)
    second = ledger.fork().reserve(3000)
    first.settle(1500)
    assert scope.used == 1500 and ledger.used == 4500 and ledger.estimated == 3000
    second.settle(2500)
    assert ledger.used == 4000 and ledger.estimated == 0


@pytest.mark.parametrize("enabled", [False, True])
def test_one_switch_controls_calls_tokens_context_and_dispatch(launch_policy, enabled):
    launch_policy({"budgets_enabled": enabled})
    runtime = SimpleNamespace(limits=SimpleNamespace(max_context_characters=100, max_model_calls=1,
        max_total_tokens=1000), output_limit=2000, attempts=5, tokens=SharedTokenBudget(1000))
    if enabled:
        with pytest.raises(ValueError, match="context_budget_exhausted"):
            BudgetedModel.guard(runtime, "x" * 101, 0)
        with pytest.raises(ValueError, match="model_call_budget_exhausted"):
            BudgetedModel.guard(runtime, "inspect", 0)
        assert runtime.tokens.reserve(1001) is None
    else:
        BudgetedModel.guard(runtime, "x" * 101, 0)
        assert runtime.tokens.used == 2101 and runtime.attempts == 6
        budget = SimpleNamespace(max_input_tokens_per_call=1, max_output_tokens_per_call=2000,
            max_total_tokens=1000, max_tokens_per_objective=1000)
        assert admit_request(SimpleNamespace(measurements=[]), budget, "x" * 1000, "objective") > 1
    coordinator = SimpleNamespace(resources=lambda: {"calls": 0, "tools": 0, "tokens": 0}, baseline_count=0,
        config=SimpleNamespace(invocation_limits=SimpleNamespace(max_model_calls=4, max_tool_calls=2,
            max_total_tokens=1000), max_invocations=1), remaining=lambda: 0, token_budget=None)
    assert CoordinatorExecution.can_dispatch(coordinator, []) is (not enabled)


@pytest.mark.parametrize("enabled", [False, True])
def test_active_wall_and_outer_timeouts_follow_global_switch(launch_policy, enabled):
    launch_policy({"budgets_enabled": enabled})
    clock = [0.0]
    deadline = ActiveDeadline(1, wall_deadline=1, clock=lambda: clock[0])
    child = deadline.fork(.1, max_wall_time_seconds=.1)
    clock[0] = 2

    async def work():
        return "completed"

    if enabled:
        with pytest.raises(TimeoutError):
            asyncio.run(within_deadline(work(), child))
    else:
        assert asyncio.run(within_deadline(work(), child)) == "completed"
        assert policy.timeout_seconds(.001) is None
        assert asyncio.run(policy.wait_for(asyncio.sleep(.01, result="ok"), .001)) == "ok"


def test_disabled_deadline_still_propagates_explicit_cancellation(launch_policy):
    launch_policy({"budgets_enabled": False})

    async def run():
        started, cleaned = asyncio.Event(), asyncio.Event()

        async def blocked():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        task = asyncio.create_task(within_deadline(blocked(), ActiveDeadline(.001)))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned.is_set()

    asyncio.run(run())


def test_global_default_is_finite_and_switch_is_strict(launch_policy):
    launch_policy({})
    assert policy.budgets_enabled()
    launch_policy({"budgets_enabled": "false"})
    with pytest.raises(ValidationError):
        policy.token_budget_policy()


def test_per_agent_overrides_are_not_supported(launch_policy):
    launch_policy({"budgets_enabled": True})
    for key in ("unlimited_token_budget", "unlimited_model_calls", "unlimited_tool_calls", "budgets_enabled"):
        with pytest.raises(ValidationError):
            InvestigationConfig(**{key: False})
    with pytest.raises(ValueError, match="Per-agent"), policy.using_token_budget_policy(BudgetPolicy(budgets_enabled=False)):
        pytest.fail("A local override must never be entered")


@pytest.mark.parametrize("enabled", [False, True])
def test_repository_read_caps_follow_switch_without_disabling_access_policy(launch_policy, tmp_path, enabled):
    from test_architecture_boundary_doc_driven_investigation import verified_tools

    from config.agents.tools import ToolLimits

    launch_policy({"budgets_enabled": enabled})
    tools = verified_tools(tmp_path, {"app/api.py": "class LongName:\n    value = '" + "x" * 1000 + "'\n"})
    tools.limits = ToolLimits(max_source_lines=1, max_source_characters=1, max_response_characters=512)
    tools.tool_call_limit = 1
    tools.retrieval_budget.limit = 1
    first = tools.execute("get_source_excerpt", {"path": "app/api.py", "start_line": 1, "end_line": 2}, tool_call_id="first")
    second = tools.execute("get_source_excerpt", {"path": "app/api.py", "start_line": 1, "end_line": 2}, tool_call_id="second")
    if enabled:
        assert first.error and second.error.code == "tool_budget_exhausted"
    else:
        assert first.status == second.status == "ok"
        assert first.data["end_line"] == 2 and len(first.data["content"]) > 1000
        assert tools.budget_usage.tool_calls == 2 and tools.retrieval_budget.used > 1000
        forbidden = tools.execute("get_source_excerpt", {"path": "../private.py", "start_line": 1}, tool_call_id="forbidden")
        assert forbidden.error.code == "access_denied"


def test_runner_cannot_override_global_switch(tmp_path):
    from server.config.runner import load_runner_config

    config = tmp_path / "agent.json"
    config.write_text('{"budgets_enabled": false}', encoding="utf-8")
    with pytest.raises(ValueError, match="only in launch.json"):
        load_runner_config(InvestigationConfig, str(config))


def test_disabled_budgets_do_not_disable_provider_quotas_or_pacing(launch_policy, tmp_path):
    from config.agents.user import ProviderRateLimits
    from server.infrastructure.llm.quota import QuotaStore, RequestTokenQuotaExceeded
    from server.infrastructure.llm.retry import RequestPacer

    launch_policy({"budgets_enabled": False})
    store = QuotaStore(tmp_path / "quota.sqlite3", clock=lambda: 1000)
    limits = ProviderRateLimits(requests_per_minute=1, tokens_per_minute=1000)
    assert store.acquire("provider:model", limits, 500)[0] is not None
    assert store.acquire("provider:model", limits, 500)[0] is None
    with pytest.raises(RequestTokenQuotaExceeded):
        store.acquire("provider:other-model", limits, 1001)
    pacer = RequestPacer(interval=5)
    before = pacer.next_allowed
    pacer.completed_attempt()
    assert pacer.next_allowed > before
