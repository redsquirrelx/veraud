import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from config.agents.execution import AgentExecutionConfig
from server.runtimes.repository.budgeted_model import BudgetedModel
from server.runtimes.repository.shared_tokens import SharedTokenBudget
from server.runtimes.repository.timing import ActiveDeadline


def test_managed_calls_settle_actual_usage_and_stop_at_call_limit():
    async def run():
        limits = AgentExecutionConfig(max_model_calls=4, max_provider_retries=0, provider_request_interval_seconds=0,
            provider_rate_limits={"requests_per_minute": None, "tokens_per_minute": None})
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content="response",
            usage_metadata={"input_tokens": 20, "output_tokens": 5})))
        tokens = SharedTokenBudget(100000)
        runtime = BudgetedModel(model, limits, tokens.fork(), ActiveDeadline(10))
        for _ in range(4):
            assert await runtime.call("prompt") == "response"
        assert tokens.used == 100 and tokens.estimated == 0
        with pytest.raises(ValueError, match="model_call_budget_exhausted"):
            await runtime.call("prompt")
        assert model.ainvoke.await_count == 4

    asyncio.run(run())


@pytest.mark.parametrize("local,shared,expected", [(1000, 100000, "local_token"), (100000, 1000, "shared_token")])
def test_token_limits_block_provider_calls_before_dispatch(local, shared, expected):
    async def run():
        model = SimpleNamespace(ainvoke=AsyncMock())
        runtime = BudgetedModel(model, AgentExecutionConfig(max_total_tokens=local), SharedTokenBudget(shared), ActiveDeadline(10))
        with pytest.raises(ValueError, match=expected):
            await runtime.call("prompt")
        model.ainvoke.assert_not_awaited()

    asyncio.run(run())
