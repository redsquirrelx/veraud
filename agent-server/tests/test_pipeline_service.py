"""The pipeline reports each stage to its own backend row.

Stub agents stand in for the real graphs: no model, no network, no repo on
disk. Stub callbacks record what would have been POSTed to the backend.
"""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from server.agents.analyzer.schemas import ProjectDescription
from server.agents.architect.schemas import ArchitectureDescription
from server.api.schemas import ExecutionConfig
from server.app.execution_service import InvalidConfigError
from server.app.pipeline_service import (
    ArchitectureAuditService,
    PipelineExecutionIds,
    PipelineInput,
    PipelineStageConfigs,
)


def _analysis(**overrides):
    values = {
        "kind": "library",
        "summary": "A widget library.",
        "primary_language": "python",
    }
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


class StubCallbacks:
    def __init__(self):
        self.calls = []

    async def mark_running(self, execution_id):
        self.calls.append(("running", execution_id))

    async def complete(self, execution_id, outcome):
        self.calls.append(
            ("complete", execution_id, outcome.status, outcome.result, outcome.error)
        )

    async def aclose(self):
        self.calls.append(("close",))


def _service(analyzer, architect, callbacks=None):
    execution_service = SimpleNamespace(
        build_agent=lambda agent_type, config: (
            (analyzer, 60) if agent_type == "analyzer" else (architect, 60)
        ),
    )
    return ArchitectureAuditService(
        execution_service=execution_service,  # type: ignore[arg-type]
        callbacks_factory=lambda: callbacks,
    )


def _ids():
    return PipelineExecutionIds(analyzer=11, architect=12)


def _input():
    return PipelineInput(root_path="/repo")


class TestHappyPath:
    def test_builds_each_stage_with_its_explicit_backend_configuration(self):
        analyzer = StubAgent(result=_analysis())
        architect = StubAgent(result=_description())
        built = []

        def build(agent_type, config):
            built.append((agent_type, config))
            return (analyzer if agent_type == "analyzer" else architect), 60

        service = ArchitectureAuditService(
            execution_service=SimpleNamespace(build_agent=build),
            callbacks_factory=lambda: None,
        )
        configurations = PipelineStageConfigs(
            analyzer=ExecutionConfig.model_validate(
                {
                    "model": {
                        "provider": "google",
                        "name": "analysis-model",
                        "temperature": 0.2,
                        "max_tokens": 2000,
                    },
                    "api_key": "analysis-key",
                }
            ),
            architect=ExecutionConfig.model_validate(
                {
                    "model": {
                        "provider": "anthropic",
                        "name": "architecture-model",
                        "temperature": 0.5,
                        "max_tokens": 4000,
                    },
                    "api_key": "architecture-key",
                }
            ),
        )
        asyncio.run(
            service.run(
                _input(),
                ExecutionConfig(api_key="unused-fallback"),
                None,
                stage_configs=configurations,
            )
        )
        assert built == [
            ("analyzer", configurations.analyzer),
            ("architect", configurations.architect),
        ]

    def test_reports_both_rows_in_order(self):
        analyzer = StubAgent(result=_analysis())
        architect = StubAgent(result=_description())
        callbacks = StubCallbacks()
        service = _service(analyzer, architect, callbacks)

        result = asyncio.run(service.run(_input(), ExecutionConfig(), _ids()))

        assert result["analysis"]["kind"] == "library"
        assert result["description"]["style"] == "layered"
        kinds = [(call[0], call[1]) for call in callbacks.calls if call[0] != "close"]
        assert kinds == [
            ("running", 11),
            ("complete", 11),
            ("running", 12),
            ("complete", 12),
        ]
        assert callbacks.calls[-1] == ("close",)
        statuses = [call[2] for call in callbacks.calls if call[0] == "complete"]
        assert statuses == ["Completed", "Completed"]

    def test_architect_receives_the_analysis(self):
        analyzer = StubAgent(result=_analysis(kind="cli"))
        architect = StubAgent(result=_description())
        service = _service(analyzer, architect, StubCallbacks())

        asyncio.run(service.run(_input(), ExecutionConfig(), _ids()))

        assert architect.seen[0].analysis.kind == "cli"
        assert architect.seen[0].root_path == "/repo"

    def test_without_execution_ids_nothing_is_reported(self):
        analyzer = StubAgent(result=_analysis())
        architect = StubAgent(result=_description())
        service = _service(analyzer, architect, None)

        result = asyncio.run(service.run(_input(), ExecutionConfig(), None))

        assert result["analysis"]["kind"] == "library"
        assert result["description"]["style"] == "layered"


