"""Pruebas del pipeline HTTP de Adecuación Funcional."""

import asyncio
from types import SimpleNamespace

import pytest

from server.api.schemas import ExecutionConfig
from server.app import functional_adequacy_definition as definition
from server.app.execution_service import AgentExecutionService, InvalidConfigError
from server.app.pipeline_service import GenericPipelineService
from server.app.tracing_port import NoOpTracingBackend


def write_repository(root):
    (root / "src").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nrequires-python = ">=3.11"\n'
        'dependencies = ["fastapi>=0.100"]\n',
        encoding="utf-8",
    )
    (root / "src" / "app.py").write_text(
        "from fastapi import FastAPI\n\n"
        "app = FastAPI()\n\n"
        '@app.get("/items")\n'
        "def list_items():\n"
        "    return []\n",
        encoding="utf-8",
    )


def test_pipeline_runs_exploratory_without_building_a_model(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    repository = workspace / "demo"
    write_repository(repository)
    monkeypatch.setattr(
        definition, "resolve_workspace_root", lambda: workspace.resolve()
    )

    exec_service = AgentExecutionService(
        tracing_backend=NoOpTracingBackend(),
        callbacks_factory=lambda: None,
    )
    monkeypatch.setattr(
        exec_service,
        "build_agent",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Exploratory mode must not build a model")
        ),
    )
    service = GenericPipelineService(
        execution_service=exec_service,
        callbacks_factory=lambda: None,
        tracing_backend=NoOpTracingBackend(),
    )

    result = asyncio.run(
        service.run(
            "functional-adequacy",
            {"root_path": str(repository)},
            ExecutionConfig(),
            timeout_seconds=30,
        )
    )

    assert result["audit_mode"] == "exploratory"
    assert result["score_applicable"] is False
    assert result["capabilities"]
    assert result["results"] == []


def test_pipeline_requirements_mode_uses_the_configured_model():
    captured = {}

    class FakeService:
        async def run(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                model_dump=lambda mode: {"audit_mode": "requirements_based"}
            )

    parsed = definition.parse_functional_input(
        {
            "requirements": [
                {
                    "requirement_id": "REQ-001",
                    "description": "El sistema debe listar elementos.",
                }
            ]
        }
    )
    agents, ctx = asyncio.run(
        definition.build_functional_agents(
            FakeService(), ExecutionConfig(), None, parsed, 30
        )
    )
    pipeline = definition.create_functional_pipeline(agents, None, ctx)

    result = asyncio.run(
        definition.run_functional_pipeline(pipeline, parsed, ctx)
    )

    assert result["audit_mode"] == "requirements_based"
    assert captured["model_required"] is True
    assert captured["payload"]["requirements"][0]["requirement_id"] == "REQ-001"


def test_pipeline_rejects_a_repository_outside_the_workspace(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(
        definition, "resolve_workspace_root", lambda: workspace.resolve()
    )
    parsed = definition.parse_functional_input(
        {"root_path": str(tmp_path / "outside")}
    )

    with pytest.raises(InvalidConfigError, match="directly inside"):
        asyncio.run(
            definition.build_functional_agents(
                SimpleNamespace(), ExecutionConfig(), None, parsed, 30
            )
        )
