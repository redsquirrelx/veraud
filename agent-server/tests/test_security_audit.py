"""Security integration exercises real scanners through the shared audit lifecycle."""

import asyncio
import io
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from config.agents.budgets import TokenBudgetConfig
from config.agents.catalog import describe_agent_config, validate_agent_config
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


@pytest.mark.parametrize("local, shared, reason", [(100_000, 1000, "audit_token_limit"), (1000, 100_000, "token_limit")])
def test_token_budget_falls_back_without_losing_detection(audit_environment, local, shared, reason):
    (audit_environment.root / "main.py").write_text('password = "example-secret"\n', encoding="utf-8")
    model = audit_environment.model
    model.bind = lambda **kwargs: model
    model.ainvoke = AsyncMock()

    async def execute():
        service = AuditService(MemoryBlackboard())
        state = service.start(str(audit_environment.root), SecurityAuditRequest(), ExecutionConfig(), "security",
            audit_budget=TokenBudgetConfig(max_total_tokens=shared), security_config={"max_total_tokens": local})
        await service.wait(state.run_id)
        snapshot = service.snapshot(state.run_id)
        assert snapshot.status == "partial"
        assert snapshot.assessments[0].termination_reason == reason
        assert "presupuesto" in snapshot.execution_issues[0].explanation
        assert snapshot.findings[0].details["security_finding"]["remediation"]["llm_generated"] is False
        model.ainvoke.assert_not_awaited()
        await service.aclose()

    asyncio.run(execute())


def test_http_accepts_the_common_security_defaults_and_records_the_effective_policy(audit_environment):
    model = audit_environment.model
    model.bind = lambda **kwargs: model
    with TestClient(app) as client:
        started = client.post("/api/audits", json={
            "repository_path": str(audit_environment.root), "agent_config": "dummy", "attributes": ["security"],
            "agent_defaults": {"max_context_characters": 20_000_000, "max_total_tokens": 80_000_000,
                "max_model_calls": 20, "max_tool_calls": 30},
            "audit_budget": {"max_total_tokens": 3_000_000_000},
        })
        assert started.status_code == 202, started.text
        run_id = started.json()["run_id"]
        client.portal.call(app.state.audit_service.wait, run_id)
        snapshot = client.get(f"/api/audits/{run_id}").json()
        assert snapshot["status"] == "completed"
        analysis = snapshot["assessments"][0]["details"]["security_analysis"]
        policy = analysis["effective_config"]
        assert policy["max_context_characters"] == 20_000_000
        assert policy["max_total_tokens"] == 80_000_000
        assert policy["max_model_calls"] == 20
        assert policy["max_tool_calls"] == 30
        assert analysis["audit_token_limit"] == 3_000_000_000
        assert "private-key" not in str(snapshot)


def test_security_specific_call_limit_overrides_common_defaults_and_preserves_all_candidates(audit_environment):
    (audit_environment.root / "main.py").write_text('password = "example-secret"\n' * 6, encoding="utf-8")
    model = audit_environment.model
    model.bind = Mock(return_value=model)
    model.ainvoke = AsyncMock(return_value='{"patch_code": "safe()", "explanation": "Revisar contexto"}')
    with TestClient(app) as client:
        started = client.post("/api/audits", json={"repository_path": str(audit_environment.root),
            "attributes": ["security"], "agent_defaults": {"max_model_calls": 20, "max_tool_calls": 30},
            "security_config": {"max_model_calls": 4, "max_output_tokens": 256,
                "provider_rate_limits": {"requests_per_minute": None}},
        })
        assert started.status_code == 202, started.text
        run_id = started.json()["run_id"]
        client.portal.call(app.state.audit_service.wait, run_id)
        snapshot = client.get(f"/api/audits/{run_id}").json()
        assert snapshot["status"] == "partial"
        assert len(snapshot["findings"]) == 6
        assert snapshot["assessments"][0]["termination_reason"] == "model_call_limit"
        assert model.ainvoke.await_count == 4
        model.bind.assert_called_once_with(max_tokens=256)
        policy = snapshot["assessments"][0]["details"]["security_analysis"]["effective_config"]
        assert policy["max_tool_calls"] == 30
        assert policy["provider_rate_limits"]["requests_per_minute"] is None
        assert policy["provider_rate_limits"]["tokens_per_minute"] is not None