class TestAnalyzerFailure:
    def test_architect_is_skipped(self):
        analyzer = StubAgent(error=RuntimeError("boom"))
        architect = StubAgent(result=_description())
        callbacks = StubCallbacks()
        service = _service(analyzer, architect, callbacks)

        with pytest.raises(RuntimeError):
            asyncio.run(service.run(_input(), ExecutionConfig(), _ids()))

        assert architect.seen == []
        completes = {
            call[1]: (call[2], call[4])
            for call in callbacks.calls
            if call[0] == "complete"
        }
        assert completes[11][0] == "Failed"
        assert "boom" in (completes[11][1] or "")
        assert completes[12][0] == "Failed"
        assert "Skipped" in (completes[12][1] or "")

    def test_bad_root_fails_both_rows_and_raises(self):
        analyzer = StubAgent(error=FileNotFoundError("no such repo"))
        architect = StubAgent(result=_description())
        callbacks = StubCallbacks()
        service = _service(analyzer, architect, callbacks)

        with pytest.raises(FileNotFoundError):
            asyncio.run(service.run(_input(), ExecutionConfig(), _ids()))

        statuses = {
            call[1]: call[2] for call in callbacks.calls if call[0] == "complete"
        }
        assert statuses == {11: "Failed", 12: "Failed"}


class TestArchitectFailure:
    def test_analyzer_result_stands(self):
        analyzer = StubAgent(result=_analysis())
        architect = StubAgent(error=RuntimeError("architect down"))
        callbacks = StubCallbacks()
        service = _service(analyzer, architect, callbacks)

        with pytest.raises(RuntimeError):
            asyncio.run(service.run(_input(), ExecutionConfig(), _ids()))

        completes = {
            call[1]: call[2] for call in callbacks.calls if call[0] == "complete"
        }
        assert completes == {11: "Completed", 12: "Failed"}


class TestTimeout:
    def test_open_rows_fail_on_timeout(self):
        async def slow(input_data):
            await asyncio.sleep(30)
            return _analysis()

        analyzer = StubAgent(result=None)
        analyzer.run = slow  # type: ignore[method-assign]
        architect = StubAgent(result=_description())
        callbacks = StubCallbacks()
        service = _service(analyzer, architect, callbacks)

        with pytest.raises(TimeoutError):
            asyncio.run(
                service.run(_input(), ExecutionConfig(), _ids(), timeout_seconds=1)
            )

        completes = {
            call[1]: (call[2], call[4])
            for call in callbacks.calls
            if call[0] == "complete"
        }
        assert completes[11][0] == "Failed"
        assert "timed out" in (completes[11][1] or "")
        # The architect never started: nothing was marked, nothing to close.
        assert 12 not in completes


class StubPipelineService:
    def __init__(self, result=None, error=None):
        self._result = result or {
            "analysis": {"kind": "library"},
            "description": {"style": "layered"},
        }
        self._error = error
        self.seen = []

    async def run(
        self, input_data, config, execution_ids, timeout_seconds=600, stage_configs=None
    ):
        self.seen.append((input_data, execution_ids, timeout_seconds))
        if self._error is not None:
            raise self._error
        return self._result


