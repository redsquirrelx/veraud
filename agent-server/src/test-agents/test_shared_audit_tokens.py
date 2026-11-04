"""Offline regression tests for individual allowances and audit-wide admission."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from test_architecture_boundary import toolset

from server.agents.maintainability.modularity.architecture_boundary import (
    ArchitectureBoundaryAgent,
    BoundaryConfig,
)
from server.config import token_budget as policy
from server.runtimes.coordination.execution import CoordinatorSynthesisExecution
from server.runtimes.invocation_reporting import (
    invocation_reporting,
    observe_invocation,
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


def test_native_investigator_and_synthesis_calls_publish_separate_cumulative_tokens(tmp_path):
    async def run():
        ledger = SharedTokenBudget(10000)
        receipts = []

        def response(input_tokens, output_tokens):
            return AIMessage(content="ok", usage_metadata={"input_tokens": input_tokens,
                "output_tokens": output_tokens, "total_tokens": input_tokens + output_tokens})

        child, _ = execution(tmp_path, ledger, [response(10, 2), {"raw": response(20, 3), "parsed": None}])
        parent_base, parent_model = execution(tmp_path, ledger, [response(30, 4), response(40, 6)])
        parent = CoordinatorSynthesisExecution(parent_model, parent_base.config, parent_base.tools, parent_base.request)

        async def send(receipt):
            receipts.append(receipt)

        async def calls(runtime):
            await runtime.provider_request(runtime.model, [HumanMessage(content="inspect")], "", "investigate", None, 0)
            return SimpleNamespace(status="completed")

        async def investigate():
            await calls(child)
            return await calls(child)

        async def synthesize():
            await calls(parent)
            await observe_invocation(investigate(), agent_id="investigator", invocation_id="child", run_id="audit")
            return await calls(parent)

        with invocation_reporting(send):
            await observe_invocation(synthesize(), agent_id="manager", invocation_id="parent", run_id="audit")
        child_receipts = [item for item in receipts if item["invocation_id"] == "child"]
        parent_receipts = [item for item in receipts if item["invocation_id"] == "parent"]
        assert [(item["input_tokens"], item["output_tokens"]) for item in child_receipts] == [
            (None, None), (10, 2), (30, 5), (30, 5)]
        assert [(item["input_tokens"], item["output_tokens"]) for item in parent_receipts] == [
            (None, None), (30, 4), (70, 10), (70, 10)]
        assert ledger.used == 115 and ledger.estimated == 0

    asyncio.run(run())


def test_unlimited_launch_allows_native_attempt_past_local_and_shared_caps(tmp_path, monkeypatch):
    path = tmp_path / "launch.json"
    path.write_text('{"unlimited_token_budget": true}', encoding="utf-8")
    monkeypatch.setattr(policy, "LAUNCH_PATH", path)
    policy.token_budget_policy.cache_clear()
    try:
        async def run():
            async def provider(*args, **kwargs):
                return AIMessage(content="ok", usage_metadata={"input_tokens": 700, "output_tokens": 500, "total_tokens": 1200})

            ledger = SharedTokenBudget(1000)
            agent, model = execution(tmp_path, ledger, provider)
            agent.tokens = 990
            response = await agent.provider_request(agent.model, [HumanMessage(content="inspect")], "", "investigate", None, 0)
            assert response is not None and not agent.stop
            model.ainvoke.assert_awaited_once()
            assert ledger.used == 1200 and agent.tokens == 2190
            assert ledger.estimated == 0
            agent.calls = agent.call_limit
            assert await agent.provider_request(agent.model, [HumanMessage(content="inspect")], "", "investigate", None, 0) is None
            assert agent.stop == "model_call_limit"
            model.ainvoke.assert_awaited_once()

        asyncio.run(run())
    finally:
        policy.token_budget_policy.cache_clear()


@pytest.mark.parametrize("result", [AIMessage(content="no usage"), ValueError("provider failed")])
def test_missing_provider_usage_does_not_report_budget_estimates_as_real_tokens(tmp_path, result):
    async def run():
        runtime, _ = execution(tmp_path, SharedTokenBudget(10000), [result])
        receipts = []

        async def send(receipt):
            receipts.append(receipt)

        async def call():
            await runtime.provider_request(runtime.model, [HumanMessage(content="inspect")], "", "investigate", None, 0)
            return SimpleNamespace(status="partial")

        with invocation_reporting(send):
            await observe_invocation(call(), agent_id="investigator", invocation_id="child", run_id="audit")
        assert runtime.tokens > 0 and runtime.estimates == runtime.tokens
        assert all(item["input_tokens"] is None and item["output_tokens"] is None for item in receipts)

    asyncio.run(run())