@pytest.mark.parametrize("context, status, calls", [(4000, "partial", 0), (20_000_000, "completed", 1)])
def test_security_context_limit_bounds_the_actual_provider_prompt(audit_environment, context, status, calls):
    (audit_environment.root / "main.py").write_text("pickle.loads(payload) # " + "x" * 6000 + "\n", encoding="utf-8")
    model = audit_environment.model
    model.bind = lambda **kwargs: model
    model.ainvoke = AsyncMock(return_value='{"patch_code": "safe()", "explanation": "Revisar contexto"}')
    with TestClient(app) as client:
        started = client.post("/api/audits", json={"repository_path": str(audit_environment.root),
            "attributes": ["security"], "security_config": {"max_context_characters": context}})
        assert started.status_code == 202, started.text
        run_id = started.json()["run_id"]
        client.portal.call(app.state.audit_service.wait, run_id)
        snapshot = client.get(f"/api/audits/{run_id}").json()
        assert snapshot["status"] == status
        assert model.ainvoke.await_count == calls
        assert snapshot["assessments"][0]["termination_reason"] == (
            "context_limit" if calls == 0 else "security_scope_completed")


def test_security_catalog_keeps_developer_controls_out_of_the_user_panel():
    user = describe_agent_config("security")
    developer = describe_agent_config("security", level="developer")
    assert "max_total_tokens" in user["config_schema"]["properties"]
    for name in ("max_scan_files", "max_source_lines", "max_context_characters", "max_model_calls", "max_retrieved_characters"):
        assert name not in user["config_schema"]["properties"]
        assert name in developer["config_schema"]["properties"]
        with pytest.raises(ValueError):
            validate_agent_config("security", {name: 8})


@pytest.mark.parametrize("overrides", [{"max_scan_files": 501}, {"max_model_calls": 101},
    {"max_source_lines": 0}, {"max_retrieved_characters": 0}, {"timeout_seconds": -1}, {"api_key": "must-not-be-a-control"},
    {"prompts": {"unused_node": "ignored"}}])
def test_security_overrides_reject_invalid_or_ineffective_controls_before_execution(audit_environment, overrides):
    with TestClient(app) as client:
        result = client.post("/api/audits", json={"repository_path": str(audit_environment.root),
            "attributes": ["security"], "security_config": overrides})
        assert result.status_code == 422
        assert not app.state.audit_service._states
    audit_environment.factory.assert_not_called()


@pytest.mark.parametrize("controls, status, end_line", [
    ({"max_source_lines": 1}, "completed", 2),
    ({"max_source_lines": 10}, "completed", 2),
    ({"max_tool_calls": 0}, "partial", None),
])
def test_security_transport_controls_bound_the_actual_source_reads(audit_environment, controls, status, end_line):
    model = audit_environment.model
    model.bind = lambda **kwargs: model
    with TestClient(app) as client:
        started = client.post("/api/audits", json={"repository_path": str(audit_environment.root),
            "attributes": ["security"], "security_config": controls})
        assert started.status_code == 202, started.text
        run_id = started.json()["run_id"]
        client.portal.call(app.state.audit_service.wait, run_id)
        snapshot = client.get(f"/api/audits/{run_id}").json()
        assert snapshot["status"] == status
        sources = [item for item in snapshot["evidence"] if item["kind"] == "source"]
        assert (max(item["end_line"] for item in sources) if sources else None) == end_line