def _client(service):
    from contextlib import contextmanager

    from server.api.pipelines import get_pipeline_service
    from server.main import app

    @contextmanager
    def _override():
        app.dependency_overrides[get_pipeline_service] = lambda: service
        try:
            yield TestClient(app, raise_server_exceptions=False)
        finally:
            app.dependency_overrides.pop(get_pipeline_service, None)

    return _override()


class TestPipelineRoute:
    def test_runs_the_pipeline(self):
        service = StubPipelineService()
        with _client(service) as client:
            response = client.post(
                "/api/pipelines/architecture-audit/run",
                json={
                    "input": {"root_path": "/repo"},
                    "execution_ids": {"analyzer": 1, "architect": 2},
                },
            )

        assert response.status_code == 200
        assert response.json()["analysis"]["kind"] == "library"
        assert response.json()["description"]["style"] == "layered"
        assert service.seen[0][0].root_path == "/repo"
        assert service.seen[0][1].analyzer == 1

    def test_bad_root_is_422(self):
        service = StubPipelineService(error=FileNotFoundError("no such repo"))
        with _client(service) as client:
            response = client.post(
                "/api/pipelines/architecture-audit/run",
                json={"input": {"root_path": "/ghost"}},
            )

        assert response.status_code == 422

    def test_bad_config_is_422(self):
        service = StubPipelineService(error=InvalidConfigError("bad provider"))
        with _client(service) as client:
            response = client.post(
                "/api/pipelines/architecture-audit/run",
                json={"input": {"root_path": "/repo"}},
            )

        assert response.status_code == 422

    def test_timeout_is_504(self):
        service = StubPipelineService(error=TimeoutError())
        with _client(service) as client:
            response = client.post(
                "/api/pipelines/architecture-audit/run",
                json={"input": {"root_path": "/repo"}},
            )

        assert response.status_code == 504


class RecorderHooks:
    def __init__(self):
        self.events = []

    async def on_analyzer_start(self):
        self.events.append("analyzer_start")

    async def on_analysis(self, analysis):
        self.events.append(("analysis", analysis.kind))

    async def on_architect_start(self):
        self.events.append("architect_start")

    async def on_description(self, description):
        self.events.append(("description", description.style))


class TestLangGraphOrchestration:
    def test_graph_runs_analyze_then_describe(self):
        from server.pipelines.architecture_audit import ArchitectureAuditPipeline

        analyzer = StubAgent(result=_analysis(kind="cli"))
        architect = StubAgent(result=_description())
        hooks = RecorderHooks()
        pipeline = ArchitectureAuditPipeline(analyzer, architect, hooks=hooks)

        result = asyncio.run(pipeline.run("/repo"))

        assert result["analysis"]["kind"] == "cli"
        assert result["description"]["style"] == "layered"
        assert hooks.events == [
            "analyzer_start",
            ("analysis", "cli"),
            "architect_start",
            ("description", "layered"),
        ]
        # The analysis flows through the graph state into the architect.
        assert architect.seen[0].analysis.kind == "cli"
        assert architect.seen[0].root_path == "/repo"

    def test_graph_runs_without_hooks(self):
        from server.pipelines.architecture_audit import ArchitectureAuditPipeline

        pipeline = ArchitectureAuditPipeline(
            StubAgent(result=_analysis()), StubAgent(result=_description())
        )

        result = asyncio.run(pipeline.run("/repo"))

        assert result["analysis"]["kind"] == "library"
        assert result["description"]["style"] == "layered"

    def test_graph_aborts_when_analyzer_fails(self):
        from server.pipelines.architecture_audit import ArchitectureAuditPipeline

        analyzer = StubAgent(error=RuntimeError("boom"))
        architect = StubAgent(result=_description())
        hooks = RecorderHooks()
        pipeline = ArchitectureAuditPipeline(analyzer, architect, hooks=hooks)

        with pytest.raises(RuntimeError):
            asyncio.run(pipeline.run("/repo"))

        assert hooks.events == ["analyzer_start"]
        assert architect.seen == []
