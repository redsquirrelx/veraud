"""Best-effort cross-process execution traces.

The sink is intentionally optional and fail-soft: tracing must never block a
payload that changes business state. Events are newline-delimited JSON so one
line is a complete record and concurrent producers can append atomically.
"""

from __future__ import annotations

import contextvars
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from random import choices
from string import hexdigits
from threading import Lock

from ..config.settings import resolve_workspace_root

_TRACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SECRET_RE = re.compile(r"(?:api[-_]?key|credential|password|secret|authorization|token)", re.IGNORECASE)
_CONTEXT: contextvars.ContextVar[dict | None] = contextvars.ContextVar("veraud-trace-context", default=None)
_LOCK = Lock()
_COUNTERS: dict[str, int] = {}


def set_trace_context(trace_id: str | None, execution_id: int | None = None, agent_type: str | None = None):
    if not trace_id or _TRACE_RE.fullmatch(trace_id) is None:
        _CONTEXT.set(None)
        return _CONTEXT.set(None)
    previous = _CONTEXT.get()
    context = {
        "traceId": trace_id,
        "executionId": execution_id,
        "agentType": agent_type or "architecture_context",
        "spanId": previous.get("spanId") if previous else trace_id,
    }
    return _CONTEXT.set(context)


def reset_trace_context(token):
    _CONTEXT.reset(token)


def current_trace_context():
    return _CONTEXT.get()


def _stamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "-", value)[:128]


def _root() -> Path:
    configured = os.environ.get("VERAUD_TRACE_DIR")
    return Path(configured) if configured else resolve_workspace_root() / "logs"


def _redact(value):
    if isinstance(value, str):
        return value if len(value) <= 16_384 else f"{value[:16_384]}<truncated>"
    if isinstance(value, list):
        return [_redact(item) for item in value[:100]]
    if isinstance(value, dict):
        return {str(key): "[redacted]" if _SECRET_RE.search(str(key)) else _redact(item) for key, item in list(value.items())[:100]}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _event_line(event: str, *, status="running", message=None, error_code=None, duration_ms=None, details=None, span_id=None, parent_span_id=None):
    context = current_trace_context()
    if not context or os.environ.get("VERAUD_TRACE_ENABLED") == "0":
        return None
    seq = _COUNTERS.get(context["traceId"], 0) + 1
    _COUNTERS[context["traceId"]] = seq
    return {
        "version": 1,
        "at": _stamp(),
        "sequence": seq,
        "traceId": context["traceId"],
        "executionId": context.get("executionId"),
        "agentType": context.get("agentType"),
        "service": "agent-server",
        "spanId": span_id or context.get("spanId") or context["traceId"],
        "parentSpanId": parent_span_id,
        "event": event,
        "status": status,
        "message": message,
        "errorCode": error_code,
        "durationMs": duration_ms,
        "details": _redact(details or {}),
    }


def trace_event(event: str, *, status="running", message=None, error_code=None, duration_ms=None, details=None, span_id=None, parent_span_id=None):
    payload = _event_line(event, status=status, message=message, error_code=error_code,
                          duration_ms=duration_ms, details=details, span_id=span_id, parent_span_id=parent_span_id)
    if payload is None:
        return
    context = current_trace_context()
    target = _root() / f"{_safe(context['traceId'])}-{_safe(context.get('agentType', 'agent'))}-exec-{context.get('executionId') or 'direct'}"
    try:
        target.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            with (target / "trace.ndjson").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
                stream.flush()
            with (target / "agent-server.log").open("a", encoding="utf-8") as stream:
                stream.write(f"{_stamp()} {status.upper()} {event}{' — ' + str(message) if message else ''}\n")
                stream.flush()
    except OSError:
        # Telemetry is deliberately fail-soft.
        return


def child_span_id(name: str) -> str:
    suffix = "".join(choices(hexdigits.lower(), k=6))
    return f"{_safe(current_trace_context().get('spanId') if current_trace_context() else 'root')}-{_safe(name)}-{suffix}"[:128]