@pytest.mark.parametrize("case, expected", [
    ("files", "security_file_limit"),
    ("tools", "tool_call_limit"),
    ("read_failure", "security_source_read_failed"),
    ("empty_scope", "security_empty_scope"),
    ("provider_failure", "security_remediation_fallback"),
])
def test_real_security_incompleteness_retains_specific_reasons(audit_environment, monkeypatch, case, expected):
    root = audit_environment.root
    overrides = {}
    request = SecurityAuditRequest()
    if case == "files":
        (root / "extra.py").write_text("value = 1\n", encoding="utf-8")
        overrides = {"max_scan_files": 1}
    elif case == "tools":
        (root / "extra.py").write_text("value = 1\n", encoding="utf-8")
        overrides = {"max_tool_calls": 1}
    elif case == "read_failure":
        monkeypatch.setattr(audit_service.RepositoryToolset, "execute",
            lambda *args, **kwargs: SimpleNamespace(error=True, evidence=()))
    elif case == "empty_scope":
        request = SecurityAuditRequest(targets=["missing.py"])
    else:
        (root / "main.py").write_text('password = "example-secret"\n', encoding="utf-8")
    model = audit_environment.model
    model.bind = lambda **kwargs: model
    model.ainvoke = AsyncMock(return_value="invalid structured response")

    async def execute():
        service = AuditService(MemoryBlackboard())
        state = service.start(str(root), request, ExecutionConfig(), "security", security_config=overrides)
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


@pytest.mark.parametrize("tool_limit, complete", [(20, True), (2, False)])
def test_security_reassembles_ranges_and_links_late_findings(audit_environment, tool_limit, complete):
    lines = ["value = 1", "", "value = 2", "", "pickle.loads(payload)", "value = 3", "value = 4"]
    (audit_environment.root / "main.py").write_text("\n".join(lines), encoding="utf-8")
    model = audit_environment.model
    model.bind = lambda **kwargs: model
    model.ainvoke = AsyncMock(return_value='{"patch_code": "safe()", "explanation": "Revisar"}')
    with TestClient(app) as client:
        started = client.post("/api/audits", json={"repository_path": str(audit_environment.root),
            "attributes": ["security"], "security_config": {"max_source_lines": 2, "max_tool_calls": tool_limit}})
        assert started.status_code == 202, started.text
        run_id = started.json()["run_id"]
        client.portal.call(app.state.audit_service.wait, run_id)
        snapshot = client.get(f"/api/audits/{run_id}").json()
        assessment = snapshot["assessments"][0]
        coverage = assessment["coverage"]["files"]["main.py"]
        assert coverage["complete"] is complete
        assert snapshot["status"] == ("completed" if complete else "partial")
        if complete:
            assert coverage["pending_ranges"] == []
            finding = next(item for item in snapshot["findings"] if item["criterion_id"] == "DESER-001")
            assert finding["details"]["security_finding"]["line_number"] == 5
            refs = [item for item in snapshot["evidence"] if item["id"] in finding["evidence_ids"]]
            assert [(ref["start_line"], ref["end_line"]) for ref in refs] == [(5, 6)]
        else:
            assert coverage["pending_ranges"] == [{"start_line": 5, "end_line": 7}]
            assert "security_source_truncated" in assessment["details"]["security_analysis"]["incomplete_reasons"]
            assert len(coverage["read_ranges"]) == 2


def test_security_reconstructs_manifests_before_dependency_scanning(audit_environment):
    (audit_environment.root / "package.json").write_text(
        '{\n  "name": "example",\n  "dependencies": {\n    "express": "1.0"\n  }\n}\n', encoding="utf-8")
    model = audit_environment.model
    model.bind = lambda **kwargs: model
    model.ainvoke = AsyncMock(return_value='{"patch_code": "safe()", "explanation": "Revisar"}')
    with TestClient(app) as client:
        started = client.post("/api/audits", json={"repository_path": str(audit_environment.root),
            "attributes": ["security"], "security_request": {"targets": ["package.json"]},
            "security_config": {"max_source_lines": 2}})
        assert started.status_code == 202, started.text
        run_id = started.json()["run_id"]
        client.portal.call(app.state.audit_service.wait, run_id)
        snapshot = client.get(f"/api/audits/{run_id}").json()
        assert snapshot["status"] == "completed"
        finding = next(item for item in snapshot["findings"] if item["criterion_id"] == "CVE-2022-24999")
        assert len(finding["evidence_ids"]) == 3


