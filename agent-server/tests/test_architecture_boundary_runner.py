"""The runner can save canonical results independently of console formatting."""

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel


@pytest.fixture(params=["architecture_boundary", "architecture_boundary_doc_driven"])
def runner(request):
    path = Path(__file__).parents[1] / f"src/test-agents/run_{request.param}.py"
    spec = importlib.util.spec_from_file_location("boundary_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runner_uses_the_corresponding_agent_package(runner):
    variant = Path(runner.__file__).stem.removeprefix("run_")
    version = "v2" if variant.endswith("_doc_driven") else "v1"
    package = f"server.agents.maintainability.{version}.modularity.{variant}"
    assert runner.ArchitectureBoundaryAgent.__module__ == f"{package}.agent"
    assert runner.AuditRequest.__module__ == f"{package}.schemas"
    assert runner.BoundaryConfig.__module__ == f"{package}.config"


def test_doc_driven_loads_canonical_context_into_request(runner, tmp_path, monkeypatch):
    if not Path(runner.__file__).stem.endswith("_doc_driven"):
        pytest.skip("Only the doc-driven runner loads documentary context")
    context = {"document_index": None, "knowledge": [], "knowledge_issues": [],
        "covered_categories": [], "pending_categories": [], "evaluated_categories": [],
        "coverage_assessment_status": "not_run", "consulted_documents": [], "section_paths": {},
        "validation_errors": [], "execution_status": "failed", "finalization_reason": "fixture"}
    root = tmp_path / "harness"
    script = root / "src/test-agents/run_architecture_boundary_doc_driven.py"
    script.parent.mkdir(parents=True)
    context_path = root / "examples/shoplab/architecture_context.json"
    context_path.parent.mkdir(parents=True)
    context_path.write_text(json.dumps(context), encoding="utf-8")
    monkeypatch.setattr(runner, "__file__", str(script))
    monkeypatch.chdir(tmp_path)
    model = object()
    settings = SimpleNamespace()
    monkeypatch.setattr(runner, "load_test_model", lambda _: (model, settings))
    audit = AsyncMock()
    cleanup = AsyncMock()
    monkeypatch.setattr(runner, "run_audit", audit)
    monkeypatch.setattr(runner, "close_model_clients", cleanup)
    args = SimpleNamespace(repository=str(tmp_path), request=None, config=None, agent_config="dummy",
        architecture_context=context_path.relative_to(tmp_path))

    asyncio.run(runner.run(args))

    assert audit.await_args.args[2].documented_architecture.model_dump(exclude={"schema_version", "execution_error"}) == context
    assert audit.await_args.args[0] is args
    cleanup.assert_awaited_once()


def test_doc_driven_without_context_does_not_load_a_default_file(runner, tmp_path, monkeypatch):
    if not Path(runner.__file__).stem.endswith("_doc_driven"):
        pytest.skip("Only the doc-driven runner accepts documentary context")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "load_test_model", lambda _: (object(), SimpleNamespace()))
    audit = AsyncMock()
    monkeypatch.setattr(runner, "run_audit", audit)
    monkeypatch.setattr(runner, "close_model_clients", AsyncMock())
    args = SimpleNamespace(repository=str(tmp_path), request=None, config=None, agent_config="dummy",
        architecture_context=None)
    asyncio.run(runner.run(args))
    assert audit.await_args.args[2].documented_architecture is None


@pytest.mark.parametrize("output", ["readable", "json"])
def test_output_file_retains_complete_result_in_utf8(tmp_path, monkeypatch, capsys, output, runner):
    root = tmp_path / "repository"
    root.mkdir()
    (root / "service.py").write_text("def run(): return 1\n", encoding="utf-8")
    destination = tmp_path / "result.json"

    class Result(BaseModel):
        description: str = "Revisión de límites: información íntegra."
        findings: list[str] = ["Hallazgo provisional"]

    result = Result()

    class Agent:
        def __init__(self, model, config):
            pass

        async def run(self, tools, request):
            return result

    class Tracing:
        async def wrap_stage(self, operation, **kwargs):
            return await operation

    monkeypatch.setattr(runner, "render_boundary_plan", lambda result: "Readable summary")
    args = SimpleNamespace(max_files=10, output=output, output_file=str(destination))
    settings = SimpleNamespace(max_tokens=4000, provider="test", name="test")
    asyncio.run(runner.run_audit(args, root, runner.AuditRequest(), runner.BoundaryConfig(), None, settings,
        agent_class=Agent, tracing_backend=Tracing()))
    saved = destination.read_text(encoding="utf-8")
    assert json.loads(saved) == result.model_dump(mode="json")
    assert "Revisión de límites" in saved
    console = capsys.readouterr().out
    if output == "readable":
        assert console.strip() == "Readable summary"
    else:
        assert json.loads(console) == json.loads(saved)
