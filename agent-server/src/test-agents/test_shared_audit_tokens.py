"""Offline regression tests for individual allowances and audit-wide admission."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock

from langchain_core.messages import AIMessage, HumanMessage
from test_architecture_boundary import toolset

from server.agents.maintainability.modularity.architecture_boundary import (
    ArchitectureBoundaryAgent,
    BoundaryConfig,
)
from server.runtimes.repository.shared_tokens import SharedTokenBudget


def execution(root, ledger, response):
    model = SimpleNamespace(ainvoke=AsyncMock(side_effect=response))
    model.bind_tools = lambda tools: model
    config = BoundaryConfig(max_total_tokens=1000, max_output_tokens=256,
        provider_rate_limits={"requests_per_minute": None, "tokens_per_minute": None})
    tools = toolset(root)
    tools.token_budget = ledger.fork()
    agent = ArchitectureBoundaryAgent(model, config)
    return agent.execution_type(model, config, tools, agent.request_type()), model


def test_global_reservations_are_atomic_and_known_usage_releases_capacity(tmp_path):
    async def run():
        ledger = SharedTokenBudget(500)
        entered, release = asyncio.Event(), asyncio.Event()

        async def provider(*args, **kwargs):
            entered.set()
            await release.wait()
            return AIMessage(content="ok", usage_metadata={"input_tokens": 10, "output_tokens": 10, "total_tokens": 20})

        first, _ = execution(tmp_path, ledger, provider)
        second, model = execution(tmp_path, ledger, provider)
        messages = [HumanMessage(content="inspect")]
        task = asyncio.create_task(first.provider_request(first.model, messages, "", "investigate", None, 0))
        await entered.wait()
        assert 256 < ledger.used < 500
        await second.provider_request(second.model, messages, "", "investigate", None, 0)
        assert second.stop == "audit_token_limit"
        model.ainvoke.assert_not_awaited()
        release.set()
        await task
        assert ledger.used == first.tokens == 20
        assert ledger.estimated == first.estimates == 0
        third, _ = execution(tmp_path, ledger, provider)
        await third.provider_request(third.model, messages, "", "investigate", None, 0)
        assert ledger.used == 40 and not third.stop

    asyncio.run(run())


def test_personal_limit_does_not_consume_the_global_budget(tmp_path):
    async def run():
        ledger = SharedTokenBudget(10000)
        agent, model = execution(tmp_path, ledger, None)
        agent.tokens = 990
        await agent.provider_request(agent.model, [HumanMessage(content="inspect")], "", "investigate", None, 0)
        assert agent.stop == "token_limit" and ledger.used == 0
        model.ainvoke.assert_not_awaited()

    asyncio.run(run())


def test_cancellation_and_unknown_failure_keep_only_attempted_reservations(tmp_path):
    async def run():
        ledger = SharedTokenBudget(10000)
        entered = asyncio.Event()

        async def blocked(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()

        agent, _ = execution(tmp_path, ledger, blocked)
        task = asyncio.create_task(agent.provider_request(agent.model, [HumanMessage(content="inspect")], "", "investigate", None, 0))
        await entered.wait()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert 0 < ledger.used == agent.tokens == ledger.estimated < 1000
        before = ledger.used

        async def fail(*args, **kwargs):
            raise ValueError("provider failure")

        failed, _ = execution(tmp_path, ledger, fail)
        await failed.provider_request(failed.model, [HumanMessage(content="inspect")], "", "investigate", None, 0)
        assert failed.stop == "model_or_schema_error"
        assert ledger.used == before + failed.tokens
        assert ledger.estimated == ledger.used

    asyncio.run(run())


def test_scopes_share_one_cap_under_concurrent_reservations():
    ledger = SharedTokenBudget(1000)
    branch = ledger.fork()
    workers = [branch.fork() for _ in range(20)]
    with ThreadPoolExecutor(max_workers=20) as pool:
        reservations = list(pool.map(lambda worker: worker.reserve(100), workers))
    assert sum(item is not None for item in reservations) == 10
    assert ledger.used == branch.used == 1000
    for reservation in reservations:
        if reservation is not None:
            reservation.settle(25)
    assert ledger.used == branch.used == 250
    assert ledger.estimated == branch.estimated == 0
    assert sum(worker.used for worker in workers) == 250
