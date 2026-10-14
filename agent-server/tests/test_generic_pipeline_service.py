"""Generic pipeline service runs registered pipelines by name.

Covers reporting order, skip-on-failure, timeout fail-open, no-report
without execution ids, plus registry listing, unknown-pipeline errors, and
the generic HTTP endpoints. Uses a fake two-stage definition so no real
agents are involved.
"""

import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pydantic import BaseModel

from server.api.schemas import ExecutionConfig
from server.app.execution_service import InvalidConfigError
from server.app.pipeline_service import (
    GenericPipelineService,
    PipelineDefinition,
    UnknownPipelineError,
    get_generic_pipeline_service,
)
from server.app.tracing_port import NoOpTracingBackend
from server.main import app


class _Output(BaseModel):
    kind: str = "library"
    style: str = "layered"


class StubAgent:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error
        self.model = SimpleNamespace(settings=SimpleNamespace(name="stub"))
        self.seen = []

    async def run(self, input_data):
        self.seen.append(input_data)
        if self._error is not None:
            raise self._error
        return self._result


class RecorderSink:
    def __init__(self):
        self.calls = []

    async def mark_running(self, execution_id):
        self.calls.append(("running", execution_id))

    async def complete(self, execution_id, outcome):
        self.calls.append(("complete", execution_id, outcome.status, outcome.error))

    async def aclose(self):
        self.calls.append(("close",))


class _Graph:
    """Two nodes in order, mirroring the old audit orchestration."""

    def __init__(self, agents, hooks):
        self._agents = agents
        self._hooks = hooks

    async def run(self):
        first = await self._run_stage("first")
        second_input = {"kind": first.kind}
        second = await self._run_stage("second", second_input)
        return {"first": first.model_dump(), "second": second.model_dump()}

    async def _run_stage(self, stage, payload=None):
        if self._hooks is not None:
            await self._hooks.on_stage_start(stage)
        try:
            result = await self._agents[stage].run(payload)
        except Exception as error:
            if self._hooks is not None:
                await self._hooks.close_failed(str(error))
            raise
        if self._hooks is not None:
            await self._hooks.on_stage_result(stage, result)
        return result


async def _build(exec_service, config, stage_configs, parsed, timeout):
    agents = {}
    for stage in ("first", "second"):
        agent, _ = exec_service.build_agent(stage, (stage_configs or {}).get(stage) or config)
        agents[stage] = agent
    return agents, {}


def _definition():
    return PipelineDefinition(
        name="two-stage",
        stages=["first", "second"],
        parse_input=lambda raw: raw if isinstance(raw, dict) and raw else (_ for _ in ()).throw(
            InvalidConfigError("Invalid pipeline input")
        ),
        build_agents=_build,
        adapt_hooks=lambda generic: generic,
        create_pipeline=lambda agents, hooks, ctx: _Graph(agents, hooks),
        run_pipeline=lambda pipeline, parsed, ctx: pipeline.run(),
    )


def _service(first, second, sink=None):
    exec_service = SimpleNamespace(
        build_agent=lambda agent_type, config: (
            (first, 60) if agent_type == "first" else (second, 60)
        ),
    )
    return GenericPipelineService(
        execution_service=exec_service,  # type: ignore[arg-type]
        callbacks_factory=lambda: sink,
        tracing_backend=NoOpTracingBackend(),
        registry={"two-stage": _definition()},
    )


def _ids():
    return {"first": 11, "second": 12}


class TestRegistry:
    def test_lists_registered_pipelines(self):
        service = _service(StubAgent(_Output()), StubAgent(_Output()))
        assert service.list_pipelines() == ["two-stage"]

    def test_unknown_pipeline_raises(self):
        service = _service(StubAgent(_Output()), StubAgent(_Output()))
        try:
            asyncio.run(service.run("missing", {}, ExecutionConfig()))
        except UnknownPipelineError as error:
            assert "missing" in str(error)
        else:  # pragma: no cover
            raise AssertionError("expected UnknownPipelineError")


