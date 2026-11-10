import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from config.agents.execution import AgentExecutionConfig
from server.agents.architecture_context.schemas import RetrievalPlan
from server.runtimes.investigation.structured import parse_structured, safe_diagnostic
from server.runtimes.repository.budgeted_model import BudgetedModel
from server.runtimes.repository.shared_tokens import SharedTokenBudget
from server.runtimes.repository.timing import ActiveDeadline


@pytest.mark.parametrize(
    "code",
    [
        "context_budget_exhausted",
        "model_call_budget_exhausted",
        "local_token_budget_exhausted",
        "shared_token_budget_exhausted",
    ],
)
def test_budget_diagnostics_expose_only_trusted_codes(code):
    assert safe_diagnostic(ValueError(code)) == code
    assert "private source" not in safe_diagnostic(
        ValueError(code + ": private source")
    )


@pytest.mark.usefixtures("finite_token_budget")
def test_failed_large_output_request_can_exhaust_retry_budget_without_hiding_cause():
    class ProviderError(Exception):
        status_code = 503

    async def run():
        provider = SimpleNamespace(ainvoke=AsyncMock(side_effect=ProviderError()))
        limits = AgentExecutionConfig(
            max_output_tokens=64000,
            max_total_tokens=100000,
            max_provider_retries=1,
            provider_request_interval_seconds=0,
            provider_retry_backoff_seconds=0,
            provider_rate_limits={
                "requests_per_minute": None,
                "tokens_per_minute": None,
            },
        )
        runtime = BudgetedModel(
            provider, limits, SharedTokenBudget(100000), ActiveDeadline(10)
        )
        with pytest.raises(ValueError) as failure:
            await runtime.call("prompt", schema=RetrievalPlan)
        assert safe_diagnostic(failure.value) == "local_token_budget_exhausted"
        provider.ainvoke.assert_awaited_once()
        assert runtime.attempts == 1
        assert runtime.tokens.used == 64000 + len("prompt")

    asyncio.run(run())


@pytest.mark.parametrize("duplicate", [False, True])
def test_native_schema_preserves_raw_json_usage_and_shared_call_budget(duplicate):
    async def run():
        raw = SimpleNamespace(
            content='{"tasks": [], "tasks": []}' if duplicate else '{"tasks": []}',
            usage_metadata={"input_tokens": 20, "output_tokens": 5},
        )
        wrapper = SimpleNamespace(
            ainvoke=AsyncMock(
                return_value={
                    "raw": raw,
                    "parsed": {"tasks": []},
                    "parsing_error": None,
                }
            )
        )
        model = SimpleNamespace(
            ainvoke=AsyncMock(return_value=raw),
            with_structured_output=Mock(return_value=wrapper),
        )
        limits = AgentExecutionConfig(
            max_model_calls=4,
            max_provider_retries=0,
            provider_request_interval_seconds=0,
            provider_rate_limits={
                "requests_per_minute": None,
                "tokens_per_minute": None,
            },
        )
        runtime = BudgetedModel(
            model, limits, SharedTokenBudget(100000), ActiveDeadline(10)
        )
        text = await runtime.call("prompt", schema=RetrievalPlan)
        assert text is raw and runtime.tokens.used == 25 and runtime.attempts == 1
        native_schema = model.with_structured_output.call_args.args[0]
        assert "tasks" in native_schema["properties"]
        assert model.with_structured_output.call_args.kwargs == {
            "method": "json_schema",
            "include_raw": True,
        }
        if duplicate:
            with pytest.raises(ValueError, match="Duplicate JSON keys"):
                parse_structured(text, RetrievalPlan, native=False)
        else:
            assert parse_structured(text, RetrievalPlan, native=False).tasks == []
        await runtime.call("plain prompt")
        assert model.ainvoke.await_count == wrapper.ainvoke.await_count == 1
        assert runtime.tokens.used == 50 and runtime.attempts == 2
        await runtime.call("plain prompt")
        await runtime.call("plain prompt")
        with pytest.raises(ValueError, match="model_call_budget_exhausted"):
            await runtime.call("prompt", schema=RetrievalPlan)
        assert wrapper.ainvoke.await_count == 1

    asyncio.run(run())


