"""Operational failure boundaries and provider-resource ownership."""

import asyncio
from time import monotonic
from types import SimpleNamespace

import pytest

from config.agents.provider import ProviderRetryConfig
from server.runtimes.repository.model_runtime import (
    ModelGateway,
    close_model_clients,
    create_project_model,
)


def test_slow_gateway_request_exits_once_and_keeps_failed_usage():
    class Model:
        calls = 0

        async def generate(self, prompt):
            self.calls += 1
            await asyncio.Event().wait()

    model = Model()
    gateway = ModelGateway(model, interval=0,
        provider_config=ProviderRetryConfig(provider_request_timeout_seconds=0.03))

    async def execute():
        task = asyncio.create_task(gateway("bounded request"))
        done, _ = await asyncio.wait({task}, timeout=0.5)
        assert done, "The gateway ignored its per-attempt deadline"
        with pytest.raises(TimeoutError):
            await task

    asyncio.run(execute())
    assert gateway.stopped and model.calls == 1
    assert gateway.calls[0]["attempts"] == gateway.calls[0]["unknown_usage_attempts"] == 1
    assert gateway.measurements[0].status == "failed"


@pytest.mark.parametrize("provider", ["google", "gemini"])
def test_project_gemini_factory_uses_adapter_and_bounds_json_output(monkeypatch, provider):
    from server.config.schemas import ModelCredentials, ModelSettings
    from server.infrastructure.llm import gemini

    requests = []
    keys = []
    response = SimpleNamespace(text='{"ok":true}')

    async def generate_content(**kwargs):
        requests.append(kwargs)
        return response

    def client(**kwargs):
        keys.append(kwargs["api_key"])
        return SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))

    monkeypatch.setattr(gemini.genai, "Client", client)
    model = create_project_model(
        ModelSettings(provider=provider, name="gemini-test", temperature=0.3, max_tokens=1200),
        ModelCredentials(api_key="fake-key"),
    )
    assert isinstance(model, gemini.GeminiModel)
    assert keys == ["fake-key"]
    assert asyncio.run(model.generate("first")) is response
    assert asyncio.run(model.generate_with_output_limit("second", max_output_tokens=200)) is response
    assert asyncio.run(model.generate_with_output_limit("third", max_output_tokens=2000)) is response
    assert [request["contents"] for request in requests] == ["first", "second", "third"]
    assert [request["config"].max_output_tokens for request in requests] == [1200, 200, 1200]
    assert all(request["model"] == "gemini-test" for request in requests)
    assert all(request["config"].temperature == 0.3 for request in requests)
    assert all(request["config"].response_mime_type == "application/json" for request in requests)


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
        provider_config=ProviderRetryConfig(provider_recovery_budget_seconds=120),
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
        response = SimpleNamespace(headers={"retry-after": "90"})

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
        remaining_seconds=lambda: 60,
        on_event=lambda event, values: events.append((event, values)),
    )
    with pytest.raises(ProviderError):
        asyncio.run(gateway("input"))
    skipped = next(
        values for event, values in events if event == "provider_retry_skipped"
    )
    assert skipped["requested_wait_seconds"] == 90
    assert skipped["remaining_budget_seconds"] == 60
    assert skipped["http_status"] == 429
    assert model.calls == 1 and gateway.stopped
    assert not any(event == "provider_wait" for event, _ in events)
    assert gateway.calls[0]["status"] == "failed"
    assert gateway.pacer.next_allowed - monotonic() < 1


def test_gateway_rejects_hours_long_provider_wait_without_wall_deadline():
    class ProviderError(Exception):
        status_code = 429
        response = SimpleNamespace(headers={"retry-after": "44378"})

    class Model:
        calls = 0

        async def generate(self, prompt):
            self.calls += 1
            raise ProviderError()

    events = []
    model = Model()
    gateway = ModelGateway(model, on_event=lambda event, values: events.append((event, values)))
    with pytest.raises(ProviderError):
        asyncio.run(gateway("input"))
    skipped = next(values for event, values in events if event == "provider_retry_skipped")
    assert skipped["reason"] == "provider_retry_wait_limit"
    assert skipped["requested_wait_seconds"] == 44378
    assert model.calls == 1 and gateway.stopped
    assert gateway.calls[0]["unknown_usage_attempts"] == 1
    assert not any(event == "provider_wait" for event, _ in events)


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