class TestGenericHappyPath:
    def test_reports_both_rows_in_order(self):
        sink = RecorderSink()
        service = _service(StubAgent(_Output(kind="library")), StubAgent(_Output(style="ok")), sink)
        result = asyncio.run(
            service.run("two-stage", {"root": "/repo"}, ExecutionConfig(), execution_ids=_ids())
        )
        assert result["first"]["kind"] == "library"
        kinds = [(c[0], c[1]) for c in sink.calls if c[0] != "close"]
        assert kinds == [("running", 11), ("complete", 11), ("running", 12), ("complete", 12)]

    def test_without_execution_ids_nothing_is_reported(self):
        service = _service(StubAgent(_Output()), StubAgent(_Output()), None)
        result = asyncio.run(service.run("two-stage", {"root": "/repo"}, ExecutionConfig()))
        assert result["second"]["style"] == "layered"

    def test_missing_stage_ids_is_422(self):
        service = _service(StubAgent(_Output()), StubAgent(_Output()), RecorderSink())
        try:
            asyncio.run(
                service.run(
                    "two-stage",
                    {"root": "/repo"},
                    ExecutionConfig(),
                    execution_ids={"first": 11},
                )
            )
        except InvalidConfigError as error:
            assert "second" in str(error)
        else:  # pragma: no cover
            raise AssertionError("expected InvalidConfigError")

    def test_bad_input_is_422(self):
        service = _service(StubAgent(_Output()), StubAgent(_Output()))
        try:
            asyncio.run(service.run("two-stage", {}, ExecutionConfig()))
        except InvalidConfigError:
            pass
        else:  # pragma: no cover
            raise AssertionError("expected InvalidConfigError")


class TestGenericFailure:
    def test_second_stage_is_skipped(self):
        sink = RecorderSink()
        service = _service(
            StubAgent(error=RuntimeError("boom")), StubAgent(_Output()), sink
        )
        try:
            asyncio.run(
                service.run("two-stage", {"root": "/repo"}, ExecutionConfig(), execution_ids=_ids())
            )
        except RuntimeError:
            pass
        else:  # pragma: no cover
            raise AssertionError("expected RuntimeError")
        completes = {c[1]: (c[2], c[3]) for c in sink.calls if c[0] == "complete"}
        assert completes[11][0] == "Failed" and "boom" in (completes[11][1] or "")
        assert completes[12][0] == "Failed" and "Skipped" in (completes[12][1] or "")

    def test_timeout_fails_open_rows(self):
        async def slow(input_data):
            await asyncio.sleep(30)
            return _Output()

        first = StubAgent()
        first.run = slow  # type: ignore[method-assign]
        sink = RecorderSink()
        service = _service(first, StubAgent(_Output()), sink)
        try:
            asyncio.run(
                service.run(
                    "two-stage",
                    {"root": "/repo"},
                    ExecutionConfig(),
                    execution_ids=_ids(),
                    timeout_seconds=1,
                )
            )
        except TimeoutError:
            pass
        else:  # pragma: no cover
            raise AssertionError("expected TimeoutError")
        completes = {c[1]: c[2] for c in sink.calls if c[0] == "complete"}
        assert completes[11] == "Failed"
        assert 12 not in completes


class TestGenericRoute:
    def _client(self, service):
        from contextlib import contextmanager

        @contextmanager
        def _override():
            app.dependency_overrides[get_generic_pipeline_service] = lambda: service
            try:
                yield TestClient(app, raise_server_exceptions=False)
            finally:
                app.dependency_overrides.pop(get_generic_pipeline_service, None)

        return _override()

    def test_lists_pipelines(self):
        service = _service(StubAgent(_Output()), StubAgent(_Output()))
        with self._client(service) as client:
            response = client.get("/api/pipelines")
        assert response.status_code == 200
        assert response.json() == ["two-stage"]

    def test_runs_by_name(self):
        seen = []

        class GenericStub:
            async def run(
                self,
                pipeline_name,
                input_data,
                config,
                stage_configs=None,
                execution_ids=None,
                timeout_seconds=600,
            ):
                seen.append(pipeline_name)
                return {"first": {"kind": "library"}}

        from server.app.pipeline_service import (
            get_generic_pipeline_service as _generic_dep,
        )

        app.dependency_overrides[_generic_dep] = lambda: GenericStub()
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/api/pipelines/custom/run",
                    json={"input": {"root": "/repo"}},
                )
        finally:
            app.dependency_overrides.pop(_generic_dep, None)
        assert response.status_code == 200
        assert response.json()["first"]["kind"] == "library"
        assert seen == ["custom"]

    def test_unknown_name_is_404(self):
        service = _service(StubAgent(_Output()), StubAgent(_Output()))
        with self._client(service) as client:
            response = client.post(
                "/api/pipelines/missing/run", json={"input": {"root": "/repo"}}
            )
        assert response.status_code == 404
