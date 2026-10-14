"""Phase 3: project-architecture registered as a generic pipeline.

Covers input parsing, registry entry, the workspace guard, agent/model
assembly over a real snapshot (models stubbed), the hooks adapter filtering
the internal diagram node, and the shared resolve_model_settings merge.
Real model calls are out of scope: no provider credentials in tests.
"""

import asyncio
from types import SimpleNamespace

import pytest

from server.api.schemas import ExecutionConfig
from server.app.execution_service import AgentExecutionService, InvalidConfigError
from server.app.pipeline_service import (
    GenericPipelineService,
    default_pipeline_registry,
)
from server.app.project_architecture_definition import (
    ProjectArchitectureHooksAdapter,
    build_project_agents,
    parse_project_architecture_input,
)
from server.app.tracing_port import NoOpTracingBackend


def _config(**overrides):
    values = {
        "model": {"provider": "openrouter", "name": "org/model"},
        "api_key": "test-key",
    }
    values.update(overrides)
    return ExecutionConfig.model_validate(values)


class RecorderSink:
    def __init__(self):
        self.calls = []

    async def mark_running(self, execution_id):
        self.calls.append(("running", execution_id))

    async def complete(self, execution_id, outcome):
        self.calls.append(("complete", execution_id, outcome.status, outcome.error))

    async def aclose(self):
        self.calls.append(("close",))


def _fake_result():
    return SimpleNamespace(model_dump_json=lambda: '{"ok": true}')


class TestInput:
    def test_defaults_mirror_cli_investigation(self):
        parsed = parse_project_architecture_input({"root_path": "/repo"})
        assert (parsed.max_files, parsed.max_depth) == (5000, 30)
        assert (parsed.max_model_calls, parsed.max_tool_calls) == (8, 20)
        assert parsed.include_orientation is True
        assert parsed.validate_semantics is True
        assert parsed.allow_return is True
        assert parsed.include_diagram is True

    def test_invalid_input_is_422(self):
        with pytest.raises(InvalidConfigError):
            parse_project_architecture_input({})


class TestRegistry:
    def test_project_architecture_registered_with_three_stages(self):
        registry = default_pipeline_registry()
        definition = registry["project-architecture"]
        assert definition.stages == ["orientation", "architecture", "semantic_validation"]
        assert definition.agent_type_for("orientation") == "orientation"

    def test_list_pipelines_sorted(self):
        service = GenericPipelineService(tracing_backend=NoOpTracingBackend())
        assert service.list_pipelines() == ["project-architecture"]


class TestResolveModelSettings:
    def test_explicit_config_passes_through(self):
        service = AgentExecutionService(
            tracing_backend=NoOpTracingBackend(), callbacks_factory=lambda: None
        )
        settings, credentials, timeout = service.resolve_model_settings(
            "orientation", _config()
        )
        assert (settings.provider, settings.name) == ("openrouter", "org/model")
        assert settings.temperature == 0.2
        assert credentials.api_key == "test-key"
        assert timeout == 60

    def test_missing_name_is_422(self):
        service = AgentExecutionService(
            tracing_backend=NoOpTracingBackend(), callbacks_factory=lambda: None
        )
        with pytest.raises(InvalidConfigError, match="model.name is required"):
            service.resolve_model_settings("orientation", ExecutionConfig())


class TestWorkspaceGuard:
    def test_root_outside_workspace_is_422(self):
        exec_stub = SimpleNamespace(
            resolve_model_settings=lambda *args: (_ for _ in ()).throw(
                AssertionError("must not build models")
            )
        )
        parsed = parse_project_architecture_input({"root_path": "/elsewhere/repo"})
        with pytest.raises(InvalidConfigError, match="directly inside the shared workspace"):
            asyncio.run(build_project_agents(exec_stub, _config(), None, parsed, 600))


class TestBuildProjectAgents:
    def test_builds_three_agents_over_real_snapshot(
        self, tmp_path, monkeypatch
    ):
        from server.app import project_architecture_definition as definition_module

        workspace = tmp_path / "workspace"
        repo = workspace / "repo"
        repo.mkdir(parents=True)
        (repo / "main.py").write_text("def main():\n    return 1\n")
        monkeypatch.setattr(
            definition_module, "resolve_workspace_root", lambda: workspace
        )

        made_models = []

        def fake_create(settings, credentials):
            model = SimpleNamespace(settings=settings)
            made_models.append(model)
            return model

        monkeypatch.setattr(
            definition_module, "create_project_model", fake_create
        )

        exec_stub = SimpleNamespace(
            resolve_model_settings=lambda stage, config: (
                SimpleNamespace(provider="test", name=f"{stage}-model"),
                SimpleNamespace(api_key="k"),
                600,
            )
        )
        parsed = parse_project_architecture_input({"root_path": str(repo)})
        agents, ctx = asyncio.run(
            build_project_agents(exec_stub, _config(), None, parsed, 600)
        )

        assert set(agents) == {"orientation", "architecture", "semantic_validation"}
        assert len(made_models) == 3
        assert ctx["snapshot"].repository.name == "repo"
        assert len(ctx["snapshot"].files) >= 1
        assert ctx["budget"].max_elapsed_seconds == 600
        assert ctx["workspace_root"] == workspace.resolve()
        for agent in agents.values():
            assert agent.generate.trace is True


class TestHooksAdapter:
    def test_tracks_rows_and_ignores_diagram_node(self):
        sink = RecorderSink()
        from server.app.pipeline_service import GenericReportingHooks

        generic = GenericReportingHooks(
            sink,
            {"orientation": 21, "architecture": 22, "semantic_validation": 23},
            ["orientation", "architecture", "semantic_validation"],
        )
        adapter = ProjectArchitectureHooksAdapter(generic)

        async def main():
            await adapter.on_stage_start("orientation")
            await adapter.on_stage_result("orientation", _fake_result())
            await adapter.on_stage_start("diagram_composition")
            await adapter.on_stage_result("diagram_composition", _fake_result())
            await generic.close_failed("boom")

        asyncio.run(main())

        kinds = [(c[0], c[1]) for c in sink.calls if c[0] != "close"]
        assert kinds == [
            ("running", 21),
            ("complete", 21),
            ("complete", 22),
            ("complete", 23),
        ]
        completes = {c[1]: (c[2], c[3]) for c in sink.calls if c[0] == "complete"}
        assert completes[22][0] == "Failed" and "boom" in (completes[22][1] or "")
        assert completes[23][0] == "Failed" and "Skipped" in (completes[23][1] or "")

    def test_skipped_stage_closes_its_row_instead_of_hanging(self):
        sink = RecorderSink()
        from server.app.pipeline_service import GenericReportingHooks

        generic = GenericReportingHooks(
            sink,
            {"orientation": 21, "architecture": 22, "semantic_validation": 23},
            ["orientation", "architecture", "semantic_validation"],
        )
        adapter = ProjectArchitectureHooksAdapter(generic)

        async def main():
            await adapter.on_stage_start("orientation")
            await adapter.on_stage_result("orientation", _fake_result())
            await adapter.on_stage_skip("diagram_composition", "No organization units.")
            await adapter.on_stage_skip("semantic_validation", "No architecture report was produced.")

        asyncio.run(main())

        completes = {c[1]: (c[2], c[3]) for c in sink.calls if c[0] == "complete"}
        # Diagram has no row: nothing reported for it.
        assert set(completes) == {21, 23}
        assert completes[21][0] == "Completed"
        assert completes[23][0] == "Failed"
        assert "Skipped" in (completes[23][1] or "")
        assert "No architecture report" in (completes[23][1] or "")
