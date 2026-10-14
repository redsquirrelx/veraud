"""Tracing and callback ports are injectable and default-safe.

The generic pipeline and single-agent service accept custom/no-op backends
while defaulting to the production LangSmith/HTTP behavior.
"""

import asyncio
from types import SimpleNamespace

from pydantic import BaseModel

from server.api.schemas import ExecutionConfig
from server.app.callback_port import (
    BackendCallbackSink,
    NoOpCallbackSink,
    default_callback_sink,
)
from server.app.pipeline_service import (
    GenericPipelineService,
    PipelineDefinition,
)
from server.app.tracing_port import (
    LangSmithTracingBackend,
    NoOpTracingBackend,
)
from server.infrastructure.callback.client import CallbackClient


class _Output(BaseModel):
    value: str


def _result(value="done"):
    return _Output(value=value)


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
        first = StubAgent(_result("one"))
        second = StubAgent(_result("two"))
        sink = RecorderSink()

        async def _build(exec_service, config, stage_configs, parsed, timeout):
            return {"first": first, "second": second}, {}

        class _Graph:
            def __init__(self, agents, hooks):
                self._agents = agents
                self._hooks = hooks

            async def run(self):
                outputs = {}
                for stage in ("first", "second"):
                    await self._hooks.on_stage_start(stage)
                    result = await self._agents[stage].run(None)
                    await self._hooks.on_stage_result(stage, result)
                    outputs[stage] = result.model_dump()
                return outputs

        definition = PipelineDefinition(
            name="two-stage",
            stages=["first", "second"],
            parse_input=lambda raw: raw,
            build_agents=_build,
            adapt_hooks=lambda generic: generic,
            create_pipeline=lambda agents, hooks, ctx: _Graph(agents, hooks),
            run_pipeline=lambda pipeline, parsed, ctx: pipeline.run(),
        )
        service = GenericPipelineService(
            execution_service=SimpleNamespace(
                build_agent=lambda agent_type, config: (_result(), 60),
            ),
            callbacks_factory=lambda: sink,  # type: ignore[return-value]
            tracing_backend=NoOpTracingBackend(),
            registry={"two-stage": definition},
        )
        result = asyncio.run(
            service.run(
                "two-stage",
                {},
                ExecutionConfig(),
                execution_ids={"first": 11, "second": 12},
            )
        )
        assert result == {"first": {"value": "one"}, "second": {"value": "two"}}
        kinds = [(c[0], c[1]) for c in sink.calls if c[0] != "close"]
        assert kinds == [("running", 11), ("complete", 11), ("running", 12), ("complete", 12)]

    def test_single_agent_service_accepts_ports(self):
        from server.app.execution_service import AgentExecutionService

        service = AgentExecutionService(
            tracing_backend=NoOpTracingBackend(),
            callbacks_factory=lambda: None,
        )
        assert service._tracing is not None
