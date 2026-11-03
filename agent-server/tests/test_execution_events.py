"""Offline coverage of volatile delivery, task isolation and instrumentation."""

import asyncio
import json
from types import SimpleNamespace
from typing import TypedDict
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph

from server.infrastructure.callback.schemas import CallbackResult
from server.infrastructure.execution_event_buffer import (
    ExecutionEventBuffer,
    deliver_execution_events,
)
from server.infrastructure.execution_events import (
    ObservedComponent,
    action_event,
    capture_event_recorder,
    execution_event_scope,
    record_event,
)
from server.runtimes.invocation_reporting import (
    observe_invocation,
    phase_node,
    report_invocation_phase,
)
from server.runtimes.repository.model_runtime import ModelGateway


def payloads(journal):
    return [event for _, _, event in journal.pending()]


def test_graph_nodes_native_model_tools_and_repeated_phases_have_correlated_events(tmp_path):
    journal = ExecutionEventBuffer()
    secret = "sk-fake-private-password-Bearer"

    class State(TypedDict):
        count: int

    model = FakeListChatModel(responses=[secret])
    tool = StructuredTool.from_function(lambda value: value, name="inspect_source", description="Offline fixture")

    async def step(state):
        await model.ainvoke(secret)
        await tool.ainvoke({"value": secret})
        return {"count": state["count"] + 1}

    graph = StateGraph(State)
    graph.add_node("investigate", phase_node("investigate", step))
    graph.add_edge(START, "investigate")
    graph.add_conditional_edges("investigate", lambda state: "investigate" if state["count"] < 2 else END)
    compiled = graph.compile()

    async def run():
        with execution_event_scope(11, buffer=journal):
            async def investigate():
                await compiled.ainvoke({"count": 0})
                return SimpleNamespace(status="completed")
            await observe_invocation(investigate(), agent_id="investigator", invocation_id="child", run_id="audit")

    asyncio.run(run())
    events = payloads(journal)
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    assert all(event["occurredAt"] for event in events)
    assert secret not in json.dumps(events)
    assert len([event for event in events if event["kind"] == "model.started"]) == 2
    assert len([event for event in events if event["kind"] == "tool.started"]) == 2
    assert len([event for event in events if event["kind"] == "phase.changed"]) == 2
    nodes = [event for event in events if event["kind"] == "node.started" and event["name"] == "investigate"]
    assert len(nodes) >= 2
    assert all(event["invocationId"] == "child" for event in nodes)
    for event in events:
        if event["kind"].endswith(".started"):
            assert any(other["actionId"] == event["actionId"] and other["kind"] == event["kind"].replace(".started", ".finished") for other in events)


def test_nested_invocations_and_concurrent_audits_do_not_mix_identities(tmp_path):
    journal = ExecutionEventBuffer()

    async def audit(target):
        async def child():
            await asyncio.to_thread(record_event, "phase.changed", name="thread_work")
            await asyncio.sleep(0)
            return SimpleNamespace(status="completed")

        async def root():
            await observe_invocation(child(), agent_id="child", invocation_id=f"child-{target}", run_id=f"audit-{target}")
            return SimpleNamespace(status="completed")

        with execution_event_scope(target, buffer=journal):
            await observe_invocation(root(), agent_id="manager", invocation_id=f"root-{target}", run_id=f"audit-{target}")

    async def run():
        await asyncio.gather(audit(1), audit(2))
    asyncio.run(run())
    for _, target, event in journal.pending():
        if event["invocationId"]:
            assert event["invocationId"].endswith(str(target))
        if event["agentId"] == "child":
            assert event["parentInvocationId"] == f"root-{target}"


def test_cancelled_and_failed_actions_close_without_exception_text(tmp_path):
    journal = ExecutionEventBuffer()
    for exception, status in [(RuntimeError("password=private"), "failed"), (asyncio.CancelledError(), "cancelled")]:
        with pytest.raises(type(exception)), execution_event_scope(1, buffer=journal), action_event("tool", name="inspect"):
            raise exception
        assert payloads(journal)[-2]["status"] == status
    assert "private" not in json.dumps(payloads(journal))


def test_ambiguous_delivery_retries_identical_events_only_during_process_lifetime(tmp_path):
    journal = ExecutionEventBuffer()
    with execution_event_scope(17, buffer=journal):
        record_event("phase.changed", name="investigate", metadata={"input_tokens": 4, "password": "private"})
    before = payloads(journal)

    class Sink:
        def __init__(self):
            self.calls = []
            self.acknowledged = False

        async def events(self, execution_id, events):
            self.calls.append((execution_id, events))
            return CallbackResult(acknowledged=self.acknowledged)

    sink = Sink()
    assert not asyncio.run(deliver_execution_events(journal, sink))
    assert payloads(ExecutionEventBuffer()) == []  # A restarted process has no local history.
    assert payloads(journal) == before
    sink.acknowledged = True
    assert asyncio.run(deliver_execution_events(journal, sink))
    assert sink.calls[0] == sink.calls[1]
    assert journal.pending() == []
    assert "password" not in json.dumps(before)


