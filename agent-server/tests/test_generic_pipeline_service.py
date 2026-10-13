"""Phase 2: generic pipeline service runs registered pipelines by name.

The legacy architecture-audit path must behave identically through the
generic service (reporting order, skip-on-failure, timeout fail-open,
no-report without execution ids), plus registry listing, unknown-pipeline
404s, and the generic HTTP endpoints.
"""

import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient

from server.agents.analyzer.schemas import ProjectDescription
from server.agents.architect.schemas import ArchitectureDescription
from server.api.schemas import ExecutionConfig
from server.app.pipeline_service import (
    GenericPipelineService,
    UnknownPipelineError,
    get_generic_pipeline_service,
)
from server.app.tracing_port import NoOpTracingBackend
from server.main import app


def _analysis(**overrides):
    values = {"kind": "library", "summary": "s", "primary_language": "python"}
    values.update(overrides)
    return ProjectDescription(**values)


def _description():
    return ArchitectureDescription(style="layered")


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


def _service(analyzer, architect, sink=None):
    exec_service = SimpleNamespace(
        build_agent=lambda agent_type, config: (
            (analyzer, 60) if agent_type == "analyzer" else (architect, 60)
        ),
    )
    return GenericPipelineService(
        execution_service=exec_service,  # type: ignore[arg-type]
        callbacks_factory=lambda: sink,
        tracing_backend=NoOpTracingBackend(),
    )


def _ids():
    return {"analyzer": 11, "architect": 12}


class TestRegistry:
    def test_lists_registered_pipelines(self):
        service = _service(StubAgent(_analysis()), StubAgent(_description()))
        assert service.list_pipelines() == ["architecture-audit", "project-architecture"]

    def test_unknown_pipeline_raises(self):
        service = _service(StubAgent(_analysis()), StubAgent(_description()))
        try:
            asyncio.run(
                service.run("missing", {"root_path": "/repo"}, ExecutionConfig())
            )
        except UnknownPipelineError as error:
            assert "missing" in str(error)
        else:  # pragma: no cover
            raise AssertionError("expected UnknownPipelineError")


class TestGenericHappyPath:
    def test_reports_both_rows_in_order(self):
        sink = RecorderSink()
        service = _service(StubAgent(_analysis()), StubAgent(_description()), sink)
        result = asyncio.run(
            service.run(
                "architecture-audit", {"root_path": "/repo"}, ExecutionConfig(), execution_ids=_ids()
            )
        )
        assert result["analysis"]["kind"] == "library"
        kinds = [(c[0], c[1]) for c in sink.calls if c[0] != "close"]
        assert kinds == [("running", 11), ("complete", 11), ("running", 12), ("complete", 12)]

    def test_without_execution_ids_nothing_is_reported(self):
        service = _service(StubAgent(_analysis()), StubAgent(_description()), None)
        result = asyncio.run(
            service.run("architecture-audit", {"root_path": "/repo"}, ExecutionConfig())
        )
        assert result["description"]["style"] == "layered"

    def test_missing_stage_ids_is_422(self):
        from server.app.execution_service import InvalidConfigError

        service = _service(StubAgent(_analysis()), StubAgent(_description()), RecorderSink())
        try:
            asyncio.run(
                service.run(
                    "architecture-audit",
                    {"root_path": "/repo"},
                    ExecutionConfig(),
                    execution_ids={"analyzer": 11},
                )
            )
        except InvalidConfigError as error:
            assert "architect" in str(error)
        else:  # pragma: no cover
            raise AssertionError("expected InvalidConfigError")

    def test_bad_input_is_422(self):
        from server.app.execution_service import InvalidConfigError

        service = _service(StubAgent(_analysis()), StubAgent(_description()))
        try:
            asyncio.run(service.run("architecture-audit", {}, ExecutionConfig()))
        except InvalidConfigError:
            pass
        else:  # pragma: no cover
            raise AssertionError("expected InvalidConfigError")


class TestGenericFailure:
    def test_analyzer_failure_skips_architect(self):
        sink = RecorderSink()
        service = _service(
            StubAgent(error=RuntimeError("boom")), StubAgent(_description()), sink
        )
        try:
            asyncio.run(
                service.run(
                    "architecture-audit", {"root_path": "/repo"}, ExecutionConfig(), execution_ids=_ids()
                )
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
            return _analysis()

        analyzer = StubAgent()
        analyzer.run = slow  # type: ignore[method-assign]
        sink = RecorderSink()
        service = _service(analyzer, StubAgent(_description()), sink)
        try:
            asyncio.run(
                service.run(
                    "architecture-audit",
                    {"root_path": "/repo"},
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
        service = _service(StubAgent(_analysis()), StubAgent(_description()))
        with self._client(service) as client:
            response = client.get("/api/pipelines")
        assert response.status_code == 200
        assert response.json() == ["architecture-audit", "project-architecture"]

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
                return {"analysis": {"kind": "library"}}

        app.dependency_overrides[get_generic_pipeline_service] = lambda: GenericStub()
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/api/pipelines/custom/run",
                    json={"input": {"root_path": "/repo"}},
                )
        finally:
            app.dependency_overrides.pop(get_generic_pipeline_service, None)
        assert response.status_code == 200
        assert response.json()["analysis"]["kind"] == "library"
        assert seen == ["custom"]

    def test_unknown_name_is_404(self):
        service = _service(StubAgent(_analysis()), StubAgent(_description()))
        with self._client(service) as client:
            response = client.post(
                "/api/pipelines/missing/run", json={"input": {"root_path": "/repo"}}
            )
        assert response.status_code == 404
