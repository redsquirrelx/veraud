import json

from server.infrastructure.tracing_sink import (
    reset_trace_context,
    set_trace_context,
    trace_event,
)


def test_trace_sink_persists_execution_events_without_interrupting_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("VERAUD_TRACE_DIR", str(tmp_path / "logs"))
    token = set_trace_context("trace-123", 129, "architecture_context")
    try:
        trace_event("provider.error", status="error", error_code="http_429", message="Provider failed", details={"apiKey": "secret"})
    finally:
        reset_trace_context(token)

    directory = next((tmp_path / "logs").iterdir())
    event = json.loads((directory / "trace.ndjson").read_text(encoding="utf-8").splitlines()[0])
    assert event["traceId"] == "trace-123"
    assert event["executionId"] == 129
    assert event["details"]["apiKey"] == "[redacted]"
    assert "secret" not in (directory / "agent-server.log").read_text(encoding="utf-8")
