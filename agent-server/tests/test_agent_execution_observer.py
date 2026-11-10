"""Unified agent tracking facade, disabled capture and acknowledged delivery."""

import asyncio

from server.agent_services.execution_tracking import ExecutionObserver
from server.agent_services.execution_tracking.buffer import ExecutionEventBuffer
from server.agent_services.execution_tracking.callback.schemas import CallbackResult
from server.agent_services.execution_tracking.events import (
    execution_event_scope,
    record_event,
)
from server.agent_services.execution_tracking.observer import CallbackSink


class Sink(CallbackSink):
    def __init__(self):
        self.calls = []
        self.acknowledged = False

    async def mark_running(self, execution_id, run_id=None):
        self.calls.append(("running", execution_id, run_id))
        return CallbackResult(acknowledged=True)

    async def progress(self, execution_id, usage):
        self.calls.append(("progress", execution_id, usage))
        return CallbackResult(acknowledged=True)

    async def invocation(self, execution_id, receipt):
        self.calls.append(("invocation", execution_id, receipt))
        return CallbackResult(acknowledged=True)

    async def complete(self, execution_id, outcome):
        self.calls.append(("complete", execution_id, outcome))
        return CallbackResult(acknowledged=True)

    async def events(self, execution_id, events):
        self.calls.append(("events", execution_id, events))
        return CallbackResult(acknowledged=self.acknowledged)

    async def aclose(self):
        self.calls.append(("closed",))


def test_same_observer_captures_and_reports_without_duplicating_lifecycle():
    journal, sink = ExecutionEventBuffer(), Sink()
    observer = ExecutionObserver(sink, buffer=journal)

    async def run():
        with observer.scope(7):
            await observer.mark_running(7, "audit")
            await observer.progress(7, "usage")
            await observer.invocation(7, "receipt")
            record_event("phase.changed", name="plan_assessment")
            await observer.complete(7, "outcome")
        pending = journal.pending()
        assert not await observer.flush()
        assert journal.pending() == pending
        sink.acknowledged = True
        assert await observer.flush()
        assert not journal.pending()
        await observer.aclose()

    asyncio.run(run())
    assert [row[0] for row in sink.calls] == ["running", "progress", "invocation", "complete", "events", "events", "closed"]
    assert sink.calls[4] == sink.calls[5]
    assert [event["kind"] for event in sink.calls[4][2]] == ["execution.started", "phase.changed", "execution.finished"]


def test_disabled_observer_suppresses_inherited_capture_without_losing_parent():
    journal = ExecutionEventBuffer()
    observer = ExecutionObserver(buffer=journal)
    with execution_event_scope(7, buffer=journal):
        with observer.scope(7):
            assert record_event("phase.changed", name="disabled") is None
        record_event("phase.changed", name="parent")
    assert [event["name"] for _, _, event in journal.pending() if event["kind"] == "phase.changed"] == ["parent"]
    assert not asyncio.run(observer.flush())
    assert not asyncio.run(observer.mark_running(7)).acknowledged


def test_legacy_paths_are_same_modules_not_duplicate_services():
    from server.agent_services.execution_tracking import buffer, events, observer
    from server.agent_services.execution_tracking.callback import client, schemas
    from server.app import callback_port
    from server.infrastructure import execution_event_buffer, execution_events
    from server.infrastructure.callback import client as legacy_client
    from server.infrastructure.callback import schemas as legacy_schemas

    assert (callback_port, execution_events, execution_event_buffer, legacy_client, legacy_schemas) == (observer, events, buffer, client, schemas)