def test_gateway_records_each_provider_attempt_and_retry_without_payloads(tmp_path):
    journal = ExecutionEventBuffer()

    # A retryable transport error, not a hard timeout (the gateway does not retry those).
    import httpx
    calls = 0

    async def generate(prompt):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("Bearer private")
        return "private-response"

    gateway = ModelGateway(SimpleNamespace(generate=generate), interval=0, backoff=0, max_retries=1)

    async def run():
        with execution_event_scope(1, buffer=journal):
            await gateway("private-prompt")
    asyncio.run(run())
    events = payloads(journal)
    assert len([event for event in events if event["kind"] == "provider.request"]) == 2
    assert len([event for event in events if event["kind"] == "provider.retry"]) == 1
    assert "private" not in json.dumps(events)


def test_buffer_sequences_are_atomic_across_threads(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    journal = ExecutionEventBuffer()
    stream = str(uuid4())
    with ThreadPoolExecutor(max_workers=4) as pool:
        events = list(pool.map(lambda _: journal.append(1, stream, kind="phase.changed", action_id=str(uuid4())), range(40)))
    assert sorted(event.sequence for event in events) == list(range(1, 41))


def test_repeated_identical_phase_entries_are_not_lost(tmp_path):
    journal = ExecutionEventBuffer()

    async def operation():
        await report_invocation_phase("security_scan")
        await report_invocation_phase("security_scan")
        return SimpleNamespace(status="completed")

    async def run():
        with execution_event_scope(1, buffer=journal):
            await observe_invocation(operation(), agent_id="security", invocation_id="scan", run_id="audit")
    asyncio.run(run())
    assert len([event for event in payloads(journal) if event["kind"] == "phase.changed"]) == 2


def test_legacy_components_and_external_lifecycle_callbacks_keep_audit_correlation(tmp_path):
    journal = ExecutionEventBuffer()

    class Scanner:
        api_key = None

        def scan_path(self, path):
            assert self.api_key == "private-key"
            return [path]

    scanner = ObservedComponent(Scanner(), "sast_scanner")
    scanner.api_key = "private-key"

    async def root():
        assert scanner.scan_path("private-source") == ["private-source"]
        return SimpleNamespace(status="completed")

    async def run():
        with execution_event_scope(42, buffer=journal):
            recorder = capture_event_recorder({"run_id": "audit", "invocation_id": "root", "agent_id": "security"})
            await observe_invocation(root(), agent_id="security", invocation_id="root", run_id="audit")
        # Simulate an external cancellation request after the task's context was left.
        recorder("audit.state_changed", status="cancelling")

    asyncio.run(run())
    events = payloads(journal)
    child = next(event for event in events if event["kind"] == "invocation.started" and event["agentId"] == "sast_scanner")
    assert child["parentInvocationId"] == "root"
    assert events[-1]["runId"] == "audit" and events[-1]["status"] == "cancelling"
    assert "private" not in json.dumps(events)


def test_synchronous_work_cannot_turn_an_expired_deadline_into_success():
    from server.runtimes.repository.timing import ActiveDeadline, within_deadline

    clock = [0.0]
    deadline = ActiveDeadline(1, clock=lambda: clock[0])

    async def finish_after_expiry():
        clock[0] = 2.0  # A synchronous operation prevents the deadline timer from waking.
        return "late success"

    with pytest.raises(TimeoutError):
        asyncio.run(within_deadline(finish_after_expiry(), deadline))


def test_direct_blackboard_publications_are_recorded_once_without_record_content(tmp_path):
    from server.blackboard.impls.memory import MemoryBlackboard
    from server.blackboard.models import Assessment

    journal = ExecutionEventBuffer()
    board = MemoryBlackboard()
    assessment = Assessment(id="assessment", agent_id="security", run_id="audit", invocation_id="scanner",
        repository_id="repository", snapshot_hash="snapshot", objective="private-source", status="complete", termination_reason="complete")
    with execution_event_scope(1, buffer=journal):
        board.publish_assessment(assessment)
        board.publish_assessment(assessment)
    events = [event for event in payloads(journal) if event["kind"] == "publication.created"]
    assert len(events) == 1
    assert events[0]["actionId"] == "assessment" and events[0]["invocationId"] == "scanner"
    assert "private-source" not in json.dumps(events)


def test_delivery_buffer_is_bounded_and_never_writes_files(tmp_path, monkeypatch):
    from pathlib import Path

    def forbidden(*args, **kwargs):
        raise AssertionError("Event delivery must not access the filesystem")

    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr("sqlite3.connect", forbidden)
    buffer = ExecutionEventBuffer(max_pending=1)
    stream = str(uuid4())
    buffer.append(1, stream, kind="phase.changed", action_id="first")
    with pytest.raises(BufferError):
        buffer.append(1, stream, kind="phase.changed", action_id="second")
    assert len(buffer.pending()) == 1
    assert list(tmp_path.iterdir()) == []


def test_unassociated_runs_are_not_retained():
    buffer = ExecutionEventBuffer()
    with execution_event_scope(buffer=buffer):
        record_event("phase.changed", name="standalone")
    assert buffer.pending() == []