def test_security_retries_smaller_ranges_when_serialized_response_is_too_large(audit_environment):
    # Source fits its character cap; JSON escaping exceeds the tool response cap.
    audit_environment.model.bind = lambda **kwargs: audit_environment.model
    (audit_environment.root / "main.py").write_text(('value = "' + '\\' * 2500 + '"\n') * 4, encoding="utf-8")
    with TestClient(app) as client:
        started = client.post("/api/audits", json={"repository_path": str(audit_environment.root),
            "attributes": ["security"]})
        assert started.status_code == 202, started.text
        run_id = started.json()["run_id"]
        client.portal.call(app.state.audit_service.wait, run_id)
        snapshot = client.get(f"/api/audits/{run_id}").json()
        assert snapshot["status"] == "completed"
        assessment = snapshot["assessments"][0]
        coverage = assessment["coverage"]["files"]["main.py"]
        assert coverage["complete"]
        assert len(coverage["read_ranges"]) > 1
        assert assessment["consumption"]["tool_calls"] > len(coverage["read_ranges"])
        errors = assessment["details"]["security_analysis"]["read_errors"]
        assert errors and all(error["retrying"] for error in errors)


@pytest.mark.parametrize("content, reason, code", [
    ("#" + "x" * 13000, "security_source_line_limit", "source_limit_exceeded"),
    ('value = "' + '\\' * 9000 + '"', "security_source_response_limit", "response_limit_exceeded"),
    (("#" + "x" * 8000 + "\n") * 25, "security_retrieval_limit", "content_budget_exhausted"),
], ids=["source-line-limit", "response-limit", "retrieval-limit"])
def test_security_read_errors_expose_real_tool_cause_and_resource_usage(audit_environment, content, reason, code):
    audit_environment.model.bind = lambda **kwargs: audit_environment.model
    (audit_environment.root / "main.py").write_text(content, encoding="utf-8")
    with TestClient(app) as client:
        started = client.post("/api/audits", json={"repository_path": str(audit_environment.root),
            "attributes": ["security"], "security_config": {"max_source_lines": 1, "max_tool_calls": 200}})
        assert started.status_code == 202, started.text
        run_id = started.json()["run_id"]
        client.portal.call(app.state.audit_service.wait, run_id)
        snapshot = client.get(f"/api/audits/{run_id}").json()
        assert snapshot["status"] == "partial"
        assessment = snapshot["assessments"][0]
        assert assessment["termination_reason"] == reason
        error = assessment["details"]["security_analysis"]["read_errors"][-1]
        assert error["code"] == code
        assert error["path"] == "main.py"
        assert error["tool_call_id"]
        assert not error["retrying"]
        assert error["tool_calls"] == assessment["consumption"]["tool_calls"]
        assert error["end_line"] == error["start_line"]
        coverage = assessment["coverage"]["files"]["main.py"]
        assert not coverage["complete"]
        assert coverage["pending_ranges"][0]["start_line"] == error["start_line"]
        issue = snapshot["execution_issues"][0]
        assert issue["termination_reason"] == reason
        assert any(f"code={code}" in item and "main.py:" in item for item in issue["diagnostics"])
        assert content not in str(error)


def test_security_can_complete_large_sources_with_an_explicit_retrieval_budget(audit_environment):
    audit_environment.model.bind = lambda **kwargs: audit_environment.model
    (audit_environment.root / "main.py").write_text(("#" + "x" * 8000 + "\n") * 25, encoding="utf-8")
    with TestClient(app) as client:
        started = client.post("/api/audits", json={"repository_path": str(audit_environment.root),
            "attributes": ["security"], "security_config": {"max_source_lines": 1,
                "max_tool_calls": 200, "max_retrieved_characters": 300000}})
        assert started.status_code == 202, started.text
        run_id = started.json()["run_id"]
        client.portal.call(app.state.audit_service.wait, run_id)
        snapshot = client.get(f"/api/audits/{run_id}").json()
        assert snapshot["status"] == "completed"
        assessment = snapshot["assessments"][0]
        assert assessment["coverage"]["files"]["main.py"]["complete"]
        assert len(assessment["coverage"]["files"]["main.py"]["read_ranges"]) == 25
        assert assessment["details"]["security_analysis"]["read_errors"] == []
        assert assessment["details"]["security_analysis"]["effective_config"]["max_retrieved_characters"] == 300000


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
