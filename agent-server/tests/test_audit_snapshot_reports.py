import io
import zipfile
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_audit_report import assessment, evidence, finding, populated

from server.api.audits import router
from server.app.audit_service import AuditService, AuditState
from server.blackboard.impls.memory import MemoryBlackboard


def test_exported_snapshot_generates_json_and_word_without_a_live_audit():
    app = FastAPI()
    app.include_router(router)
    board = populated()
    board.publish_assessment(assessment("child", agent_id="component_adaptability", status="partial",
        details={"nested": {"validation_issues": ["input_preparation_unread"]}}))
    board.publish_finding(finding("pending", "insufficient_evidence"))
    service = AuditService(board)
    service._states["audit"] = AuditState(run_id="audit", invocation_id="manager", status="partial",
        view_url="/blackboard?run_id=audit", created_at=datetime.now(UTC))
    app.state.audit_service = service
    with TestClient(app) as client:
        saved = client.get("/api/audits/audit").json()
        child = next(a for a in saved["assessments"] if a["id"] == "child")
        assert child["details"]["nested"]["validation_issues"] == ["input_preparation_unread"]
        # Simulate using the downloaded file after all live state was lost.
        app.state.audit_service = AuditService(MemoryBlackboard())
        assert client.get("/api/audits/audit").status_code == 404
        response = client.post("/api/audits/reports/from-snapshot", json=saved)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        report = response.json()
        assert report["identification"]["audit_id"] == "audit"
        assert report["identification"]["status"] == "partial"
        assert report["executive_summary"]["findings"]["by_verification"] == {"verified": 1, "inconclusive": 1, "discarded": 0}
        assert report["consolidated_risks"]["risks"][0]["finding_ids"] == ["f1"]
        word = client.post("/api/audits/reports/from-snapshot.docx", json=saved)
        assert word.status_code == 200
        assert "attachment" in word.headers["content-disposition"]
        with zipfile.ZipFile(io.BytesIO(word.content)) as document:
            content = document.read("word/document.xml").decode()
            assert "domain/service.py" in content
            assert "Registro de construcci" in content
        generations = client.get("/api/audits/audit/report-generations").json()
        assert len(generations) == 2 and generations[0]["source_digest"] == generations[1]["source_digest"]
        generation_id = response.headers["x-report-generation-id"]
        saved_response = client.get(f"/api/audits/audit/report-generations/{generation_id}")
        assert saved_response.json() == report
        detached = app.state.audit_service.saved_report("audit", generation_id)
        detached.annexes_and_traceability.generation.source_snapshot["findings"].clear()
        assert client.get(f"/api/audits/audit/report-generations/{generation_id}").json() == report
        with pytest.raises(ValueError, match="overwrite"):
            app.state.audit_service.retain_report(app.state.audit_service.saved_report("audit", generation_id).model_copy(
                update={"executive_summary": detached.executive_summary.model_copy(update={"conclusion": "rewritten"})}))
        assert client.get(f"/api/audits/another-run/report-generations/{generation_id}").status_code == 404
        assert "source_snapshot" not in generations[0]
        assert app.state.audit_service.snapshot("audit") is None
        assert app.state.audit_service.blackboard.query_assessments("audit") == []


@pytest.mark.parametrize("invalid", ["malformed", "report_instead_of_snapshot", "mixed_runs", "duplicate", "missing_list",
    "invalid_investigation", "invalid_contribution", "invalid_question"])
def test_invalid_snapshot_is_rejected_before_generating_a_report(invalid):
    app = FastAPI()
    app.include_router(router)
    app.state.audit_service = AuditService(MemoryBlackboard())
    payload = {"run_id": "audit", "evidence": [evidence().model_dump(mode="json")], "findings": [], "assessments": []}
    if invalid == "mixed_runs":
        payload["evidence"][0]["run_id"] = "another"
    elif invalid == "duplicate":
        payload["evidence"] *= 2
    elif invalid == "missing_list":
        del payload["assessments"]
    elif invalid == "report_instead_of_snapshot":
        payload = {"schema_version": "1.0", "identification": {"audit_id": "audit"}}
    elif invalid == "invalid_investigation":
        payload["evidence"][0]["details"] = {"investigation": "not an object"}
    elif invalid == "invalid_contribution":
        payload["assessments"] = [assessment(consolidated_findings=({"id": "g", "contributions": [
            {"finding": None}]},)).model_dump(mode="json")]
    elif invalid == "invalid_question":
        payload["evidence"][0]["details"] = {"investigation": {"plan": {"hypotheses": [{"id": "h", "question": []}]}}}
    with TestClient(app) as client:
        response = (client.post("/api/audits/reports/from-snapshot", content="{", headers={"Content-Type": "application/json"})
            if invalid == "malformed" else client.post("/api/audits/reports/from-snapshot", json=payload))
        assert response.status_code == 422
