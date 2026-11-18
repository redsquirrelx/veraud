"""Verification-suite generators are wrapped in stable LangSmith spans without changing logic."""

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api import verification_suite as suite
from server.config import tracing as tracing_config


def _mk_zip(path: Path, generator: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        manifest = {"schema_version": "1.1", "generator": generator,
                    "generator_version": "0.1", "audit_id": "7",
                    "source_commit": "a" * 40, "suite_id": f"suite-{generator}",
                    "runner": "uv", "root_layout": ".tallercito",
                    "language": "python", "framework": "pytest",
                    "verifications": [], "limitations": []}
        archive.writestr(".tallercito/manifest.json", json.dumps(manifest))


def test_create_spans_wrap_both_generator_coroutines(tmp_path, monkeypatch):
    run_id = "tracing-test"
    root = tmp_path / run_id
    root.mkdir()
    (root / "report.json").write_text(json.dumps({
        "identification": {"repository_location": str(tmp_path), "audit_id": "7",
                           "revisions": [{"commit": "a" * 40}]},
        "quality_results": {"findings": []},
    }), encoding="utf-8")
    monkeypatch.setattr(suite, "artifact_root", lambda: tmp_path)
    monkeypatch.setattr(suite, "split_findings", lambda findings: {
        "ftg": [{"id": "f-1", "subcharacteristic": "isolation"}],
        "probe": [{"id": "p-1", "subcharacteristic": "testability"}],
        "unsupported": [],
    })
    artifacts = tmp_path / "sentinels"
    artifacts.mkdir()
    _mk_zip(artifacts / "ftg.zip", "finding_test_generation")
    _mk_zip(artifacts / "probe.zip", "testability_probe")

    async def _sentinel(output_zip):
        return SimpleNamespace(output_zip=str(output_zip), verification_results=[],
                               validation_status="generated",
                               limitations=[], ok=True, termination_reason="suite_packaged")

    monkeypatch.setattr(suite, "_run_finding_test_generation", lambda *a, **kw: _sentinel(artifacts / "ftg.zip"))
    monkeypatch.setattr(suite, "_run_probe", lambda *a, **kw: _sentinel(artifacts / "probe.zip"))

    spans = []

    async def recorder(coro, *, name, **metadata):
        spans.append((name, metadata))
        return await coro

    monkeypatch.setattr(suite, "traced_agent_run", recorder)
    app = FastAPI()
    app.include_router(suite.router)
    with TestClient(app) as client:
        response = client.post(f"/{run_id}/verification-suite", json={"action": "create", "llm": "none"})
        assert response.status_code == 200
    spans_by_name = dict(spans)
    assert list(spans_by_name) == ["verification_suite/finding_test_generation",
                                   "verification_suite/testability_probe"]
    for metadata in spans_by_name.values():
        assert metadata["run_id"] == run_id
        assert metadata["audit_id"] == "7"


def test_no_key_returns_coroutine_result_without_wrapping(monkeypatch):
    async def coro():
        return "ran"

    monkeypatch.setattr(tracing_config, "get_tracing_settings",
                        lambda: SimpleNamespace(enabled=False))
    monkeypatch.setattr(tracing_config, "setup", lambda: None)
    assert tracing_config.is_enabled() is False

    import asyncio

    assert asyncio.run(tracing_config.traced_agent_run(coro(), name="smoke")) == "ran"
