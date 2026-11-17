"""Offline acceptance tests for the unified verification-suite flow.

Everything here runs without LLM calls, without network access and without a
real audit: synthetic payloads drive split, merge and the filtered runner.
"""

import json
import sys
import zipfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.agents.testability_probe import audit_input
from server.api import verification_suite as suite_api
from server.runtimes.verification import split, zip_validate
from server.runtimes.verification.merge import (
    load_agent_zip,
    merge_suite_zips,
)

AUDIT_FIXTURE = {
    "auditId": 4242,
    "commitHash": "a" * 40,
    "project_name": "C:/tmp/repo",
    "findings": [
        {"id": "ftg-1", "title": "Boundary violation", "description": "d", "kind": "violation",
         "quality_attribute": "maintainability", "subcharacteristic": "modularity",
         "criterion": {"id": "architectural-boundaries", "description": "", "origin": "", "provenance": ""},
         "severity": "medium", "components": ["src/x.py"], "evidence_ids": [],
         "justification": "j", "impact": "i", "recommendation": "r",
         "technical_details": {"id": "t1", "document_claim_ids": ["claim-1"], "evidence_ids": ["retrieval:1"]}},
        {"id": "probe-1", "title": "Clock dependency", "description": "d", "kind": "violation",
         "quality_attribute": "maintainability", "subcharacteristic": "testability",
         "criterion": {"id": "test-controllability", "description": "", "origin": "", "provenance": ""},
         "severity": "medium", "components": ["src/y.py"], "evidence_ids": [],
         "justification": "j", "impact": "i", "recommendation": "r",
         "technical_details": {"id": "t2", "document_claim_ids": ["claim-2"], "evidence_ids": ["retrieval:2"]}},
        {"id": "other-1", "title": "Mystery", "description": "d", "kind": "violation",
         "quality_attribute": "maintainability", "subcharacteristic": "",
         "criterion": {"id": "abstraction", "description": "", "origin": "", "provenance": ""},
         "severity": "low", "components": ["src/z.py"], "evidence_ids": [],
         "justification": "j", "impact": "i", "recommendation": "r",
         "technical_details": {"id": "t3", "document_claim_ids": [], "evidence_ids": []}},
    ],
}



def test_split_routes_by_subcharacteristic():
    buckets = split.split_findings(AUDIT_FIXTURE["findings"])
    assert [f["id"] for f in buckets["ftg"]] == ["ftg-1"]
    assert [f["id"] for f in buckets["probe"]] == ["probe-1"]
    assert [f["id"] for f in buckets["unsupported"]] == ["other-1"]
    assert split.group_of(AUDIT_FIXTURE["findings"][0]) == "modularity"
    assert split.group_of(AUDIT_FIXTURE["findings"][1]) == "testability"


def test_group_of_falls_back_to_criterion_id():
    finding = {"criterion_id": "test-isolation"}
    assert split.group_of(finding) == "test-isolation"
    assert split.route_agent(finding) == "probe"


def test_audit_input_adapter_preserves_probe_fields():
    converted = audit_input.convert_audit_export(AUDIT_FIXTURE)
    assert converted["repository_id"] == "C:/tmp/repo"
    assert converted["commit"] == "a" * 40
    probe_findings = converted["findings"]
    assert probe_findings[0]["criterion_id"] == "architectural-boundaries"
    assert probe_findings[0]["modularity_impact"] == "i"
    assert probe_findings[0]["document_claim_ids"] == ["claim-1"]
    assert probe_findings[0]["evidence"] == []
    assert probe_findings[1]["criterion_id"] == "test-controllability"


def _member_zip(destination: Path, members: dict[str, str]) -> Path:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in members.items():
            archive.writestr(path, content)
    return destination


def _probe_zip(destination: Path, *, finding_id: str) -> Path:
    tests = {"test_probe_check.py": "def test_check():\n    assert False, 'denounced'\n"}
    members = {
        ".tallercito/tests/test_probe_check.py": tests["test_probe_check.py"],
        ".tallercito/manifest.json": json.dumps({
            "schema_version": "1.1",
            "generator": "testability-probe",
            "suite_id": "probe-suite",
            "source_commit": "deadbeef",
            "verifications": [{
                "verification_id": "probe-001",
                "finding_id": finding_id,
                "test_path": "tests/test_probe_check.py",
                "test_name": "test_check",
                "strategy": "static_ast",
                "covered_property": "condition",
                "condition": "condition",
                "target_components": ["src/y.py"],
                "generated_by": "llm",
                "generation_status": "validated_red",
            }],
            "limitations": [],
        }),
        ".tallercito/docs/verification-report.md": "# Testability report\n",
    }
    return _member_zip(destination, members)


