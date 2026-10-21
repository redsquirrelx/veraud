import asyncio
from types import SimpleNamespace

import pytest

from server.runtimes.invocation_reporting import (
    invocation_reporting,
    observe_invocation,
    phase_node,
    report_invocation_phase,
    report_invocation_usage,
)


def test_concurrent_roots_keep_parents_and_usage_scoped_and_preserve_cancellation():
    async def run():
        receipts = []
        entered = asyncio.Event()
        release = asyncio.Event()

        async def send(receipt):
            receipts.append(receipt)

        async def child():
            class Runtime:
                def usage_totals(self):
                    return {"input_tokens": 9, "output_tokens": 2}

            await report_invocation_usage(Runtime())
            entered.set()
            await release.wait()

        async def root():
            await observe_invocation(child(), agent_id="investigator", invocation_id="child", run_id="a")

        async def sibling():
            await entered.wait()
            return SimpleNamespace(status="complete")

        with invocation_reporting(send):
            first = asyncio.create_task(observe_invocation(root(), agent_id="manager", invocation_id="root-a", run_id="a"))
            second = asyncio.create_task(observe_invocation(sibling(), agent_id="security", invocation_id="root-b", run_id="b"))
            await second
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
        assert next(item for item in receipts if item["invocation_id"] == "root-b")["parent_invocation_id"] is None
        children = [item for item in receipts if item["invocation_id"] == "child"]
        assert all(item["parent_invocation_id"] == "root-a" for item in children)
        assert children[-1]["status"] == "cancelled"
        assert children[-1]["input_tokens"] == 9
        assert children[-1]["finished_at"] is not None
        assert all(item["input_tokens"] is None for item in receipts if item["invocation_id"] == "root-a")

    asyncio.run(run())


def test_graph_phases_remain_scoped_to_invocations_and_clear_on_completion():
    async def run():
        receipts = []

        async def send(receipt):
            receipts.append(receipt)

        async def child(state):
            await report_invocation_phase("investigate")
            await report_invocation_phase("investigate")
            return SimpleNamespace(status="completed")

        async def root():
            await report_invocation_phase("delegate_auditors")
            await observe_invocation(phase_node("plan_investigation", child)({}, {}),
                agent_id="investigator", invocation_id="child", run_id="audit")
            return SimpleNamespace(status="completed")

        with invocation_reporting(send):
            await observe_invocation(root(), agent_id="manager", invocation_id="root", run_id="audit")
        children = [receipt for receipt in receipts if receipt["invocation_id"] == "child"]
        assert [receipt["phase"] for receipt in children] == [None, "plan_investigation", "investigate", None]
        assert [receipt["phase_sequence"] for receipt in children] == [0, 1, 2, 3]
        assert [receipt["phase"] for receipt in receipts if receipt["invocation_id"] == "root"] == [None, "delegate_auditors", None]
        assert children[-1]["status"] == "completed"

    asyncio.run(run())
