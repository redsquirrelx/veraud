import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from server import run_graphify
from server.services.graphify import GraphifyError, GraphifyResult
from server.services.repository_structure import RepositoryStructureService


def test_service_delegates_to_graphify_adapter():
    repository = Path("repository")
    output = Path("artifacts")
    expected = GraphifyResult(graph_file=output / "graphify-out" / "graph.json", elapsed_seconds=1)
    adapter = AsyncMock()
    adapter.extract.return_value = expected

    result = asyncio.run(RepositoryStructureService(adapter).extract_structure(repository, output))

    assert result is expected
    adapter.extract.assert_awaited_once_with(repository_path=repository, output_directory=output)


def test_service_preserves_adapter_failure():
    failure = GraphifyError("execution_failed", returncode=1)
    adapter = AsyncMock()
    adapter.extract.side_effect = failure
    with pytest.raises(GraphifyError) as error:
        asyncio.run(RepositoryStructureService(adapter).extract_structure(Path("repo"), Path("out")))
    assert error.value is failure


def test_runner_extracts_real_repository(tmp_path, capsys):
    repository = tmp_path / "repository with spaces"
    repository.mkdir()
    source = repository / "example.py"
    content = "class Service:\n    def execute(self):\n        return 42\n"
    source.write_text(content, encoding="utf-8")
    output = tmp_path / "new artifacts"

    assert run_graphify.main([str(repository), "--out", str(output)]) == 0

    graph = output / "graphify-out" / "graph.json"
    assert graph.is_file() and graph.stat().st_size > 0
    assert list(repository.iterdir()) == [source]
    assert source.read_text(encoding="utf-8") == content
    captured = capsys.readouterr()
    assert str(graph) in captured.out
    assert "static analysis, no LLM" in captured.out
    assert captured.err == ""


def test_runner_reports_safe_error(tmp_path, capsys):
    assert run_graphify.main([str(tmp_path / "missing"), "--out", str(tmp_path / "out")]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "invalid_path" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize("option,value", [("--timeout", "0"), ("--max-workers", "0")])
def test_runner_rejects_invalid_limits_before_extraction(option, value, monkeypatch):
    extract = AsyncMock()
    monkeypatch.setattr(RepositoryStructureService, "extract_structure", extract)
    with pytest.raises(SystemExit) as error:
        run_graphify.main(["repository", "--out", "output", option, value])
    assert error.value.code == 2
    extract.assert_not_called()


def test_runner_passes_limits_and_paths_to_service(tmp_path, monkeypatch):
    extract = AsyncMock(return_value=GraphifyResult(tmp_path / "graph.json", 0.5))
    monkeypatch.setattr(RepositoryStructureService, "extract_structure", extract)
    original_adapter = run_graphify.GraphifyAdapter
    adapters = []

    def create_adapter(**kwargs):
        adapter = original_adapter(**kwargs)
        adapters.append(adapter)
        return adapter

    monkeypatch.setattr(run_graphify, "GraphifyAdapter", create_adapter)
    assert run_graphify.main([
        "repository", "--out", "output", "--timeout", "30", "--max-workers", "2",
    ]) == 0
    assert adapters[0].timeout_seconds == 30
    assert adapters[0].max_workers == 2
    extract.assert_awaited_once_with(Path("repository"), Path("output"))


def test_runner_reports_interruption(monkeypatch, capsys):
    extract = AsyncMock(side_effect=KeyboardInterrupt())
    monkeypatch.setattr(RepositoryStructureService, "extract_structure", extract)
    assert run_graphify.main(["repository", "--out", "output"]) == 130
    assert "cancelled" in capsys.readouterr().err
