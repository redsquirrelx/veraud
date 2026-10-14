"""Generic callback port (Phase 1).

`CallbackSink` decouples services from the backend HTTP client: services
report `mark_running`/`complete` per execution id through this port. Tests
inject a recorder, production injects `BackendCallbackSink`, and callers
without a backend get `None` (same as today: run and return, report nothing).
"""

from __future__ import annotations

from pydantic import ValidationError

from ..infrastructure.callback.client import CallbackClient
from ..infrastructure.callback.schemas import (
    CallbackConfig,
    CallbackResult,
    ExecutionOutcome,
    ExecutionProgress,
)


class CallbackSink:
    """Port for reporting lifecycle events back to the backend."""

    async def mark_running(self, execution_id: int) -> CallbackResult:
        raise NotImplementedError

    async def complete(self, execution_id: int, outcome: ExecutionOutcome) -> CallbackResult:
        raise NotImplementedError

    async def progress(self, execution_id: int, usage: ExecutionProgress) -> CallbackResult:
        raise NotImplementedError

    async def aclose(self) -> None:
        raise NotImplementedError


class BackendCallbackSink(CallbackSink):
    """Production sink: forwards to the backend over HTTP."""

    def __init__(self, client: CallbackClient) -> None:
        self._client = client

    async def mark_running(self, execution_id: int) -> CallbackResult:
        return await self._client.mark_running(execution_id)

    async def complete(self, execution_id: int, outcome: ExecutionOutcome) -> CallbackResult:
        return await self._client.complete(execution_id, outcome)

    async def progress(self, execution_id: int, usage: ExecutionProgress) -> CallbackResult:
        return await self._client.progress(execution_id, usage)

    async def aclose(self) -> None:
        await self._client.aclose()


class NoOpCallbackSink(CallbackSink):
    """Test sink: records nothing, acknowledges nothing, never touches HTTP."""

    async def mark_running(self, execution_id: int) -> CallbackResult:
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
        from ..config.settings import get_server_settings

        settings = get_server_settings()
    except ValidationError:
        return None

    return f"http://localhost:{settings.port_backend}"


def default_callback_sink() -> CallbackSink | None:
    """Production factory: a backend sink, or None when nobody can listen."""
    url = backend_url()
    if url is None:
        return None
    return BackendCallbackSink(CallbackClient(CallbackConfig(backend_url=url)))