def _ftg_zip(destination: Path, *, finding_id: str) -> Path:
    members = {
        ".tallercito/tests/test_layer_import_x.py": "def test_layer_import():\n    assert True\n",
        ".tallercito/manifest.json": json.dumps({
            "schema_version": "1.1",
            "suite_id": "audit-4242-1a2b3c4d",
            "source_commit": "deadbeef",
            "verifications": [{
                "verification_id": "verification-001",
                "finding_id": finding_id,
                "test_path": "tests/test_layer_import_x.py",
                "test_name": "test_layer_import",
                "strategy": "static_ast",
                "covered_property": "layer",
                "target_components": ["src/x.py"],
                "generated_by": "llm",
                "generation_status": "validated_red",
            }],
            "limitations": [],
        }),
        ".tallercito/docs/verification-report.md": "# Finding-test report\n",
    }
    return _member_zip(destination, members)


def test_merge_assigns_groups_and_generators(tmp_path):
    groups = {"ftg-1": "modularity", "probe-1": "testability"}
    merged_path = tmp_path / "merged.zip"
    ftg = load_agent_zip(_ftg_zip(tmp_path / "ftg.zip", finding_id="ftg-1"),
                         "finding_test_generation", limitations=["ftg was here"])
    probe = load_agent_zip(_probe_zip(tmp_path / "probe.zip", finding_id="probe-1"),
                           "testability_probe", limitations=["probe was here"])
    manifest, _ = merge_suite_zips(merged_path, [ftg, probe], audit_id="4242",
                                   source_commit="a" * 40, verification_groups=groups)
    entries = {item["verification_id"]: item for item in manifest["verifications"]}
    assert entries["verification-001"]["generator"] == "finding_test_generation"
    assert entries["verification-001"]["group"] == "modularity"
    assert entries["probe-001"]["generator"] == "testability_probe"
    assert entries["probe-001"]["group"] == "testability"
    assert manifest["generator"] == "tallercito-verification-suite"
    assert "ftg was here" in manifest["limitations"] and "probe was here" in manifest["limitations"]
    with zipfile.ZipFile(merged_path) as archive:
        names = set(archive.namelist())
        assert ".tallercito/tests/test_layer_import_x.py" in names
        assert ".tallercito/tests/test_probe_check.py" in names


def test_merged_runner_supports_group_selection(tmp_path):
    groups = {"ftg-1": "modularity", "probe-1": "testability"}
    merged_path = tmp_path / "merged.zip"
    ftg = load_agent_zip(_ftg_zip(tmp_path / "ftg.zip", finding_id="ftg-1"), "finding_test_generation")
    probe = load_agent_zip(_probe_zip(tmp_path / "probe.zip", finding_id="probe-1"), "testability_probe")
    merge_suite_zips(merged_path, [ftg, probe], audit_id="4242",
                     source_commit="a" * 40, verification_groups=groups)

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "x.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "src" / "y.py").write_text("y = 1\n", encoding="utf-8")
    import zipfile as zipfile_module
    zipfile_module.ZipFile(merged_path).extractall(repo)
    # runner --only testability → expects violation (exit 1)
    cmd = [sys.executable, str(repo / ".tallercito" / "runner.py"), "--only", "testability"]
    import subprocess
    proc = subprocess.run(cmd, check=False, cwd=repo / ".tallercito", capture_output=True, text=True)
    assert proc.returncode == 1
    report = json.loads((repo / ".tallercito" / "results" / "report.json").read_text(encoding="utf-8"))
    assert report["selection"] == ["testability"]
    assert [v["verification_id"] for v in report["verifications"]] == ["probe-001"]

    cmd = [sys.executable, str(repo / ".tallercito" / "runner.py"), "--only", "modularity"]
    proc = subprocess.run(cmd, check=False, cwd=repo / ".tallercito", capture_output=True, text=True)
    assert proc.returncode == 0
    report = json.loads((repo / ".tallercito" / "results" / "report.json").read_text(encoding="utf-8"))
    assert [v["verification_id"] for v in report["verifications"]] == ["verification-001"]

    cmd = [sys.executable, str(repo / ".tallercito" / "runner.py"), "--list-groups"]
    proc = subprocess.run(cmd, check=False, cwd=repo / ".tallercito", capture_output=True, text=True)
    assert proc.returncode == 0
    assert set(proc.stdout.split()) == {"modularity", "testability"}


