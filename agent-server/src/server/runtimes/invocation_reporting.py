"""Task-local invocation lifecycle reporting, independent of agents and transport."""

import asyncio
import inspect
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

from langchain_core.runnables import Runnable, RunnableConfig

from ..config.logs import get_logger
from .cancellation import check_cancellation

logger = get_logger("invocation-reporting")
_reporter = ContextVar("invocation_reporter", default=None)
_active = ContextVar("active_invocation", default=None)


@contextmanager
def invocation_reporting(reporter):
    """Background tasks inherit their pipeline's sink, never another audit's."""
    token = _reporter.set(reporter)
    try:
        yield
    finally:
        _reporter.reset(token)


async def _send(receipt):
    try:
        await _reporter.get()(dict(receipt))
    except Exception as error:  # noqa: BLE001 - telemetry must not fail agent work
        logger.warning("Invocation callback failed (%s)", type(error).__name__)


async def report_invocation_usage(runtime):
    active = _active.get()
    if active is None:
        return
    receipt, sources = active
    sources[runtime] = runtime.usage_totals()
    for key in ("input_tokens", "output_tokens"):
        counts = [usage.get(key) for usage in sources.values()]
        receipt[key] = sum(counts) if all(isinstance(value, int) for value in counts) else None
    await _send(receipt)


async def report_invocation_phase(phase):
    active = _active.get()
    if active is None:
        return
    receipt, _ = active
    if receipt["phase"] == phase:
        return
    receipt["phase"] = phase
    receipt["phase_sequence"] += 1
    await _send(receipt)


def phase_node(name, operation):
    """Observe an existing graph node without changing its outputs or routes."""
    async def node(state, config: RunnableConfig):
        check_cancellation()
        await report_invocation_phase(name)
        check_cancellation()
        if isinstance(operation, Runnable):
            return await operation.ainvoke(state, config)
        result = operation(state)
        return await result if inspect.isawaitable(result) else result
    return node


async def observe_invocation(operation, *, agent_id, invocation_id, run_id):
    """Wrap actual execution, preserving results, exceptions and cancellation."""
    try:
        check_cancellation()
    except asyncio.CancelledError:
        if inspect.iscoroutine(operation):
            operation.close()
        raise
    if _reporter.get() is None:
        return await operation
    parent = _active.get()
    receipt = {"agent_id": agent_id, "invocation_id": invocation_id, "run_id": run_id,
        "parent_invocation_id": parent[0]["invocation_id"] if parent else None,
        "status": "running", "started_at": datetime.now(UTC).isoformat(), "finished_at": None,
        "input_tokens": None, "output_tokens": None, "error": None, "phase": None, "phase_sequence": 0}
    token = _active.set((receipt, {}))
    began = False
    try:
        await _send(receipt)
        check_cancellation()
        began = True
        result = await operation
        status = getattr(result, "status", None)
        receipt["status"] = "completed" if status in {"complete", "completed"} else (
            status if status in {"partial", "failed", "cancelled", "timeout"} else "partial")
        return result
    except BaseException as error:
        if not began and hasattr(operation, "close"):
            operation.close()
        receipt["status"] = "cancelled" if isinstance(error, asyncio.CancelledError) else (
            "timeout" if isinstance(error, TimeoutError) else "failed")
        receipt["error"] = type(error).__name__
        raise
    finally:
        receipt["finished_at"] = datetime.now(UTC).isoformat()
        receipt["phase"] = None
        receipt["phase_sequence"] += 1
        try:
            await _send(receipt)
        finally:
            _active.reset(token)
