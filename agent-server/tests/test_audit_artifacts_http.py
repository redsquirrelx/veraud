"""Artifact end-to-end integration: production artifact publishing is round-tripped
through the HTTP layer — the compact manifest is served only after it reconciles
byte-for-byte against the stored files, and a corrupted store is refused."""
import asyncio

from fastapi.testclient import TestClient

from server.app.audit_artifacts import publish_audit_artifacts
from server.main import app
from server.reporting.docx import render_audit_report_docx
from server.reporting.snapshot import BlackboardSnapshot, report_from_snapshot

pytest_plugins = ["test_audits"]

RUN_ID = "e" * 32


def test_published_artifacts_roundtrip_over_http_and_enforce_integrity(tmp_path, monkeypatch):
    monkeypatch.setenv("VERAUD_ARTIFACT_DIR", str(tmp_path / "audit-artifacts"))

    async def publish():
        snapshot = BlackboardSnapshot.model_validate({"run_id": RUN_ID, "assessments": [], "findings": [], "evidence": []})
        report = await report_from_snapshot(snapshot)
        document = render_audit_report_docx(report)
        return publish_audit_artifacts(RUN_ID, report, document)

    manifest = asyncio.run(publish())

    artifact_dir = tmp_path / "audit-artifacts" / RUN_ID
    assert (artifact_dir / "report.json").stat().st_size == manifest.report_bytes
    assert (artifact_dir / "report.docx").stat().st_size == manifest.docx_bytes
    assert (artifact_dir / "manifest.json").is_file()
    assert len(manifest.sections) == 10

    with TestClient(app) as client:
        response = client.get(f"/api/audits/{RUN_ID}/artifacts")
        assert response.status_code == 200
        served = response.json()
        assert served == {"format": manifest.format, "run_id": RUN_ID,
                          "report_bytes": manifest.report_bytes, "docx_bytes": manifest.docx_bytes,
                          "sections": list(manifest.sections)}

        # Corrupting a stored file makes integrity verification fail and the endpoint refuse to serve.
        with open(artifact_dir / "report.json", "ab") as handle:
            handle.write(b"corrupt")
        assert client.get(f"/api/audits/{RUN_ID}/artifacts").status_code == 404

        # A completely foreign run never escapes as a valid artifact.
        assert client.get(f"/api/audits/{'f' * 32}/artifacts").status_code == 404
