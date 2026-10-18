"""Security integration exercises real scanners through the shared audit lifecycle."""

import asyncio
import io
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from config.agents.budgets import TokenBudgetConfig
from server.agents.maintainability.manager import MaintainabilityRequest
from server.agents.security.audit import SecurityAuditRequest
from server.api.schemas import ExecutionConfig
from server.app import audit_service
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
        assert snapshot.status == "completed", snapshot
        assert not snapshot.execution_issues
        assert snapshot.findings
        rules = {item.criterion_id for item in snapshot.findings}
        assert "SEC-PWD-003" in rules
        assert "CVE-2022-24999" in rules
        assert all(item.details["validation_status"] == "insufficient_evidence" for item in snapshot.findings)
        assert all(not item.details["security_finding"]["file_path"].startswith(str(root)) for item in snapshot.findings)
        assert "example-secret" not in snapshot.model_dump_json()
        assert "private-key" not in snapshot.model_dump_json()
        assessment = next(item for item in snapshot.assessments if item.agent_id == "security")
        assert assessment.status == "completed"
        assert assessment.termination_reason == "security_scope_completed"
        assert assessment.details["security_analysis"]["incomplete_reasons"] == []
        assert assessment.limitations
        assert assessment.consumption.model_calls > 0
        assert assessment.consumption.accounted_tokens > 0
        restored = BlackboardSnapshot.model_validate_json(snapshot.model_dump_json())
        report = await report_from_snapshot(restored)
        security = next(item for item in report.quality_results.attributes if item.id == "security")
        assert security.subcharacteristics
        assert all(item.verification_status == "inconclusive" for item in report.quality_results.findings)
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
        assert snapshot.assessments[0].termination_reason == "audit_token_limit"
        assert "presupuesto compartido" in snapshot.execution_issues[0].explanation
        assert snapshot.findings[0].details["security_finding"]["remediation"]["llm_generated"] is False
        model.ainvoke.assert_not_awaited()
        await service.aclose()

    asyncio.run(execute())


@pytest.mark.parametrize("case, expected", [
    ("files", "security_file_limit"),
    ("tools", "tool_call_limit"),
    ("truncated", "security_source_truncated"),
    ("read_failure", "security_source_read_failed"),
    ("empty_scope", "security_empty_scope"),
    ("provider_failure", "security_remediation_fallback"),
])
def test_real_security_incompleteness_retains_specific_reasons(audit_environment, monkeypatch, case, expected):
    root = audit_environment.root
    config = audit_service.SecurityAuditConfig()
    request = SecurityAuditRequest()
    if case == "files":
        (root / "extra.py").write_text("value = 1\n", encoding="utf-8")
        config = config.model_copy(update={"max_scan_files": 1})
    elif case == "tools":
        (root / "extra.py").write_text("value = 1\n", encoding="utf-8")
        config = config.model_copy(update={"max_tool_calls": 1})
    elif case == "truncated":
        (root / "main.py").write_text("value = 1\n" * 200, encoding="utf-8")
    elif case == "read_failure":
        monkeypatch.setattr(audit_service.RepositoryToolset, "execute",
            lambda *args, **kwargs: SimpleNamespace(error=True, evidence=()))
    elif case == "empty_scope":
        request = SecurityAuditRequest(targets=["missing.py"])
    else:
        (root / "main.py").write_text('password = "example-secret"\n', encoding="utf-8")
    monkeypatch.setattr(audit_service, "SecurityAuditConfig", lambda: config)
    model = audit_environment.model
    model.bind = lambda **kwargs: model
    model.ainvoke = AsyncMock(return_value="invalid structured response")

    async def execute():
        service = AuditService(MemoryBlackboard())
        state = service.start(str(root), request, ExecutionConfig(), "security")
        await service.wait(state.run_id)
        snapshot = service.snapshot(state.run_id)
        assert snapshot.status == "partial", snapshot
        assessment = snapshot.assessments[0]
        assert assessment.termination_reason == expected
        assert expected in assessment.details["security_analysis"]["incomplete_reasons"]
        assert assessment.details["security_analysis"]["incidents"]
        assert snapshot.execution_issues[0].termination_reason == expected
        assert not snapshot.execution_issues[0].explanation.startswith("Motivo registrado")
        await service.aclose()

    asyncio.run(execute())


def test_joint_cancellation_stops_both_attributes_and_retains_the_shared_analysis(audit_environment, monkeypatch):
    (audit_environment.root / "main.py").write_text('password = "example-secret"\n', encoding="utf-8")
    model = audit_environment.model
    model.bind = lambda **kwargs: model

    async def execute():
        manager_entered, security_entered = asyncio.Event(), asyncio.Event()
        stopped = set()

        async def block(attribute, entered):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.add(attribute)

        manager = SimpleNamespace(run=lambda *args: block("maintainability", manager_entered))
        monkeypatch.setattr(audit_service, "MaintainabilityManagerAgent", Mock(return_value=manager))
        model.ainvoke = lambda prompt: block("security", security_entered)
        service = AuditService(MemoryBlackboard())
        state = service.start(str(audit_environment.root), MaintainabilityRequest(), ExecutionConfig(), "offline",
            attributes=["maintainability", "security"])
        await asyncio.wait_for(asyncio.gather(manager_entered.wait(), security_entered.wait()), 5)
        await service.cancel(state.run_id)
        snapshot = service.snapshot(state.run_id)
        assert snapshot.status == "cancelled"
        assert stopped == {"maintainability", "security"}
        assert snapshot.findings
        context = next(item.details["audit_context"] for item in snapshot.evidence if "audit_context" in item.details)
        assert context["requested_attributes"] == ["maintainability", "security"]
        assert {item.run_id for item in snapshot.evidence} == {state.run_id}
        await service.aclose()

    asyncio.run(execute())
    audit_environment.async_client.aclose.assert_awaited_once()


@pytest.mark.parametrize("attributes", [None, ["maintainability", "security"]])
def test_http_selects_security_and_reconstructs_its_export_without_the_repository(audit_environment, monkeypatch, attributes):
    model = audit_environment.model
    model.bind = lambda **kwargs: model
    model.ainvoke = AsyncMock()
    manager = SimpleNamespace(run=AsyncMock(return_value=SimpleNamespace(status="complete")))
    monkeypatch.setattr(audit_service, "MaintainabilityManagerAgent", Mock(return_value=manager))
    with TestClient(app) as client:
        started = client.post("/api/audits", json={"repository_path": str(audit_environment.root),
            "security_request": {"objective": "Inspeccionar seguridad"}, "agent_config": "security",
            **({"attributes": attributes} if attributes else {})})
        assert started.status_code == 202
        run_id = started.json()["run_id"]
        client.portal.call(app.state.audit_service.wait, run_id)
        exported = client.get(f"/api/audits/{run_id}")
        assert exported.status_code == 200
        assert exported.json()["status"] == "completed"
        assert exported.json()["execution_issues"] == []
        assert exported.json()["assessments"][0]["quality_attribute"] == "security"
        (audit_environment.root / "main.py").unlink()
        restored = client.post("/api/audits/reports/from-snapshot", json=exported.json())
        assert restored.status_code == 200, restored.text
        assert "Inspeccionar seguridad" in restored.text
        word = client.post("/api/audits/reports/from-snapshot.docx", json=exported.json())
        assert word.status_code == 200, word.text
        assert word.content.startswith(b"PK")
        assert manager.run.await_count == (1 if attributes else 0)
