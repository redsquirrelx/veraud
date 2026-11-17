"""Node lane and install controls: no model calls, original repo stays untouched."""

import json
import shutil

import pytest

from server.agents.testability_probe.llm_client import extract_code
from server.runtimes.verification.templates import node_runtime as node
from server.runtimes.verification.tools.workspace_writer import WorkspaceWriter


def test_detect_languages_and_fences():
    assert node.language_for(["lib/auth/session.ts"]) == "typescript"
    assert node.language_for(["app/component.tsx"]) == "typescript"
    assert node.language_for(["api/client.js"]) == "javascript"
    assert node.language_for(["src/client.py"]) == "python"
    assert extract_code("```tsx\nconst x = 1;\n```") == "const x = 1;\n"


def test_writer_confines_node_tests(tmp_path):
    writer = WorkspaceWriter(tmp_path)
    writer.write_test_file(".tallercito/tests/check.test.tsx", "test('x', () => expect(1).toBe(1));")
    with pytest.raises(ValueError):
        writer.write_test_file("src/production.ts", "no")
    with pytest.raises(ValueError):
        writer.write_test_file(".tallercito/tests/../../../escape.ts", "no")


def test_install_uses_lock_ignore_scripts_and_clean_env(tmp_path, monkeypatch):
    (tmp_path / "package.json").write_text('{"name":"example"}')
    (tmp_path / "package-lock.json").write_text("{}")
    (tmp_path / ".npmrc").write_text("registry=https://example.invalid")
    seen = []
    monkeypatch.setattr(node, "command", lambda args, root, timeout: (
        seen.append(args) or {"exit_code": 1, "timeout": False}))
    monkeypatch.setenv("LLM_API_KEY", "secret-not-for-child")
    receipt = node.install_project(tmp_path)
    assert receipt["status"] == "failed"
    assert seen == [["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"]]
    assert "LLM_API_KEY" not in node.clean_env(tmp_path)
    assert not (tmp_path / ".npmrc").exists()
    seen.clear()
    assert node.install_project(tmp_path, enabled=False)["status"] == "disabled"
    assert seen == []
    (tmp_path / "pnpm-lock.yaml").touch()
    node.install_project(tmp_path)
    assert seen[0] == ["pnpm", "install", "--frozen-lockfile", "--ignore-scripts"]


@pytest.mark.skipif(not shutil.which("node"), reason="Node runtime unavailable")
def test_node_runner_pass_red_import_and_mixed_failures(tmp_path):
    tests = tmp_path / ".tallercito" / "tests"
    tests.mkdir(parents=True)
    header = "import {test} from 'node:test'; import assert from 'node:assert/strict';\n"
    path = tests / "check.test.mjs"
    path.write_text(header + "test('check', () => assert.equal(1, 1));")
    assert node.run(tmp_path, ".tallercito/tests/check.test.mjs", "node:test")["classification"] == "pass"
    path.write_text(header + "test('check', () => assert.equal(1, 2));")
    assert node.run(tmp_path, ".tallercito/tests/check.test.mjs", "node:test")["classification"] == "violation"
    path.write_text(header + "test('check', () => { throw new TypeError('broken'); });")
    assert node.run(tmp_path, ".tallercito/tests/check.test.mjs", "node:test")["classification"] == "technical_failure"
    path.write_text("import './absent.mjs';\n" + header)
    assert node.run(tmp_path, ".tallercito/tests/check.test.mjs", "node:test")["classification"] == "technical_failure"
    assert node.classify_cases([{"kind": "passed"}, {"kind": "error"}], 1) == "technical_failure"


@pytest.mark.skipif(not shutil.which("node"), reason="Node runtime unavailable")
def test_portable_node_execution_does_not_install_into_checkout(tmp_path):
    repo = tmp_path / "original"
    tests = repo / ".tallercito" / "tests"
    tests.mkdir(parents=True)
    original = '{"name":"untouched"}'
    (repo / "package.json").write_text(original)
    (repo / ".env").write_text("TOP_SECRET=must-not-copy")
    (tests / "check.test.mjs").write_text(
        "import {test} from 'node:test'; import assert from 'node:assert/strict';"
        "import fs from 'node:fs'; import path from 'node:path';"
        "test('safe copy', () => assert.equal(fs.existsSync(path.join(process.env.TALLERCITO_REPO_ROOT, '.env')), false));")
    observed, receipt = node.run_exported(repo, repo / ".tallercito", [{
        "verification_id": "probe-1", "test_path": "tests/check.test.mjs", "framework": "node:test"}], install=False)
    assert observed["probe-1"]["classification"] == "pass"
    assert receipt["status"] == "disabled"
    assert (repo / "package.json").read_text() == original
    assert not (repo / "node_modules").exists()
    assert not (repo / ".tallercito" / "package.json").exists()


def test_plan_has_target_source_even_if_layout_truncated(tmp_path):
    from server.agents.testability_probe.execution import _repo_layout
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}))
    for directory in ("agents-service", "ai-service", "app"):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "file.ts").write_text("export const x = 1")
    layout = _repo_layout(str(tmp_path), max_dirs=1)
    assert "package.json" in layout
