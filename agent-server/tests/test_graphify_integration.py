"""End-to-end checks against the pinned Graphify package, without adapter mocks."""

import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest

from server.services.graphify import GraphifyAdapter
from server.services.repository_structure import RepositoryStructureService


def test_extract_python_and_typescript_modules_symbols_and_relationships(tmp_path):
    repository = tmp_path / "mixed repository"
    repository.mkdir()
    sources = {
        "py_base.py": (
            "class PyBase:\n"
            "    pass\n\n"
            "def py_helper():\n"
            "    return 42\n"
        ),
        "py_service.py": (
            "from py_base import PyBase, py_helper\n\n"
            "class PyService(PyBase):\n"
            "    def execute(self):\n"
            "        return py_helper()\n"
        ),
        "ts_base.ts": (
            "export class TsBase {}\n"
            "export function tsHelper(): number { return 42; }\n"
        ),
        "ts_service.ts": (
            'import { TsBase, tsHelper } from "./ts_base";\n'
            "export class TsService extends TsBase {\n"
            "  execute(): number { return tsHelper(); }\n"
            "}\n"
        ),
    }
    for name, content in sources.items():
        (repository / name).write_text(content, encoding="utf-8")

    result = asyncio.run(RepositoryStructureService().extract_structure(
        repository_path=repository,
        output_directory=tmp_path / "artifacts",
    ))

    # This is the output artifact of this test only, not a project input file.
    graph = json.loads(result.graph_file.read_text(encoding="utf-8"))
    nodes = graph["nodes"]
    edges = graph.get("links", graph.get("edges", []))

    def node_id(label, source):
        matches = [
            node["id"] for node in nodes
            if node["label"] == label and Path(node.get("source_file", "")).name == source
        ]
        assert len(matches) == 1, f"Expected one sourced node for {source}:{label}, got {matches}"
        return matches[0]

    def assert_relation(source, target, relation):
        assert any(
            edge["source"] == source
            and edge["target"] == target
            and edge["relation"] == relation
            for edge in edges
        ), f"Missing {relation}: {source} -> {target}"

    for prefix, base, service, helper in [
        ("py", "PyBase", "PyService", "py_helper()"),
        ("ts", "TsBase", "TsService", "tsHelper()"),
    ]:
        extension = "py" if prefix == "py" else "ts"
        base_file = f"{prefix}_base.{extension}"
        service_file = f"{prefix}_service.{extension}"
        base_module = node_id(base_file, base_file)
        service_module = node_id(service_file, service_file)
        base_class = node_id(base, base_file)
        service_class = node_id(service, service_file)
        helper_function = node_id(helper, base_file)
        execute_method = node_id(".execute()", service_file)

        assert_relation(base_module, base_class, "contains")
        assert_relation(base_module, helper_function, "contains")
        assert_relation(service_module, service_class, "contains")
        assert_relation(service_class, execute_method, "method")
        # Targets must be the definitions in the other file, not unresolved stubs.
        assert_relation(service_class, base_class, "inherits")
        assert_relation(execute_method, helper_function, "calls")

    assert {path.name for path in repository.iterdir()} == set(sources)
    for name, content in sources.items():
        assert (repository / name).read_text(encoding="utf-8") == content


VERAUD_URL = "https://github.com/redsquirrelx/veraud.git"
VERAUD_REVISION = "f8250927f91fa00bc524c38d035c07c212c1b719"


@pytest.mark.skipif(
    os.environ.get("RUN_GRAPHIFY_VERAUD_INTEGRATION") != "1",
    reason="Set RUN_GRAPHIFY_VERAUD_INTEGRATION=1 to clone and analyze the real repository.",
)
def test_extract_real_veraud_repository(tmp_path, record_property):
    """Analyze the complete pinned upstream checkout, never the developer's worktree."""
    repository = tmp_path / "veraud"
    repository.mkdir()

    def git(*arguments):
        return subprocess.run(
            ["git", "-c", "core.autocrlf=false", *arguments],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        ).stdout.strip()

    git("init", "--quiet")
    git("fetch", "--quiet", "--depth=1", VERAUD_URL, VERAUD_REVISION)
    git("-c", "core.hooksPath=", "checkout", "--quiet", "--detach", "FETCH_HEAD")
    assert git("rev-parse", "HEAD") == VERAUD_REVISION
    record_property("repository", VERAUD_URL)
    record_property("revision", VERAUD_REVISION)

    service = RepositoryStructureService(GraphifyAdapter(timeout_seconds=600, max_workers=2))
    result = asyncio.run(service.extract_structure(repository, tmp_path / "artifacts"))
    graph = json.loads(result.graph_file.read_text(encoding="utf-8"))
    nodes = graph["nodes"]
    edges = graph.get("links", graph.get("edges", []))

    def node_id(label, source):
        matches = [
            node["id"] for node in nodes
            if node["label"] == label
            and node.get("source_file", "").replace("\\", "/").endswith(source)
        ]
        assert len(matches) == 1, f"Expected one sourced node for {source}:{label}, got {matches}"
        return matches[0]

    known_calls = [
        (
            "agent-server/src/server/services/repository_analysis/source_code.py",
            "extract_source_code()",
            "extract_python_symbols()",
        ),
        (
            "frontend/src/shared/ui-kit/directoryTree.ts",
            "listExtensions()",
            "extensionOf()",
        ),
    ]
    relations = {(edge["source"], edge["target"], edge["relation"]) for edge in edges}
    for source, caller_label, callee_label in known_calls:
        module = node_id(Path(source).name, source)
        caller = node_id(caller_label, source)
        callee = node_id(callee_label, source)
        assert (module, caller, "contains") in relations
        assert (module, callee, "contains") in relations
        assert (caller, callee, "calls") in relations

    assert git("status", "--porcelain", "--untracked-files=all") == ""
