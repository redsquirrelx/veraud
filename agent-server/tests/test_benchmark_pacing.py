import asyncio
import json
from types import SimpleNamespace

import pytest
from test_benchmark import ScriptedModel

from server.benchmark.pacing import RequestPacer, retry_after
from server.benchmark.telemetry import MeasuredModel, call_metrics
from server.run_benchmark import build_parser


class ProviderError(Exception):
    def __init__(self, code, headers=None, details=None):
        super().__init__("private-provider-detail")
        self.code = code
        self.response = SimpleNamespace(headers=headers or {})
        self.details = details


@pytest.fixture
def clock(monkeypatch):
    from server.benchmark import pacing

    state = SimpleNamespace(now=100.0, waits=[])
    async def sleep(seconds):
        state.waits.append(seconds)
        state.now += seconds
    monkeypatch.setattr(pacing, "time", SimpleNamespace(monotonic=lambda: state.now))
    monkeypatch.setattr(pacing, "asyncio", SimpleNamespace(Lock=asyncio.Lock, sleep=sleep))
    return state


def test_shared_pause_applies_between_models_and_successful_calls(clock):
    pacer = RequestPacer(interval=12)
    first = MeasuredModel(ScriptedModel([{}, {}]), pacer)
    second = MeasuredModel(ScriptedModel([{}]), pacer)
    async def run():
        await first.generate("analyzer")
        await second.generate("architect")
        await first.generate("judge")
    asyncio.run(run())
    assert clock.waits == [12, 12]
    assert first.calls[1]["wait_seconds"] == 12


def test_429_respects_retry_after_and_success_does_not_count_as_failure(clock, capsys):
    model = MeasuredModel(ScriptedModel([ProviderError(429, {"retry-after": "90"}), {}]), RequestPacer(interval=12, max_retries=2, backoff=30))
    asyncio.run(model.generate("prompt"))
    assert clock.waits == [90]
    assert model.calls[0]["status"] == "completed"
    assert [item["status"] for item in model.calls[0]["attempts"]] == ["failed", "completed"]
    metrics = call_metrics(model.calls, 1, 2)
    assert metrics["failed_calls"] == 0
    assert metrics["retry_attempts"] == 1
    assert metrics["rate_limit_events"] == 1
    assert metrics["usage_complete"] is False
    assert metrics["cost_usd"] is None
    output = capsys.readouterr().out
    assert "HTTP 429" in output
    assert "private-provider-detail" not in output + json.dumps(model.calls)


def test_exponential_backoff_and_exhaustion_cool_down_the_next_agent(clock):
    pacer = RequestPacer(interval=12, max_retries=2, backoff=30)
    first = MeasuredModel(ScriptedModel([ProviderError(429) for _ in range(3)]), pacer)
    second = MeasuredModel(ScriptedModel([{}]), pacer)
    async def run():
        with pytest.raises(ProviderError):
            await first.generate("first")
        await second.generate("second")
    asyncio.run(run())
    assert clock.waits == [30, 60, 120]
    assert len(first.calls[0]["attempts"]) == 3
    assert first.calls[0]["http_status"] == 429
    assert second.calls[0]["wait_seconds"] == 120


def test_authentication_errors_are_not_retried(clock):
    model = MeasuredModel(ScriptedModel([ProviderError(401), {}]), RequestPacer(max_retries=3))
    with pytest.raises(ProviderError):
        asyncio.run(model.generate("prompt"))
    assert len(model.calls[0]["attempts"]) == 1
    assert clock.waits == []


def test_gemini_retry_info_and_http_hint_choose_the_longer_wait():
    error = ProviderError(429, {"retry-after": "30"}, {"error": {"details": [
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "150.5s"},
    ]}})
    assert retry_after(error) == 150.5
    assert retry_after(ProviderError(429, {"retry-after": "nan"})) == 0


def test_cancellation_during_backoff_stops_retries_and_releases_gate(monkeypatch):
    from server.benchmark import pacing

    async def cancelled_sleep(seconds):
        raise asyncio.CancelledError
    monkeypatch.setattr(pacing, "asyncio", SimpleNamespace(Lock=asyncio.Lock, sleep=cancelled_sleep))
    pacer = RequestPacer(max_retries=3)
    model = MeasuredModel(ScriptedModel([ProviderError(429), {}]), pacer)
    async def run():
        with pytest.raises(asyncio.CancelledError):
            await model.generate("prompt")
    asyncio.run(run())
    assert len(model.calls[0]["attempts"]) == 1
    assert model.calls[0]["status"] == "cancelled"
    assert not pacer.lock.locked()


def test_cli_defaults_and_overrides_are_validated():
    parser = build_parser()
    defaults = parser.parse_args(["run"])
    assert defaults.request_interval == 12
    assert defaults.max_retries == 3
    assert defaults.retry_backoff == 30
    for flag, value in (("--request-interval", "nan"), ("--max-retries", "-1"), ("--retry-backoff", "-1")):
        with pytest.raises(SystemExit):
            parser.parse_args(["run", flag, value])