def test_only_global_switch_disables_model_call_limit_and_attempts_still_count(monkeypatch):
    from config.agents.budgets import BudgetPolicy
    from server.agent_services.budgeting import policy

    async def run():
        provider = SimpleNamespace(
            ainvoke=AsyncMock(
                return_value=SimpleNamespace(
                    content="{}",
                    usage_metadata={"input_tokens": 2, "output_tokens": 1},
                )
            )
        )
        limits = AgentExecutionConfig(
            max_model_calls=4,
            max_provider_retries=0,
            provider_request_interval_seconds=0,
            provider_rate_limits={
                "requests_per_minute": None,
                "tokens_per_minute": None,
            },
        )
        runtime = BudgetedModel(
            provider, limits, SharedTokenBudget(100_000), ActiveDeadline(10)
        )
        runtime.attempts = limits.max_model_calls
        with pytest.raises(ValueError, match="model_call_budget_exhausted"):
            await runtime.call("normally capped")
        monkeypatch.setattr(policy, "token_budget_policy", lambda: BudgetPolicy(budgets_enabled=False))
        await runtime.call("global budgets disabled")
        assert provider.ainvoke.await_count == 1
        assert runtime.attempts == limits.max_model_calls + 1
        assert runtime.tokens.used == 3

    asyncio.run(run())


def test_unsupported_native_schema_uses_validated_json_fallback():
    async def run():
        model = SimpleNamespace(
            ainvoke=AsyncMock(return_value=SimpleNamespace(content='{"tasks": []}')),
            with_structured_output=Mock(side_effect=NotImplementedError),
        )
        runtime = BudgetedModel(
            model, AgentExecutionConfig(), SharedTokenBudget(100000), ActiveDeadline(10)
        )
        assert (
            parse_structured(
                await runtime.call("prompt", schema=RetrievalPlan),
                RetrievalPlan,
                native=False,
            ).tasks
            == []
        )
        model.ainvoke.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize(
    "reason,expected",
    [
        ("MAX_TOKENS", "output_token_limit_reached"),
        ("length", "output_token_limit_reached"),
        ("SAFETY", "provider_content_filter"),
    ],
)
def test_structured_finish_reason_is_not_lost_or_accepted_as_complete(reason, expected):
    async def run():
        # Even syntactically valid partial JSON must not establish complete coverage.
        response = SimpleNamespace(
            content='{"tasks": []}',
            response_metadata={"finish_reason": reason},
            usage_metadata={"input_tokens": 20, "output_tokens": 5},
        )
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=response))
        runtime = BudgetedModel(
            model, AgentExecutionConfig(), SharedTokenBudget(100000), ActiveDeadline(10)
        )
        with pytest.raises(ValueError, match=expected):
            await runtime.call("prompt", schema=RetrievalPlan)
        assert runtime.tokens.used == 25 and runtime.attempts == 1
        model.ainvoke.assert_awaited_once()

    asyncio.run(run())


def test_managed_calls_settle_actual_usage_and_stop_at_call_limit():
    async def run():
        limits = AgentExecutionConfig(
            max_model_calls=4,
            max_provider_retries=0,
            provider_request_interval_seconds=0,
            provider_rate_limits={
                "requests_per_minute": None,
                "tokens_per_minute": None,
            },
        )
        model = SimpleNamespace(
            ainvoke=AsyncMock(
                return_value=SimpleNamespace(
                    content="response",
                    usage_metadata={"input_tokens": 20, "output_tokens": 5},
                )
            )
        )
        tokens = SharedTokenBudget(100000)
        runtime = BudgetedModel(model, limits, tokens.fork(), ActiveDeadline(10))
        for _ in range(4):
            assert await runtime.call("prompt") == "response"
        assert tokens.used == 100 and tokens.estimated == 0
        with pytest.raises(ValueError, match="model_call_budget_exhausted"):
            await runtime.call("prompt")
        assert model.ainvoke.await_count == 4

    asyncio.run(run())


@pytest.mark.parametrize(
    "local,shared,expected",
    [(1000, 100000, "local_token"), (100000, 1000, "shared_token")],
)
@pytest.mark.usefixtures("finite_token_budget")
def test_token_limits_block_provider_calls_before_dispatch(local, shared, expected):
    async def run():
        model = SimpleNamespace(ainvoke=AsyncMock())
        runtime = BudgetedModel(
            model,
            AgentExecutionConfig(max_total_tokens=local),
            SharedTokenBudget(shared),
            ActiveDeadline(10),
        )
        with pytest.raises(ValueError, match=expected):
            await runtime.call("prompt")
        model.ainvoke.assert_not_awaited()

    asyncio.run(run())
