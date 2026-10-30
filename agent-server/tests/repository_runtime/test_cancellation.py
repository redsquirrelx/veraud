import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from server.infrastructure.llm import quota
from server.infrastructure.llm.retry import RequestPacer
from server.runtimes.cancellation import AuditCancellation, cancellation_scope
from server.runtimes.invocation_reporting import (
    invocation_reporting,
    observe_invocation,
    phase_node,
)
from server.runtimes.repository.timing import ActiveDeadline, within_deadline


def test_cancelled_scope_rejects_new_work_without_affecting_other_audits():
    async def run():
        signal = AuditCancellation(lambda: None)
        operation = AsyncMock()
        with cancellation_scope(signal):
            timing = ActiveDeadline(10)
            signal.request()
            assert not timing.publication_allowed
            with pytest.raises(asyncio.CancelledError):
                await within_deadline(operation(), timing)
            with pytest.raises(asyncio.CancelledError):
                await observe_invocation(operation(), agent_id="test", invocation_id="one", run_id="audit")
            with pytest.raises(asyncio.CancelledError):
                await phase_node("investigate", operation)({}, {})
            with pytest.raises(asyncio.CancelledError):
                timing.fork(5)
        with cancellation_scope(AuditCancellation(lambda: None)):
            assert ActiveDeadline(10).publication_allowed
            await within_deadline(operation(), ActiveDeadline(10))
        operation.assert_awaited_once()

    asyncio.run(run())


def test_cancellation_during_quota_wait_does_not_make_another_provider_attempt(monkeypatch):
    async def run():
        signal = AuditCancellation(lambda: None)
        attempts = []
        provider = AsyncMock()

        class Store:
            def acquire(self, *args):
                attempts.append("quota")
                return None, {"rpm": 0}

        monkeypatch.setattr(quota, "global_quota_store", lambda: Store())
        monkeypatch.setattr(quota, "model_quota_scope", lambda model: "offline")
        with cancellation_scope(signal):
            with pytest.raises(asyncio.CancelledError):
                await quota.acquire_global("offline", None, 10, on_wait=lambda *args: signal.request())
            with pytest.raises(asyncio.CancelledError):
                await quota.quota_generate(SimpleNamespace(), "prompt", provider)
            with pytest.raises(asyncio.CancelledError):
                await RequestPacer().wait()
        assert attempts == ["quota"]
        provider.assert_not_awaited()

    asyncio.run(run())


def test_cancellation_keeps_recorded_invocation_usage_and_publishes_final_receipt():
    from server.runtimes.invocation_reporting import report_invocation_usage

    async def run():
        receipts = []
        entered = asyncio.Event()

        async def report(receipt):
            receipts.append(receipt)

        async def operation():
            class Usage:
                def usage_totals(self):
                    return {"input_tokens": 123, "output_tokens": 45}

            await report_invocation_usage(Usage())
            entered.set()
            await asyncio.Event().wait()

        with invocation_reporting(report):
            task = asyncio.create_task(observe_invocation(operation(), agent_id="test", invocation_id="one", run_id="audit"))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert receipts[-1]["status"] == "cancelled"
        assert receipts[-1]["input_tokens"] == 123
        assert receipts[-1]["output_tokens"] == 45
        assert receipts[-1]["finished_at"] is not None

    asyncio.run(run())
