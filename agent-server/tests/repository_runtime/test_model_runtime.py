"""Operational failure boundaries and provider-resource ownership."""

import asyncio
from time import monotonic
from types import SimpleNamespace

import pytest

from server.runtimes.repository.model_runtime import (
    ModelGateway,
    close_model_clients,
)


def test_retry_requires_token_admission_and_counts_only_submitted_attempts():
    from server.runtimes.repository.schemas import ExecutionBudget
    from server.runtimes.repository.telemetry import measured_prompt
    from server.runtimes.repository.token_budget import (
        TokenBudgetExceeded,
        account_tokens,
        admit_request,
    )

    class ProviderError(Exception):
        status_code = 503

    class Model:
        calls = 0

        async def generate(self, prompt):
            self.calls += 1
            raise ProviderError()

    model = Model()
    gateway = ModelGateway(model, max_retries=2, backoff=0)
    budget = ExecutionBudget(max_total_tokens=5000)
    prompt = measured_prompt(
        [("Inspect main", "instructions")],
        stage="investigation",
        objective_id="objective:main",
    )
    gateway.request_guard = lambda text, attempts: admit_request(
        gateway, budget, text, "objective:main", attempts
    )
    with pytest.raises(TokenBudgetExceeded):
        asyncio.run(gateway(prompt))
    assert model.calls == gateway.usage_totals()["provider_attempts"] == 1
    assert gateway.measurements[0].unknown_usage_attempts == 1
    accounted, estimated = account_tokens(gateway, budget)
    assert accounted == estimated < budget.max_total_tokens


def test_gateway_retry_text_normalization_usage_and_terminal_stop():
    class ProviderError(Exception):
        status_code = 503

    class Model:
        calls = 0

        async def generate(self, prompt):
            self.calls += 1
            if self.calls == 1:
                raise ProviderError()
            return SimpleNamespace(
                content='```json\n{"ok": true}\n```',
                usage_metadata={"input_tokens": 11, "output_tokens": 4},
            )

    gateway = ModelGateway(Model(), max_retries=1, backoff=0)
    assert asyncio.run(gateway("input")) == '{"ok": true}'
    assert gateway.usage_totals()["provider_retries"] == 1
    assert gateway.usage_totals()["provider_attempts"] == 2
    assert gateway.usage_totals()["input_tokens"] is None
    assert gateway.usage_totals()["reported_input_tokens"] == 11
    assert gateway.usage_totals()["reported_output_tokens"] == 4
    assert gateway.usage_totals()["unknown_usage_attempts"] == 1
    stage = gateway.telemetry().stages[0]
    assert stage.reported_input_tokens == 11 and stage.reported_output_tokens == 4
    assert stage.input_tokens is None and stage.unknown_usage_attempts == 1

    class Broken:
        async def generate(self, prompt):
            raise ProviderError()

    broken = ModelGateway(Broken(), max_retries=0)
    with pytest.raises(ProviderError):
        asyncio.run(broken("input"))
    assert broken.stopped and broken.usage_totals()["input_tokens"] is None
    with pytest.raises(RuntimeError, match="terminal failure"):
        asyncio.run(broken("input"))
    assert len(broken.calls) == 1


def test_gateway_explains_provider_retry_after_without_real_wait(monkeypatch):
    class ProviderError(Exception):
        status_code = 429
        response = SimpleNamespace(headers={"retry-after": "90"})

    class Model:
        calls = 0

        async def generate(self, prompt):
            self.calls += 1
            if self.calls == 1:
                raise ProviderError()
            return "{}"

    events = []
    gateway = ModelGateway(
        Model(),
        max_retries=1,
        backoff=2,
        on_event=lambda event, values: events.append((event, values)),
    )

    async def no_wait():
        return 0

    monkeypatch.setattr(gateway.pacer, "wait", no_wait)
    assert asyncio.run(gateway("input")) == "{}"
    retry = next(values for event, values in events if event == "provider_retry")
    wait = next(values for event, values in events if event == "provider_wait")
    assert retry["reason"] == wait["reason"] == "provider_retry_after"
    assert retry["provider_retry_after_seconds"] == 90
    assert wait["http_status"] == 429 and wait["attempt"] == 2
    assert 89 < wait["wait_seconds"] <= 90


def test_gateway_skips_retry_beyond_budget_without_poisoning_shared_pacer():
    class ProviderError(Exception):
        status_code = 429
        response = SimpleNamespace(headers={"retry-after": "78093"})

    class Model:
        calls = 0

        async def generate(self, prompt):
            self.calls += 1
            raise ProviderError()

    events = []
    model = Model()
    gateway = ModelGateway(
        model,
        max_retries=2,
        remaining_seconds=lambda: 600,
        on_event=lambda event, values: events.append((event, values)),
    )
    with pytest.raises(ProviderError):
        asyncio.run(gateway("input"))
    skipped = next(
        values for event, values in events if event == "provider_retry_skipped"
    )
    assert skipped["requested_wait_seconds"] == 78093
    assert skipped["remaining_budget_seconds"] == 600
    assert skipped["http_status"] == 429
    assert model.calls == 1 and gateway.stopped
    assert not any(event == "provider_wait" for event, _ in events)
    assert gateway.calls[0]["status"] == "failed"
    assert gateway.pacer.next_allowed - monotonic() < 1


def test_gateway_cancellation_records_attempt_and_cleanup_attempts_every_resource():
    async def scenario():
        entered = asyncio.Event()

        class Model:
            async def generate(self, prompt):
                entered.set()
                await asyncio.sleep(3600)

        gateway = ModelGateway(Model())
        task = asyncio.create_task(gateway("input"))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert gateway.calls[0]["status"] == "cancelled"
        assert gateway.usage_totals()["provider_attempts"] == 1
        closed = []

        class AsyncClient:
            async def aclose(self):
                closed.append("async")
                raise RuntimeError("cleanup failure")

        class Client:
            aio = AsyncClient()

            def close(self):
                closed.append("sync")

        assert await close_model_clients(SimpleNamespace(client=Client())) == (
            "RuntimeError",
        )
        assert closed == ["async", "sync"]

    asyncio.run(scenario())
