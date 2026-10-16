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
)
from server.app.pipeline_service import (
    GenericPipelineService,
    PipelineDefinition,
)
from server.app.tracing_port import NoOpTracingBackend
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


class TestCallbackPorts:
    def test_noop_never_touches_http(self, monkeypatch):
        import httpx

        http_attempts = []

        def unexpected_http(*args, **kwargs):
            http_attempts.append(True)
            raise AssertionError("No-op callbacks must not create an HTTP client")

        monkeypatch.setattr(httpx.AsyncClient, "__init__", unexpected_http)
        monkeypatch.setattr(httpx.Client, "__init__", unexpected_http)
        monkeypatch.setattr(httpx.AsyncClient, "send", unexpected_http)
        monkeypatch.setattr(httpx.Client, "send", unexpected_http)
        monkeypatch.setattr(CallbackClient, "__init__", unexpected_http)

        async def main():
            sink = NoOpCallbackSink()
            r1 = await sink.mark_running(1)
            r2 = await sink.complete(1, SimpleNamespace(status="Completed"))
            r3 = await sink.progress(1, SimpleNamespace(input_tokens=10))
            await sink.aclose()
            return r1, r2, r3

        r1, r2, r3 = asyncio.run(main())
        assert r1.acknowledged is False
        assert r2.acknowledged is False
        assert r3.acknowledged is False
        assert not http_attempts

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
