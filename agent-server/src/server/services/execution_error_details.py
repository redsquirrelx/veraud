"""Capture incidents, not provider payloads; retain a child's original attribution."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

from server.contracts.execution_error import ExecutionErrorDetail
from server.services.execution_failures import ExecutionFailure, failure_from_exception

_incidents = ContextVar("execution_error_details", default=None)


@contextmanager
def capture_execution_errors():
    incidents = []
    token = _incidents.set(incidents)
    try:
        yield incidents
    finally:
        _incidents.reset(token)
        parent = _incidents.get()
        if parent is not None and incidents:
            parent.append(incidents[0])


def record_error(detail):
    incidents = _incidents.get()
    if incidents is not None and detail is not None:
        incidents.append(detail)
    return detail


def exception_error_detail(error, *, agent_id=None, invocation_id=None, stage="execute"):
    # The same exception may cross several wrappers: its first observation wins.
    cause = error
    seen = set()
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        existing = getattr(cause, "_execution_error_detail", None)
        if isinstance(existing, ExecutionErrorDetail):
            return record_error(existing)
        cause = cause.__cause__ or cause.__context__
    failure = failure_from_exception(error, stage)
    detail = ExecutionErrorDetail(agent_id=agent_id, invocation_id=invocation_id,
        occurred_at=datetime.now(UTC), code=failure.code, exception_type=failure.exception_type,
        message=failure.summary[:2000])
    try:
        error._execution_error_detail = detail
    except (AttributeError, TypeError):
        pass  # Unusual immutable exceptions must not replace the original failure.
    return record_error(detail)


def result_error_detail(result, *, agent_id=None, invocation_id=None, children=()):
    status = getattr(result, "status", None)
    if status not in {"failed", "timeout", "partial"}:
        return None
    # A parent must not re-date or take ownership of a child's incident.
    if children:
        return record_error(children[0])
    if status == "partial":
        return None  # Incomplete coverage alone is not an execution error.
    failure = getattr(result, "failure", None)
    if not isinstance(failure, ExecutionFailure):
        failure = ExecutionFailure(code="execution_timeout" if status == "timeout" else "execution_failed",
            stage="execute", summary="Se agotó el tiempo de ejecución." if status == "timeout"
            else "La ejecución terminó en estado fallido sin un detalle seguro adicional.")
    return record_error(ExecutionErrorDetail(agent_id=agent_id, invocation_id=invocation_id,
        occurred_at=datetime.now(UTC), code=failure.code, exception_type=failure.exception_type,
        message=failure.summary[:2000]))
