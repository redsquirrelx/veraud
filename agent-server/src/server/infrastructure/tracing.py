"""Generic tracing port (Phase 1).

`TracingBackend` decouples pipeline/agent services from LangSmith: services
wrap stage and pipeline coroutines through this port instead of calling
`config.tracing.traced_agent_run` directly. A custom backend only needs to
implement this protocol; no service or graph code changes.
"""

from collections.abc import Awaitable
from typing import Any, TypeVar

T = TypeVar("T")


class TracingBackend:
    """Port for tracing agent/pipeline runs.

    Both methods must await the given coroutine exactly once and return its
    result, whether tracing is on or off. The default LangSmith backend
    delegates to `config.tracing.traced_agent_run`, which is already a
    pass-through without a key.
    """

    async def wrap_stage(self, coro: Awaitable[T], *, name: str, **metadata: Any) -> T:
        raise NotImplementedError

    async def wrap_pipeline(self, coro: Awaitable[T], *, name: str, **metadata: Any) -> T:
        raise NotImplementedError


class LangSmithTracingBackend(TracingBackend):
    """Production backend: one span per stage plus one parent pipeline span."""

    async def wrap_stage(self, coro: Awaitable[T], *, name: str, **metadata: Any) -> T:
        from server.config.tracing import traced_agent_run

        return await traced_agent_run(coro, name=name, **metadata)

    async def wrap_pipeline(self, coro: Awaitable[T], *, name: str, **metadata: Any) -> T:
        from server.config.tracing import traced_agent_run

        return await traced_agent_run(coro, name=name, **metadata)


class NoOpTracingBackend(TracingBackend):
    """Test/CLI backend: no spans, the coroutine runs untouched."""

    async def wrap_stage(self, coro: Awaitable[T], *, name: str, **metadata: Any) -> T:
        return await coro

    async def wrap_pipeline(self, coro: Awaitable[T], *, name: str, **metadata: Any) -> T:
        return await coro
