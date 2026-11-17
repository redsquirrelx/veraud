"""Investigation runtime persists node and provider traces for the audit run.

The 2026-11-15 parallel-investigators incident (both Test* doc-driven
investigators deferring `plan_investigation` after HTTP 503 recovery) was only
diagnosable from report limitations; the per-run trace.ndjson carried no
provider or node events. These tests pin the trace events for that path.
"""

import asyncio
import json

import httpx
from test_architecture_boundary_doc_driven_investigation import verified_tools
from test_architecture_boundary_doc_driven_planning import claim, context

from server.agents.maintainability.v2.testability.test_isolation_doc_driven import (
    AuditRequest,
    TestIsolationAgent,
    TestIsolationConfig,
)
from server.infrastructure.tracing_sink import reset_trace_context, set_trace_context
from server.runtimes.invocation_reporting import observe_invocation, phase_node


class UnavailableModel:
    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages, **kwargs):
        self.calls += 1
        request = httpx.Request("POST", "https://example.test/x")
        response = httpx.Response(503, request=request)
        raise httpx.HTTPStatusError("unavailable", request=request, response=response)


def _events(tmp_path, trace_id, agent_type, execution_id):
    directory = tmp_path / "logs" / f"{trace_id}-{agent_type}-exec-{execution_id}"
    return [json.loads(line)
            for line in (directory / "trace.ndjson").read_text(encoding="utf-8").splitlines()]


def test_provider_503_emits_node_and_provider_traces(tmp_path, monkeypatch):
    monkeypatch.setenv("VERAUD_TRACE_DIR", str(tmp_path / "logs"))
    tools = verified_tools(tmp_path, {
        "app/__init__.py": "",
        "app/api.py": "from .store import Store\ndef use(): return Store()\n",
        "app/store.py": "class Store:\n    pass\n",
    })
    token = set_trace_context("trace-provider-503", 149, "test_isolation")
    try:
        model = UnavailableModel()
        documented = context(tools, [claim()])
        config = TestIsolationConfig(provider_retry_backoff_seconds=0,
                                     provider_max_retry_wait_seconds=120,
                                     provider_recovery_budget_seconds=0,
                                     max_output_tokens=1000)
        result = asyncio.run(observe_invocation(
            TestIsolationAgent(model, config).run(tools, AuditRequest(documented_architecture=documented)),
            agent_id="test_isolation", invocation_id="inv-trace-1", run_id="run-trace-1"))
    finally:
        reset_trace_context(token)

    events = _events(tmp_path, "trace-provider-503", "test_isolation", 149)
    names = [event["event"] for event in events]

    assert "node.started" in names
    assert "node.finished" in names
    assert "provider.request_started" in names
    assert "provider.error" in names
    assert "provider.defer" in names

    plan_started = next(event for event in events
                        if event["event"] == "node.started" and event["details"]["node"] == "plan_investigation")
    assert plan_started["details"]["invocationId"] == "inv-trace-1"
    assert "node-plan_investigation" in plan_started["spanId"]

    error = next(event for event in events
                 if event["event"] == "provider.error" and event["details"]["node"] == "plan_investigation")
    assert error["details"]["httpStatus"] == 503
    assert error["details"]["errorType"] == "HTTPStatusError"
    assert error["status"] == "error"

    defer = next(event for event in events if event["event"] == "provider.defer")
    assert defer["details"]["node"] == "plan_investigation"
    assert defer["details"]["reason"].startswith("provider_")

    node_finished = [event for event in events if event["event"] == "node.finished"
                     and event["details"]["node"] == "plan_investigation"]
    assert node_finished and all(event["durationMs"] is not None for event in node_finished)
    # Provider-side failure does not break the graph; the run terminates partial.
    assert result.termination_reason == defer["details"]["reason"]


def test_phase_node_emits_started_and_finished(tmp_path, monkeypatch):
    monkeypatch.setenv("VERAUD_TRACE_DIR", str(tmp_path / "logs"))

    async def run():
        token = set_trace_context("trace-node", 151, "test_isolation")
        try:
            wrapped = phase_node("plan_investigation", lambda state: state)
            return await observe_invocation(wrapped({"ok": True}, None),
                                            agent_id="test_isolation",
                                            invocation_id="inv-1",
                                            run_id="run-1")
        finally:
            reset_trace_context(token)

    asyncio.run(run())

    events = _events(tmp_path, "trace-node", "test_isolation", 151)
    by_event = {}
    for event in events:
        by_event.setdefault(event["event"], []).append(event)

    started = by_event["node.started"][0]
    finished = by_event["node.finished"][0]
    assert started["details"]["node"] == "plan_investigation"
    assert finished["details"]["node"] == "plan_investigation"
    assert started["details"]["invocationId"] == "inv-1"
    assert finished["status"] == "ok"
    assert finished["durationMs"] is not None
