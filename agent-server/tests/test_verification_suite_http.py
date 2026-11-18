"""HTTP integration for the verification-suite lifecycle through the real FastAPI wiring.

The LLM-backed agents are stubbed (same as elsewhere), but everything else is real:
artifact store on disk, git repo, ZIP packaging & merge, summary persistence and download.
"""
import io
import json
import subprocess
import zipfile
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from server.api import verification_suite as vs
from server.main import app

FINDING_FTG = {"id": "F-2", "criterion": {"id": "single-responsibility"}, "severity": "high"}
FINDING_PROBE = {"id": "F-1", "criterion": {"id": "test-isolation"}, "subcharacteristic": "testability"}
RUN_ID = "d" * 32


def _write_suite_zip(destination, generator_id: str, suite_id: str, verification_id: str) -> None:
    manifest = {
        "suite_id": suite_id,
        "verifications": [{
            "verification_id": verification_id,
            "finding_id": "F-1" if generator_id == "testability_probe" else "F-2",
            "rule_kind": "single-responsibility" if generator_id == "finding_test_generation" else None,
            "strategy": "static",
            "covered_property": "example",
            "target_components": ["a.py"],
            "generation_status": "generated",
            "generated_by": generator_id,
        }],
        "limitations": [],
    }
    with zipfile.ZipFile(destination, "w") as archive:
        archive.writestr(".tallercito/manifest.json", json.dumps(manifest))


@pytest.fixture
def suite_env(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "code.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    for args in (["init", "-q", "-b", "main"], ["add", "."], ["-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "fixture"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()

    artifacts = tmp_path / "artifacts"
    monkeypatch.setenv("VERAUD_ARTIFACT_DIR", str(artifacts))
    run_dir = artifacts / RUN_ID
    run_dir.mkdir(parents=True)
    report = {
        "identification": {
            "audit_id": "123",
            "repository_location": str(repo),
            "revisions": [{"commit": commit}],
        },
        "quality_results": {"findings": [FINDING_PROBE, FINDING_FTG]},
    }
    (run_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")

    async def fake_ftg(_run_id, _adapted, findings, _repo_path, output_dir, _body, trackers=None):
        assert findings == [FINDING_FTG]
        output_dir.mkdir(parents=True, exist_ok=True)
        destination = output_dir / "ftg" / "ftg.zip"
        destination.parent.mkdir(parents=True, exist_ok=True)
        _write_suite_zip(destination, "finding_test_generation", "ftg-suite", "verification-ftg-001")
        return SimpleNamespace(
            output_zip=str(destination), termination_reason="suite_packaged", validation_status="partial",
            limitations=[], verification_results=[SimpleNamespace(verification_id="verification-ftg-001", status="pass", summary="reproduced")],
        )

    async def fake_probe(_run_id, _adapted, findings, _repo_path, output_dir, _body, trackers=None):
        assert findings == [FINDING_PROBE]
        output_dir.mkdir(parents=True, exist_ok=True)
        destination = output_dir / "probe" / "probe.zip"
        destination.parent.mkdir(parents=True, exist_ok=True)
        _write_suite_zip(destination, "testability_probe", "probe-suite", "verification-probe-001")
        return SimpleNamespace(
            output_zip=str(destination), termination_reason="suite_packaged", validation_status="partial",
            limitations=[], verifications=[SimpleNamespace(verification_id="verification-probe-001", outcome="violation_present", llm_assessment="still reproducible", detail="")],
        )

    monkeypatch.setattr(vs, "_run_finding_test_generation", fake_ftg)
    monkeypatch.setattr(vs, "_run_probe", fake_probe)
    return SimpleNamespace(repo=repo, commit=commit, artifacts=artifacts, run_id=RUN_ID)


def test_verification_suite_http_lifecycle(suite_env):
    with TestClient(app) as client:
        assert client.get(f"/api/audits/{suite_env.run_id}/verification-suite").status_code == 404
        assert client.get(f"/api/audits/{suite_env.run_id}/verification-suite.zip").status_code == 404

        response = client.post(f"/api/audits/{suite_env.run_id}/verification-suite", json={"llm": "none"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True
        assert body["action"] == "create"
        assert body["termination_reason"] == "suite_packaged"
        assert set(body["generators"]) == {"finding_test_generation", "testability_probe"}
        assert {item["verification_id"] for item in body["verifications"]} == {"verification-ftg-001", "verification-probe-001"}
        probe_group = next(item for item in body["verifications"] if item["verification_id"] == "verification-probe-001")
        assert probe_group["status"] == "VIOLATION_PRESENT"
        assert probe_group["group"] == "testability"

        # The summary is persisted next to the artifacts; the GET route reflects it.
        stored = (suite_env.artifacts / suite_env.run_id / "verification-suite-summary.json").read_text(encoding="utf-8")
        persisted = json.loads(stored)
        assert persisted["run_id"] == suite_env.run_id
        listing = client.get(f"/api/audits/{suite_env.run_id}/verification-suite")
        assert listing.status_code == 200
        assert listing.json()["run_id"] == suite_env.run_id
        assert listing.json()["action"] == "create"

        # The unified ZIP is downloadable and contains the merged manifest.
        zip_response = client.get(f"/api/audits/{suite_env.run_id}/verification-suite.zip")
        assert zip_response.status_code == 200
        manifest = json.loads(zipfile.ZipFile(io.BytesIO(zip_response.content)).read(".tallercito/manifest.json"))
        assert {item["verification_id"] for item in manifest["verifications"]} == {"verification-ftg-001", "verification-probe-001"}


def test_verification_suite_requires_llm_config_or_explicit_none(suite_env):
    with TestClient(app) as client:
        rejected = client.post(f"/api/audits/{suite_env.run_id}/verification-suite", json={"llm": "provider"})
        assert rejected.status_code == 422
