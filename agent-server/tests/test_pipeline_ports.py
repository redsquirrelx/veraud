"""Phase 1: tracing and callback ports are injectable and default-safe.

The legacy pipeline and single-agent service must behave exactly as before
when constructed without arguments, while accepting custom/no-op backends.
"""

import asyncio
from types import SimpleNamespace

from server.agents.analyzer.schemas import ProjectDescription
from server.agents.architect.schemas import ArchitectureDescription
from server.api.schemas import ExecutionConfig
from server.app.callback_port import (
    BackendCallbackSink,
    NoOpCallbackSink,
    default_callback_sink,
)
from server.app.pipeline_service import (
    ArchitectureAuditService,
    PipelineExecutionIds,
    PipelineInput,
)
from server.app.tracing_port import (
    LangSmithTracingBackend,
    NoOpTracingBackend,
)
from server.infrastructure.callback.client import CallbackClient


def _analysis():
    return ProjectDescription(kind="library", summary="s", primary_language="python")


def _description():
    return ArchitectureDescription(style="layered")


class StubAgent:
    def __init__(self, result):
        self._result = result
        self.model = SimpleNamespace(settings=SimpleNamespace(name="stub"))

    async def run(self, input_data):
        return self._result


class RecorderSink:
    def __init__(self):
        self.calls = []

    async def mark_running(self, execution_id):
        self.calls.append(("running", execution_id))

    async def complete(self, execution_id, outcome):
        self.calls.append(("complete", execution_id, outcome.status))

    async def aclose(self):
        self.calls.append(("close",))


class TestTracingPorts:
    def test_noop_passes_value_through(self):
        async def main():
            return await NoOpTracingBackend().wrap_stage(_coro(7), name="s")

        async def _coro(value):
            return value

        assert asyncio.run(main()) == 7

    def test_noop_pipeline_passes_value_through(self):
        async def main():
            async def _coro():
                return {"ok": True}

            return await NoOpTracingBackend().wrap_pipeline(_coro(), name="p")

        assert asyncio.run(main()) == {"ok": True}

    def test_langsmith_without_key_is_pass_through(self):
        # No LANGSMITH_API_KEY in test env, so setup() returns None and the
        # coroutine runs untouched instead of raising.
        async def main():
            async def _coro():
                return 42

            return await LangSmithTracingBackend().wrap_stage(_coro(), name="s")

        assert asyncio.run(main()) == 42


class TestCallbackPorts:
    def test_noop_never_touches_http(self):
        async def main():
            sink = NoOpCallbackSink()
            r1 = await sink.mark_running(1)
            r2 = await sink.complete(1, SimpleNamespace(status="Completed"))
            await sink.aclose()
            return r1, r2

        r1, r2 = asyncio.run(main())
        assert r1.acknowledged is False
        assert r2.acknowledged is False

    def test_backend_sink_forwards_to_client(self):
        seen = []

        class FakeClient:
            async def mark_running(self, execution_id):
                seen.append(("running", execution_id))

            async def complete(self, execution_id, outcome):
                seen.append(("complete", execution_id, outcome.status))

            async def aclose(self):
                seen.append(("close",))

        async def main():
            sink = BackendCallbackSink(FakeClient())  # type: ignore[arg-type]
            await sink.mark_running(9)
            await sink.complete(9, SimpleNamespace(status="Completed"))
            await sink.aclose()

        asyncio.run(main())
        assert seen == [("running", 9), ("complete", 9, "Completed"), ("close",)]

    def test_default_sink_never_raises_without_explicit_config(self):
        # With or without .env, the default factory must return a usable
        # sink-or-None without raising (None = run locally, no reporting).
        sink = default_callback_sink()
        assert sink is None or isinstance(sink, BackendCallbackSink)
        assert isinstance(CallbackClient, type)


class TestPortsInjectedIntoPipeline:
    def test_pipeline_runs_with_noop_tracing_and_recorder_sink(self):
        analyzer = StubAgent(_analysis())
        architect = StubAgent(_description())
        sink = RecorderSink()
        service = ArchitectureAuditService(
            execution_service=SimpleNamespace(
                build_agent=lambda agent_type, config: (
                    (analyzer, 60) if agent_type == "analyzer" else (architect, 60)
                ),
            ),
            callbacks_factory=lambda: sink,  # type: ignore[return-value]
            tracing_backend=NoOpTracingBackend(),
        )
        result = asyncio.run(
            service.run(
                PipelineInput(root_path="/repo"),
                ExecutionConfig(),
                PipelineExecutionIds(analyzer=11, architect=12),
            )
        )
        assert result["analysis"]["kind"] == "library"
        kinds = [(c[0], c[1]) for c in sink.calls if c[0] != "close"]
        assert kinds == [("running", 11), ("complete", 11), ("running", 12), ("complete", 12)]

    def test_single_agent_service_accepts_ports(self):
        from server.app.execution_service import AgentExecutionService

        service = AgentExecutionService(
            tracing_backend=NoOpTracingBackend(),
            callbacks_factory=lambda: None,
        )
        assert service._tracing is not None
