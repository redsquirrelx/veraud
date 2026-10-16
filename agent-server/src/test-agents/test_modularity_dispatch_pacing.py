"""Offline: uv run pytest src/test-agents/test_modularity_dispatch_pacing.py -q."""

import asyncio
from itertools import pairwise
from time import monotonic
from types import SimpleNamespace

import pytest
from test_architecture_boundary import NativeStructuredModel, toolset
from test_modularity import result

from server.agents.maintainability.modularity.coordinator import (
    ModularityAgent,
    ModularityConfig,
    ModularityRequest,
)
from server.agents.maintainability.modularity.coordinator.agent import (
    ModularityExecution,
)
from server.app.tracing_port import NoOpTracingBackend


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "main.py").write_text("value = 1\n", encoding="utf-8")
    return root


def execution(root, config, factory):
    tools = toolset(root, max_model_calls=96, max_tool_calls=96)
    agent = ModularityAgent(NativeStructuredModel([]), config, investigator_factory=factory,
        tracing_backend=NoOpTracingBackend())
    run = ModularityExecution(agent, tools, ModularityRequest())
    state = run.initial_state()
    state.update(run.plan_assessment(state))
    return run, state


def test_staggered_starts_still_run_three_investigators_concurrently(repo):
    async def execute():
        starts, active, peak = [], 0, 0
        all_started = asyncio.Event()
        def create(key, model, config):
            async def invoke(tools, request):
                nonlocal active, peak
                starts.append(monotonic())
                active += 1
                peak = max(peak, active)
                if len(starts) == 3:
                    all_started.set()
                await asyncio.wait_for(all_started.wait(), 1)
                active -= 1
                return result(key, tools, request)
            return SimpleNamespace(run=invoke)
        run, state = execution(repo, ModularityConfig(max_parallel=3, investigation_start_interval_seconds=0.02), create)
        update = await run.delegate_investigations(state)
        assert peak == 3 and len(starts) == 3
        assert all(b - a >= 0.015 for a, b in pairwise(starts))
        assert all(r.status == "received" for r in update["execution_records"])
    asyncio.run(execute())


def test_start_spacing_is_shared_across_rounds(repo):
    async def execute():
        starts = []
        def create(key, model, config):
            async def invoke(tools, request):
                starts.append(monotonic())
                return result(key, tools, request)
            return SimpleNamespace(run=invoke)
        run, state = execution(repo, ModularityConfig(investigation_start_interval_seconds=0.03), create)
        assignments = state["pending_assignments"]
        state["pending_assignments"] = assignments[:1]
        await run.delegate_investigations(state)
        state["pending_assignments"] = [assignments[1].model_copy(update={"round": 2})]
        await run.delegate_investigations(state)
        assert len(starts) == 2 and starts[1] - starts[0] >= 0.025
    asyncio.run(execute())


def test_deadline_during_start_delay_skips_without_charging_unused_reservations(repo):
    async def execute():
        starts = []
        def create(key, model, config):
            async def invoke(tools, request):
                starts.append(key)
                return result(key, tools, request)
            return SimpleNamespace(run=invoke)
        run, state = execution(repo, ModularityConfig(timeout_seconds=0.1,
            investigation_start_interval_seconds=1), create)
        state.update(await run.delegate_investigations(state))
        records = state["execution_records"]
        assert len(starts) == 1
        skipped = [r for r in records if r.status == "skipped"]
        assert len(skipped) == 2
        assert all(r.error == "assessment_time_exhausted" and r.assignment.budget is None for r in skipped)
        state.update(run.collect_findings(state))
        assert run.spent.model_calls == 4 and run.spent.accounted_tokens == 100
    asyncio.run(execute())


def test_cancellation_during_start_delay_propagates(repo):
    async def execute():
        def create(*args):
            raise AssertionError("No investigator should start during cancellation")
        run, state = execution(repo, ModularityConfig(investigation_start_interval_seconds=1), create)
        run.investigation_start_pacer.next_allowed = monotonic() + 10
        task = asyncio.create_task(run.delegate_investigations(state))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert run.spent.model_calls == 0
    asyncio.run(execute())


def test_start_spacing_and_request_pacing_are_independent(repo):
    run, _ = execution(repo, ModularityConfig(investigation_start_interval_seconds=1,
        provider_request_interval_seconds=0.5, provider_retry_backoff_seconds=5), lambda *args: None)
    assert run.config.max_parallel == 3
    assert run.investigation_start_pacer.interval == 1
    assert run.provider_pacer.interval == 0.5
    assert run.provider_pacer.backoff == 5
