"""Offline: uv run pytest src/test-agents/test_provider_quotas.py -q.

Rolling-window tests use a virtual clock: no provider requests or minute-long sleeps.
"""

import asyncio

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError
from test_architecture_boundary import ScriptedModel, toolset
from test_modularity_e2e import ProviderScenario, request
from test_modularity_provider import rate_limit

from server.agents.maintainability.modularity.architecture_boundary import (
    ArchitectureBoundaryAgent,
    BoundaryConfig,
)
from server.agents.maintainability.modularity.coordinator import (
    ModularityAgent,
    ModularityConfig,
    ModularityRequest,
)
from server.agents.maintainability.modularity.coordinator.agent import _Execution
from server.runtimes.investigation.provider import (
    ProviderPacer,
    RequestTokenQuotaExceeded,
)
from server.runtimes.investigation.schemas import ProviderRateLimits, Review
from server.app.tracing_port import NoOpTracingBackend


class Clock:
    def __init__(self):
        self.now = 0.0
        self.waits = []

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


def pacer(clock, rpm=14, tpm=250_000):
    return ProviderPacer(rate_limits=ProviderRateLimits(requests_per_minute=rpm, tokens_per_minute=tpm),
        clock=clock, sleep=clock.sleep)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "main.py").write_text("value = 1\n", encoding="utf-8")
    return root


def test_defaults_apply_to_standalone_and_coordinator():
    for config in (BoundaryConfig(), ModularityConfig(), ModularityConfig().invocation_limits):
        assert config.provider_rate_limits.requests_per_minute == 14
        assert config.provider_rate_limits.tokens_per_minute == 250_000
    config = ModularityConfig.model_validate({"provider_rate_limits": {"requests_per_minute": 10}})
    assert config.provider_rate_limits.requests_per_minute == 10
    assert config.provider_rate_limits.tokens_per_minute == 250_000


def test_fifteenth_concurrent_request_waits_for_rolling_minute():
    async def execute():
        clock = Clock()
        limiter = pacer(clock)
        records = await asyncio.gather(*(limiter.acquire(1) for _ in range(15)))
        assert [r.started_at for r in records] == [0] * 14 + [60]
        assert clock.waits == [60]
    asyncio.run(execute())


def test_tpm_reservations_block_even_when_rpm_is_available():
    async def execute():
        clock = Clock()
        limiter = pacer(clock)
        await limiter.acquire(100_000)
        await limiter.acquire(150_000)
        record = await limiter.acquire(1)
        assert record.started_at == 60 and clock.waits == [60]
    asyncio.run(execute())


def test_joint_limits_wait_until_both_have_capacity():
    async def execute():
        clock = Clock()
        limiter = pacer(clock, rpm=2, tpm=250)
        await limiter.acquire(100)
        clock.now = 10
        await limiter.acquire(100)
        record = await limiter.acquire(200)
        assert record.started_at == 70
        assert clock.waits == [60]
    asyncio.run(execute())


def test_window_does_not_reset_at_calendar_minute_boundary():
    async def execute():
        clock = Clock()
        clock.now = 59
        limiter = pacer(clock, rpm=1)
        await limiter.acquire(1)
        clock.now = 60
        record = await limiter.acquire(1)
        assert record.started_at == 119
    asyncio.run(execute())


def test_reported_usage_releases_unused_token_reservation():
    async def execute():
        clock = Clock()
        limiter = pacer(clock)
        first = await limiter.acquire(200_000)
        limiter.settle(first, 10_000)
        second = await limiter.acquire(240_000)
        assert second.started_at == 0 and not clock.waits
        assert sum(r.tokens for r in limiter.reservations) == 250_000
    asyncio.run(execute())


def test_usage_reconciliation_wakes_a_waiting_request_without_a_minute_delay():
    async def execute():
        limiter = ProviderPacer(rate_limits=ProviderRateLimits(tokens_per_minute=1000))
        first = await limiter.acquire(900)
        waiting = asyncio.Event()
        task = asyncio.create_task(limiter.acquire(200, on_wait=lambda *args: waiting.set()))
        await asyncio.wait_for(waiting.wait(), 1)
        assert not task.done()
        limiter.settle(first, 100)
        second = await asyncio.wait_for(task, 1)
        assert second.tokens == 200
    asyncio.run(execute())


def test_reported_usage_can_raise_reservation_and_delay_future_requests():
    async def execute():
        clock = Clock()
        limiter = pacer(clock, tpm=1000)
        first = await limiter.acquire(100)
        limiter.settle(first, 900)
        second = await limiter.acquire(200)
        assert second.started_at == 60
    asyncio.run(execute())


def test_single_request_above_tpm_fails_without_wait_or_reservation():
    async def execute():
        clock = Clock()
        limiter = pacer(clock, tpm=1000)
        with pytest.raises(RequestTokenQuotaExceeded):
            await limiter.acquire(1001)
        assert not clock.waits and not limiter.reservations
    asyncio.run(execute())


