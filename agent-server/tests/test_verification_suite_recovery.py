"""Attempt identity must survive HTTP and artifact publication for reconciliation."""

import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api import verification_suite as suite


def test_create_publishes_attempt_identity_without_running_repository(tmp_path, monkeypatch):
    run_id = "recovery-test"
    root = tmp_path / run_id
    root.mkdir()
    (root / "report.json").write_text(json.dumps({
        "identification": {"repository_location": str(tmp_path), "audit_id": "1"},
        "quality_results": {"findings": []},
    }), encoding="utf-8")
    monkeypatch.setattr(suite, "artifact_root", lambda: tmp_path)

    class Agent:
        def __init__(self, config, llm_client):
            assert not config.allow_local_unsafe_execution
            assert llm_client is None

        async def run(self, request):
            return SimpleNamespace(output_zip=None, specs=[], verification_results=[],
                                   validation_status="generated", limitations=[], ok=True,
                                   termination_reason="suite_packaged")

    monkeypatch.setattr(suite, "FindingTestGenerationAgent", Agent)
    app = FastAPI()
    app.include_router(suite.router)
    with TestClient(app) as client:
        response = client.post(f"/{run_id}/verification-suite", json={
            "action": "create", "llm": "none", "allow_execution": False,
            "attempt_id": "attempt-current",
        })
        assert response.status_code == 200
        assert response.json()["attempt_id"] == "attempt-current"
        assert client.get(f"/{run_id}/verification-suite").json()["attempt_id"] == "attempt-current"
    persisted = json.loads((root / "verification-suite-summary.json").read_text(encoding="utf-8"))
    assert persisted["attempt_id"] == "attempt-current"
