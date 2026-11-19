"""Shared observability for this agent, across the two existing channels.

`trace_event` writes best-effort NDJSON/text traces with content-free
details (fail-soft; only emitted inside an HTTP trace context). `record_event`
reports the same decision to the backend's execution event stream, subject to
the shared contract's closed vocabulary: the wire `kind` must be a contract
kind ("phase.changed"), the full dotted name travels in `name`, and `status`
belongs to the contract enum. Only lossless scalars cross the boundary:
identifiers, line ranges, counters and stable reason codes — never quotes,
document text or prompts.
"""

from server.agent_services.execution_tracking.events import record_event
from server.infrastructure.tracing_sink import trace_event

# Wire-contract vocabulary for the callback channel.
_STATUS = {"ok": "completed", "warning": "partial", "running": "running",
           "completed": "completed", "partial": "partial", "rejected": "rejected",
           "failed": "failed", "error": "failed"}

_REASON_CODES = (
    ("Evidence contains only a heading without supporting content", "heading_only"),
    ("Evidence line range is outside its original section", "invalid_line_range"),
    ("Evidence line range reconstructed empty text", "empty_quote"),
    ("Claim evidence and section IDs must agree", "ids_mismatch"),
    ("Claim evidence references a section outside its batch", "outside_batch"),
    ("Claim evidence references an unavailable or invalid section", "invalid_section_ref"),
    ("section IDs must be unique", "duplicate_section_ids"),
    ("Claim section IDs must be unique and reference valid sections", "invalid_section_ids"),
    ("Issue section IDs must be unique", "invalid_issue_ids"),
    ("Issue document reference does not exist", "issue_document_mismatch"),
    ("Issue references an unavailable or invalid section", "issue_section_unavailable"),
    ("Evidence quote does not match", "non_literal_quote"),
)


def _reason_code(message: str) -> str:
    for needle, slug in _REASON_CODES:
        if needle in message:
            return slug
    return "invalid_evidence"


def architecture_context_event(kind, *, status="running", message=None, error_code=None, details=None):
    safe_details = {
        key: value
        for key, value in (details or {}).items()
        if isinstance(value, (str, int, float, bool)) or value is None
    }
    if error_code is not None:
        safe_details = {"error_code": error_code, **safe_details}
    trace_event(kind, status=status, message=message, error_code=error_code, details=safe_details)
    wire_status = _STATUS.get(status, "partial")
    # Only the dotted name, a contract kind and a contract status fit the wire;
    # rich details stay in the trace channel.
    record_event("phase.changed", name=kind, status=wire_status)


def reason_slug(message):
    return _reason_code(str(message))
