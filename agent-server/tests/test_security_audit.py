"""Security integration exercises real scanners through the shared audit lifecycle."""

import asyncio
import io
import zipfile
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from config.agents.budgets import TokenBudgetConfig
from server.agents.security.audit import SecurityAuditRequest
from server.api.schemas import ExecutionConfig
from server.app.audit_service import AuditService
from server.blackboard.impls.memory import MemoryBlackboard
from server.main import app
from server.services.audit_report_docx import render_audit_report_docx
from server.services.audit_report_snapshot import (
    BlackboardSnapshot,
    report_from_snapshot,
)

pytest_plugins = ["test_audits"]


def test_security_scanners_publish_portable_candidates_without_claiming_verification(audit_environment):
    root = audit_environment.root
    (root / "main.py").write_text('import pickle\npickle.loads(data)\npassword = "example-secret"\n', encoding="utf-8")
    (root / "package.json").write_text('{"dependencies": {"express": "1.0"}}', encoding="utf-8")
    model = audit_environment.model
    model.bind = lambda **kwargs: model
    model.ainvoke = AsyncMock(return_value='{"patch_code": "safe_call()", "explanation": "Revisar en contexto"}')

    async def execute():
        service = AuditService(MemoryBlackboard())
        state = service.start(str(root), SecurityAuditRequest(), ExecutionConfig(), "security")
        await service.wait(state.run_id)
        snapshot = service.snapshot(state.run_id)
        assert snapshot.status == "partial", snapshot
        assert snapshot.findings
        rules = {item.criterion_id for item in snapshot.findings}
        assert "SEC-PWD-003" in rules
        assert "CVE-2022-24999" in rules
        assert all(item.details["validation_status"] == "insufficient_evidence" for item in snapshot.findings)
        assert all(not item.details["security_finding"]["file_path"].startswith(str(root)) for item in snapshot.findings)
        assert "example-secret" not in snapshot.model_dump_json()
        assert "private-key" not in snapshot.model_dump_json()
        assessment = next(item for item in snapshot.assessments if item.agent_id == "security")
        assert assessment.consumption.model_calls > 0
        assert assessment.consumption.accounted_tokens > 0
        restored = BlackboardSnapshot.model_validate_json(snapshot.model_dump_json())
        report = await report_from_snapshot(restored)
        security = next(item for item in report.quality_results.attributes if item.id == "security")
        assert security.subcharacteristics
        with zipfile.ZipFile(io.BytesIO(render_audit_report_docx(report))) as document:
            assert b"DAST" in document.read("word/document.xml")
        await service.aclose()

    asyncio.run(execute())


def test_cancellation_keeps_the_candidate_and_closes_provider(audit_environment):
    (audit_environment.root / "main.py").write_text('password = "example-secret"\n', encoding="utf-8")
    model = audit_environment.model
    model.bind = lambda **kwargs: model

    async def execute():
        entered = asyncio.Event()

        async def blocked(prompt):
            entered.set()
            await asyncio.Event().wait()

        model.ainvoke = blocked
        service = AuditService(MemoryBlackboard())
        state = service.start(str(audit_environment.root), SecurityAuditRequest(), ExecutionConfig(), "security")
        await asyncio.wait_for(entered.wait(), 5)
        assert service.snapshot(state.run_id).evidence
        await service.cancel(state.run_id)
        snapshot = service.snapshot(state.run_id)
        assert snapshot.status == "cancelled"
        assert snapshot.findings[0].details["security_finding"]["remediation"]["interrupted"]
        assert snapshot.assessments[0].termination_reason == "security_interrupted"
        assert snapshot.assessments[0].consumption.estimated_tokens > 0
        await service.aclose()

    asyncio.run(execute())
    audit_environment.async_client.aclose.assert_awaited_once()


def test_token_budget_falls_back_without_losing_detection(audit_environment):
    (audit_environment.root / "main.py").write_text('password = "example-secret"\n', encoding="utf-8")
    model = audit_environment.model
    model.bind = lambda **kwargs: model
    model.ainvoke = AsyncMock()

    async def execute():
        service = AuditService(MemoryBlackboard())
        state = service.start(str(audit_environment.root), SecurityAuditRequest(), ExecutionConfig(), "security",
            audit_budget=TokenBudgetConfig(max_total_tokens=1000))
        await service.wait(state.run_id)
        snapshot = service.snapshot(state.run_id)
        assert snapshot.status == "partial"
        assert snapshot.findings[0].details["security_finding"]["remediation"]["llm_generated"] is False
        model.ainvoke.assert_not_awaited()
        await service.aclose()

    asyncio.run(execute())


def test_http_selects_security_and_reconstructs_its_export_without_the_repository(audit_environment):
    model = audit_environment.model
    model.bind = lambda **kwargs: model
    model.ainvoke = AsyncMock()
    with TestClient(app) as client:
        started = client.post("/api/audits", json={"repository_path": str(audit_environment.root),
            "security_request": {"objective": "Inspeccionar seguridad"}, "agent_config": "security"})
        assert started.status_code == 202
        run_id = started.json()["run_id"]
        client.portal.call(app.state.audit_service.wait, run_id)
        exported = client.get(f"/api/audits/{run_id}")
        assert exported.status_code == 200
        assert exported.json()["assessments"][0]["quality_attribute"] == "security"
        (audit_environment.root / "main.py").unlink()
        restored = client.post("/api/audits/reports/from-snapshot", json=exported.json())
        assert restored.status_code == 200, restored.text
        assert "Inspeccionar seguridad" in restored.text
        word = client.post("/api/audits/reports/from-snapshot.docx", json=exported.json())
        assert word.status_code == 200, word.text
        assert word.content.startswith(b"PK")