def test_disabled_limits_do_not_create_minute_waits():
    async def execute():
        clock = Clock()
        limiter = pacer(clock, rpm=None, tpm=None)
        await asyncio.gather(*(limiter.acquire(300_000) for _ in range(30)))
        assert not clock.waits
    asyncio.run(execute())


def test_quota_wait_is_cancellable_without_counting_an_unstarted_request():
    async def execute():
        limiter = ProviderPacer(rate_limits=ProviderRateLimits(requests_per_minute=1))
        await limiter.acquire(1)
        waiting = asyncio.Event()
        task = asyncio.create_task(limiter.acquire(1, on_wait=lambda *args: waiting.set()))
        await asyncio.wait_for(waiting.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(limiter.reservations) == 1 and not limiter.lock.locked()
    asyncio.run(execute())


def test_retry_counts_against_rpm_and_respects_execution_deadline(repo):
    model = ScriptedModel([rate_limit("0s")])
    config = BoundaryConfig(timeout_seconds=0.05, provider_retry_backoff_seconds=0,
        provider_rate_limits=ProviderRateLimits(requests_per_minute=1))
    run = ArchitectureBoundaryAgent.execution_type(model, config, toolset(repo), ArchitectureBoundaryAgent.request_type())
    value = asyncio.run(run.call("review_findings", run.initial_state(), Review))
    assert value is None and run.stop == "time_limit"
    assert run.calls == len(model.history) == len(run.provider_pacer.reservations) == 1
    assert run.provider_pacer.reservations[0].tokens == run.tokens > 0


def test_runtime_reconciles_provider_reported_usage(repo):
    model = ScriptedModel([AIMessage(content='{"findings": [], "limitations": []}',
        usage_metadata={"input_tokens": 100, "output_tokens": 30, "total_tokens": 130})])
    run = ArchitectureBoundaryAgent.execution_type(model, BoundaryConfig(), toolset(repo), ArchitectureBoundaryAgent.request_type())
    value = asyncio.run(run.call("review_findings", run.initial_state(), Review))
    assert value is not None and run.provider_pacer.reservations[0].tokens == run.tokens == 130


def test_runtime_rejects_oversized_tpm_request_before_provider_call(repo):
    model = ScriptedModel([])
    config = BoundaryConfig(provider_rate_limits=ProviderRateLimits(tokens_per_minute=1))
    run = ArchitectureBoundaryAgent.execution_type(model, config, toolset(repo), ArchitectureBoundaryAgent.request_type())
    value = asyncio.run(run.call("review_findings", run.initial_state(), Review))
    assert value is None and run.stop == "provider_tpm_request_limit"
    assert run.calls == run.tokens == 0 and not model.history


def test_coordinator_synthesis_and_investigators_share_injected_quota(repo):
    shared = ProviderPacer(rate_limits=ProviderRateLimits())
    model = ScriptedModel([])
    agent = ModularityAgent(model, provider_pacer=shared)
    run = _Execution(agent, toolset(repo, max_model_calls=96), ModularityRequest())
    assert run.provider_pacer is run.synth.provider_pacer is shared
    child = ArchitectureBoundaryAgent(model, provider_pacer=shared)
    assert child.provider_pacer is shared


def test_real_coordinator_and_three_investigators_share_fourteen_rpm(repo, monkeypatch):
    (repo / "domain").mkdir()
    (repo / "storage").mkdir()
    (repo / "domain" / "service.py").write_text(
        "from storage.db import save\n\ndef execute(order):\n    save(order)\n    return str(order)\n", encoding="utf-8")
    (repo / "storage" / "db.py").write_text("def save(order):\n    return order\n", encoding="utf-8")
    clock = Clock()
    shared = pacer(clock)
    starts = []
    acquire = shared.acquire
    async def observe(*args, **kwargs):
        reservation = await acquire(*args, **kwargs)
        starts.append(reservation.started_at)
        return reservation
    monkeypatch.setattr(shared, "acquire", observe)
    model = ProviderScenario()
    agent = ModularityAgent(model, provider_pacer=shared, tracing_backend=NoOpTracingBackend())
    assessment = asyncio.run(agent.run(toolset(repo, max_model_calls=96, max_tool_calls=96), request()))
    assert assessment.status == "completed" and len(assessment.invocations) == 3
    assert len(starts) == len(model.history) == assessment.consumption.model_calls == 16
    assert starts == [0] * 14 + [60] * 2
    assert clock.waits == [60]  # one shared quota, not fourteen requests per investigator


@pytest.mark.parametrize("field", ["requests_per_minute", "tokens_per_minute"])
@pytest.mark.parametrize("value", [0, -1])
def test_invalid_quota_values_are_rejected(field, value):
    with pytest.raises(ValidationError):
        ProviderRateLimits(**{field: value})
