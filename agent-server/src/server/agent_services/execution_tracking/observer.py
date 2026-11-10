"""Agent-facing execution observer and its injectable backend delivery port.

Lifecycle notifications and content-free activity share one service, while
capture, buffering and HTTP transport retain separate internal responsibilities.
"""

from __future__ import annotations

from pydantic import ValidationError

from .callback.client import CallbackClient
from .callback.schemas import (
    CallbackConfig,
    CallbackResult,
    ExecutionOutcome,
    ExecutionProgress,
    InvocationReceipt,
)


class CallbackSink:
    """Port for reporting lifecycle events back to the backend."""

    async def mark_running(self, execution_id: int, run_id: str | None = None) -> CallbackResult:
        raise NotImplementedError

    async def complete(self, execution_id: int, outcome: ExecutionOutcome) -> CallbackResult:
        raise NotImplementedError

    async def progress(self, execution_id: int, usage: ExecutionProgress) -> CallbackResult:
        raise NotImplementedError

    async def aclose(self) -> None:
        raise NotImplementedError

    async def invocation(self, execution_id: int, receipt: InvocationReceipt) -> CallbackResult:
        return CallbackResult(acknowledged=False, error="invocation reporting unavailable")

    async def events(self, execution_id: int, events: list[dict]) -> CallbackResult:
        return CallbackResult(acknowledged=False, error="event reporting unavailable")


class BackendCallbackSink(CallbackSink):
    """Production sink: forwards to the backend over HTTP."""

    def __init__(self, client: CallbackClient) -> None:
        self._client = client

    async def mark_running(self, execution_id: int, run_id: str | None = None) -> CallbackResult:
        return await self._client.mark_running(execution_id, run_id) if run_id else await self._client.mark_running(execution_id)

    async def complete(self, execution_id: int, outcome: ExecutionOutcome) -> CallbackResult:
        return await self._client.complete(execution_id, outcome)

    async def progress(self, execution_id: int, usage: ExecutionProgress) -> CallbackResult:
        return await self._client.progress(execution_id, usage)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def invocation(self, execution_id: int, receipt: InvocationReceipt) -> CallbackResult:
        return await self._client.invocation(execution_id, receipt)

    async def events(self, execution_id: int, events: list[dict]) -> CallbackResult:
        return await self._client.events(execution_id, events)


class NoOpCallbackSink(CallbackSink):
    """Test sink: records nothing, acknowledges nothing, never touches HTTP."""

    async def mark_running(self, execution_id: int, run_id: str | None = None) -> CallbackResult:
        return CallbackResult(acknowledged=False, error="noop sink")

    async def complete(self, execution_id: int, outcome: ExecutionOutcome) -> CallbackResult:
        return CallbackResult(acknowledged=False, error="noop sink")

    async def progress(self, execution_id: int, usage: ExecutionProgress) -> CallbackResult:
        return CallbackResult(acknowledged=False, error="noop sink")

    async def aclose(self) -> None:
        return None


def backend_url() -> str | None:
    """Where to report progress, from PORT_BACKEND, or None if unavailable.

    Lives here (not in execution_service) so both services share it without
    a circular import. Imported lazily for the same reason the old helper was:
    everything must still import when there is no .env.
    """
    try:
        from server.config.settings import get_server_settings

        settings = get_server_settings()
    except ValidationError:
        return None

    return f"http://localhost:{settings.port_backend}"


def default_callback_sink() -> CallbackSink | None:
    """Production factory: a backend sink, or None when nobody can listen."""
    url = backend_url()
    if url is None:
        return None
    return ExecutionObserver(BackendCallbackSink(CallbackClient(CallbackConfig(backend_url=url))))


class ExecutionObserver(CallbackSink):
    """Unified lifecycle reporting and activity capture for agent executions.

    Without a sink, capture and delivery are disabled. Budgets are independent.
    """

    def __init__(self, sink: CallbackSink | None = None, *, buffer=None):
        self.sink = sink
        self.buffer = buffer

    def scope(self, execution_id=None):
        from .events import execution_event_scope

        return execution_event_scope(execution_id, buffer=self.buffer, enabled=self.sink is not None)

    async def mark_running(self, execution_id, run_id=None):
        if self.sink is None:
            return CallbackResult(acknowledged=False, error="tracking disabled")
        return await self.sink.mark_running(execution_id, run_id) if run_id else await self.sink.mark_running(execution_id)

    async def complete(self, execution_id, outcome):
        if self.sink is None:
            return CallbackResult(acknowledged=False, error="tracking disabled")
        return await self.sink.complete(execution_id, outcome)

    async def progress(self, execution_id, usage):
        if self.sink is None:
            return CallbackResult(acknowledged=False, error="tracking disabled")
        return await self.sink.progress(execution_id, usage)

    async def invocation(self, execution_id, receipt):
        if self.sink is None:
            return CallbackResult(acknowledged=False, error="tracking disabled")
        return await self.sink.invocation(execution_id, receipt)

    async def events(self, execution_id, events):
        if self.sink is None:
            return CallbackResult(acknowledged=False, error="tracking disabled")
        return await self.sink.events(execution_id, events)

    async def flush(self):
        from .buffer import deliver_execution_events, execution_event_buffer

        if self.sink is None:
            return False
        return await deliver_execution_events(self.buffer if self.buffer is not None else execution_event_buffer(), self)

    async def aclose(self):
        if self.sink is not None:
            await self.sink.aclose()