def test_validate_zip_supports_only_selection(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "x.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "src" / "y.py").write_text("y = 1\n", encoding="utf-8")
    groups = {"ftg-1": "modularity", "probe-1": "testability"}
    merged_path = tmp_path / "merged.zip"
    ftg = load_agent_zip(_ftg_zip(tmp_path / "ftg.zip", finding_id="ftg-1"), "finding_test_generation")
    probe = load_agent_zip(_probe_zip(tmp_path / "probe.zip", finding_id="probe-1"), "testability_probe")
    merge_suite_zips(merged_path, [ftg, probe], audit_id="4242",
                     source_commit="a" * 40, verification_groups=groups)

    class _Config:
        max_repo_copy_files = 1000
        max_repo_copy_bytes = 100_000_000
        max_test_run_seconds = 60

    report = zip_validate.validate_zip(merged_path, repo, None, _Config(), target_commit=None,
                                       only=["testability"])
    assert report["selection"] == ["testability"]
    assert [item["verification_id"] for item in report["verifications"]] == ["probe-001"]
    assert report["groups_present"] == ["modularity", "testability"]


def test_endpoint_create_with_zero_findings_builds_empty_suite(tmp_path, monkeypatch):
    """`create` with zero findings must produce a valid empty suite, never invent checks."""
    root = tmp_path / "artifacts"
    run = root / "run-1"
    run.mkdir(parents=True)
    (run / "report.json").write_text(json.dumps({
        "identification": {"repository_location": str(tmp_path), "audit_id": "4242",
                           "revisions": [{"commit": "a" * 40}]},
        "quality_results": {"findings": []},
    }), encoding="utf-8")
    monkeypatch.setattr(suite_api, "artifact_root", lambda: root)

    app = FastAPI()
    app.include_router(suite_api.router)
    with TestClient(app) as client:
        response = client.post("/run-1/verification-suite", json={"action": "create", "llm": "none"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["termination_reason"] == "no_findings"
    assert body["verifications"] == []
    assert body["zip_path"] and Path(body["zip_path"]).is_file()


def test_endpoint_create_runs_both_agents_and_merges(tmp_path, monkeypatch):
    """Both agents run offline (stubbed) and their suites merge into one ZIP."""
    from types import SimpleNamespace

    root = tmp_path / "artifacts"
    run = root / "run-2"
    run.mkdir(parents=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (run / "report.json").write_text(json.dumps({
        "identification": {"repository_location": str(repo), "audit_id": "4242",
                           "revisions": [{"commit": "a" * 40}]},
        "quality_results": {"findings": AUDIT_FIXTURE["findings"]},
    }), encoding="utf-8")
    monkeypatch.setattr(suite_api, "artifact_root", lambda: root)

    def fake_ftg_zip() -> Path:
        target = tmp_path / "ftg-agent.zip"
        return _ftg_zip(target, finding_id="ftg-1")

    def fake_probe_zip() -> Path:
        target = tmp_path / "probe-agent.zip"
        return _probe_zip(target, finding_id="probe-1")

    async def fake_run_ftg(run_id, adapted, findings, repo_path, output_dir, body, **kwargs):
        return SimpleNamespace(output_zip=str(fake_ftg_zip()), termination_reason="suite_packaged",
                               validation_status="validated", limitations=["ftg stub"],
                               verification_results=[SimpleNamespace(verification_id="verification-001",
                                                                     status="VIOLATION_PRESENT",
                                                                     summary="stub violation")])

    async def fake_run_probe(run_id, adapted, findings, repo_path, output_dir, body, **kwargs):
        return SimpleNamespace(output_zip=str(fake_probe_zip()), termination_reason="suite_packaged",
                               validation_status="validated", limitations=["probe stub"],
                               verifications=[SimpleNamespace(verification_id="probe-001",
                                                              outcome="violation_present",
                                                              llm_assessment="stub violation",
                                                              detail="stub violation")])

    monkeypatch.setattr(suite_api, "_run_finding_test_generation", fake_run_ftg)
    monkeypatch.setattr(suite_api, "_run_probe", fake_run_probe)

    app = FastAPI()
    app.include_router(suite_api.router)
    with TestClient(app) as client:
        response = client.post("/run-2/verification-suite", json={"action": "create", "llm": "provider",
            "config": {"model": {"provider": "google", "name": "suite-test-model"}, "api_key": "test-key"}})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["termination_reason"] == "suite_packaged"
    assert body["generators"] == ["finding_test_generation", "testability_probe"]
    counts = {entry["name"]: entry["count"] for entry in body["groups"]}
    assert counts == {"modularity": 1, "testability": 1}
    groups = {entry["verification_id"]: entry.get("group") for entry in body["verifications"]}
    assert groups["verification-001"] == "modularity"
    assert groups["probe-001"] == "testability"
    generators = {entry["verification_id"]: entry.get("generator") for entry in body["verifications"]}
    assert generators["verification-001"] == "finding_test_generation"
    assert generators["probe-001"] == "testability_probe"
    assert body["zip_path"] and Path(body["zip_path"]).is_file()
    with zipfile.ZipFile(body["zip_path"]) as archive:
        manifest = json.loads(archive.read(".tallercito/manifest.json"))
    assert manifest["generator"] == "tallercito-verification-suite"
    manifest_groups = {v["verification_id"]: v["group"] for v in manifest["verifications"]}
    assert manifest_groups == {"verification-001": "modularity", "probe-001": "testability"}
