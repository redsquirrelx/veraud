"""End-to-end trace middleware integration: x-veraud-* request headers must be honored
across a real FastAPI request cycle — the response echoes the header and the NDJSON
on disk records the request lifecycle with status-aware fields."""
import json
import re

import pytest
from fastapi.testclient import TestClient

from server.main import app

HEADERS = {"x-veraud-trace-id": "a" * 32, "x-veraud-execution-id": "129", "x-veraud-agent-type": "architecture_context"}


@pytest.fixture
def traced(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    monkeypatch.setenv("VERAUD_TRACE_DIR", str(logs))
    return logs


def _read_envelopes(logs):
    directories = [entry for entry in logs.iterdir() if entry.is_dir()]
    assert len(directories) == 1
    return [json.loads(line) for line in (directories[0] / "trace.ndjson").read_text(encoding="utf-8").splitlines() if line.strip()]


def test_middleware_traces_a_successful_request(traced):
    with TestClient(app) as client:
        response = client.get("/api/agents", headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["x-veraud-trace-id"] == "a" * 32
    envelopes = _read_envelopes(traced)
    by_event = {envelope["event"]: envelope for envelope in envelopes}
    started = by_event["http.request.started"]
    completed = by_event["http.request.completed"]
    assert started["traceId"] == "a" * 32 and started["executionId"] == 129
    assert completed["status"] == "ok"
    assert completed["details"]["httpStatus"] == 200
    assert completed.get("errorCode") is None
    assert completed["agentType"] == "architecture_context"
    assert completed["service"] == "agent-server"
    assert re.match(r"^\d{4}-\d{2}-\d{2}T", completed["at"])
    for envelope in envelopes:
        assert envelope["traceId"] == "a" * 32


def test_middleware_marks_4xx_as_error_with_status_code(traced):
    with TestClient(app) as client:
        response = client.get("/api/agents/missing/schema", headers=HEADERS)
    assert response.status_code == 404
    envelopes = _read_envelopes(traced)
    completed = next(envelope for envelope in envelopes if envelope["event"] == "http.request.completed")
    assert completed["status"] == "error"
    assert completed["errorCode"] == "http_404"
    assert completed["details"]["httpStatus"] == 404


def test_requests_without_trace_headers_leave_no_trace_files(traced):
    with TestClient(app) as client:
        response = client.get("/api/agents")
    assert response.status_code == 200
    assert not traced.exists() or list(traced.iterdir()) == []
