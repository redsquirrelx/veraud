"""Validates the portable verification-suite runner flow against a fixture.

Builds a minimal deliverable ZIP (producer of a known violation) and runs it through
validate_zip() — the same code path the HTTP execute endpoint uses — asserting that the
bundled runner detects the violation mechanically, without any LLM.
"""

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.agents.finding_test_generation.config import FindingTestConfig
from server.agents.finding_test_generation.validate_zip import (
    SUMMARY_ACTION_EXECUTE,
    ValidationError,
    validate_zip,
)
from server.api import verification_suite as suite_api

TEMPLATE_BODY = """import os
from pathlib import Path

def test_mod_has_single_top_level_class():
    root = Path(os.environ.get('TALLERCITO_REPO_ROOT', Path(__file__).resolve().parents[2]))
    text = (root / 'pkg/mod.py').read_text(encoding='utf-8')
    assert text.count('class ') <= 1, 'expected a single top-level class'
"""


def _make_zip(destination: Path) -> None:
    manifest = {
        "suite_id": "test-fixture",
        "audit_id": "audit-test",
        "source_commit": "deadbeef",
        "limitations": [],
        "verifications": [
            {
                "verification_id": "verification-001",
                "finding_id": "F-1",
                "rule_kind": "one_class_per_module",
                "generation_status": "generated",
                "strategy": "static_ast",
                "test_path": "tests/test_mod.py",
                "covered_property": "one top-level class per module",
                "target_components": ["pkg/mod.py"],
                "generated_by": "llm",
            },
        ],
    }
    runner_src = (Path(__file__).resolve().parents[3] / "runtimes" / "verification" / "templates" / "runner.py").read_text(encoding="utf-8")
    with zipfile.ZipFile(destination, "w") as archive:
        archive.writestr(".tallercito/manifest.json", json.dumps(manifest))
        archive.writestr(".tallercito/runner.py", runner_src)
        archive.writestr(".tallercito/tests/test_mod.py", TEMPLATE_BODY)


def _make_repo(root: Path) -> None:
    target = root / "pkg"
    target.mkdir(parents=True)
    (target / "mod.py").write_text("class A:\n    pass\nclass B:\n    pass\n", encoding="utf-8")


def test_validate_zip_detects_red_violation_on_fixture(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _make_repo(repo)
    zip_path = tmp_path / "suite.zip"
    _make_zip(zip_path)
    result = validate_zip(zip_path, repo, None, FindingTestConfig(allow_local_unsafe_execution=True))
    assert result["action"] == SUMMARY_ACTION_EXECUTE
    entries = result["verifications"]
    assert len(entries) == 1
    assert entries[0]["status"] == "VIOLATION_PRESENT"
    assert result["validation_status"] == "partial"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def test_endpoint_executes_exact_commits_with_same_zip_and_preserves_dirty_workspace(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _make_repo(repo)
    _git(repo, "init")
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "violating")
    red = _git(repo, "rev-parse", "HEAD")
    target = repo / "pkg/mod.py"
    target.write_text("class A: pass\n", encoding="utf-8")
    _git(repo, "commit", "-am", "corrected control")
    green = _git(repo, "rev-parse", "HEAD")
    target.write_text("dirty and deliberately not valid Python", encoding="utf-8")
    before = _git(repo, "status", "--porcelain")
    artifacts = tmp_path / "artifacts"
    run = artifacts / "audit-test"
    run.mkdir(parents=True)
    archive = run / "verification-suite.zip"
    _make_zip(archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (run / "report.json").write_text(json.dumps({"identification": {
        "repository_location": str(repo), "revisions": [{"commit": red}]}, "quality_results": {"findings": []}}), encoding="utf-8")
    monkeypatch.setattr(suite_api, "artifact_root", lambda: artifacts)
    app = FastAPI()
    app.include_router(suite_api.router)
    with TestClient(app) as client:
        for commit, expected in ((red, "VIOLATION_PRESENT"), (green, "EXECUTION_ERROR")):
            response = client.post("/audit-test/verification-suite", json={
                "action": "execute", "target_commit": commit, "attempt_id": commit, "allow_execution": True})
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["checkout_commit"] == result["target_commit"] == commit
            assert result["suite_sha256"] == digest
            assert result["verifications"][0]["status"] == expected
            assert (run / "verification-executions" / f"{commit}.json").is_file()
        missing = client.post("/audit-test/verification-suite", json={"action": "execute", "target_commit": "f" * 40})
        assert missing.status_code == 422
        denied = client.post("/audit-test/verification-suite", json={"action": "execute", "target_commit": red, "allow_execution": False})
        assert denied.status_code == 403
    assert target.read_text(encoding="utf-8") == "dirty and deliberately not valid Python"
    assert _git(repo, "rev-parse", "HEAD") == green
    assert _git(repo, "status", "--porcelain") == before
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == digest


def test_unavailable_target_never_falls_back_to_working_tree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _make_repo(repo)
    archive = tmp_path / "suite.zip"
    _make_zip(archive)
    with pytest.raises(ValidationError, match="unavailable"):
        validate_zip(archive, repo, None, target_commit="a" * 40)
