"""The runner can save canonical results independently of console formatting."""

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel


@pytest.fixture
def runner():
    path = Path(__file__).parents[1] / "src/test-agents/run_architecture_boundary.py"
    spec = importlib.util.spec_from_file_location("boundary_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
