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


def test_known_usage_continues_after_an_unmetered_attempt_without_claiming_exact_totals():
    from server.agent_services.execution_tracking.callback.schemas import (
        InvocationReceipt,
    )
    from server.runtimes.investigation.agent import InvestigationExecution

    async def run():
        receipts = []
        runtime = InvestigationExecution.__new__(InvestigationExecution)
        runtime.usage_attempts = runtime.unknown_usage_attempts = 0
        runtime.reported_input_tokens = runtime.reported_output_tokens = 0

        async def send(receipt):
            receipts.append(InvocationReceipt.model_validate(receipt))

        async def operation():
            await runtime.record_invocation_usage(SimpleNamespace(usage_metadata={"input_tokens": 100, "output_tokens": 20}))
            await runtime.record_invocation_usage(None)  # Failed provider attempt.
            await runtime.record_invocation_usage({"raw": SimpleNamespace(usage_metadata={"input_tokens": 50, "output_tokens": 10})})
            return SimpleNamespace(status="complete")

        with invocation_reporting(send):
            await observe_invocation(operation(), agent_id="responsibility", invocation_id="child", run_id="audit")
        assert [(row.input_tokens, row.output_tokens, row.unknown_usage_attempts) for row in receipts] == [
            (None, None, 0), (100, 20, 0), (100, 20, 1), (150, 30, 1), (150, 30, 1),
        ]
        # Exact totals remain unknown; partial UI counters do not change budget accounting.
        assert runtime.usage_totals()["input_tokens"] is None
        assert runtime.usage_totals()["output_tokens"] is None

    asyncio.run(run())


def test_unmetered_runtime_does_not_hide_known_usage_from_another_source():
    class Runtime:
        def __init__(self, usage):
            self.usage = usage

        def usage_totals(self):
            return self.usage

    async def run():
        receipts = []

        async def send(receipt):
            receipts.append(receipt)

        async def operation():
            await report_invocation_usage(Runtime({
                "input_tokens": None, "output_tokens": None, "reported_input_tokens": 0,
                "reported_output_tokens": 0, "provider_attempts": 1, "unknown_usage_attempts": 1,
            }))
            await report_invocation_usage(Runtime({"input_tokens": 9, "output_tokens": 2}))
            return SimpleNamespace(status="complete")

        with invocation_reporting(send):
            await observe_invocation(operation(), agent_id="modularity", invocation_id="coord", run_id="audit")
        assert receipts[1]["input_tokens"] is None  # Unknown usage is not zero.
        assert receipts[1]["output_tokens"] is None
        assert receipts[-1]["input_tokens"] == 9
        assert receipts[-1]["output_tokens"] == 2
        assert receipts[-1]["unknown_usage_attempts"] == 1

    asyncio.run(run())
