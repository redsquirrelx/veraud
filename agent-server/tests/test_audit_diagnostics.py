from datetime import UTC, datetime

from test_audit_report import assessment, build

from server.app.audit_service import AuditService, AuditState
from server.blackboard.impls.memory import MemoryBlackboard
from server.services.audit_diagnostics import execution_diagnostics


def incomplete_board():
    board = MemoryBlackboard()
    provider = "evaluate_evidence: provider_request: GoogleInvalidRequestError; http_status=400, request_field=not_reported"
    schema = "review_findings: response_schema attempt 1/2: ValidationError (response: review_unknown_candidates)"
    limitations = [provider, schema, "Some hypotheses remain inconclusive."]
    board.publish_assessment(assessment(finding_ids=(), evidence_ids=(), status="partial", termination_reason="round_limit",
        summary="SUPERVISOR_RAW_TEXT", limitations=limitations, details={"report": {
            "status": "partial", "termination_reason": "round_limit", "limitations": limitations,
            "assessments": [{"assignment": {"investigator_id": "modularity", "invocation_id": "modularity-1"},
                "status": "partial", "result": {
                    "status": "partial", "termination_reason": "round_limit", "limitations": limitations,
                    "invocations": [{"assignment": {"investigator_id": "dependency_impact", "invocation_id": "impact-1"},
                        "status": "failed", "result": {"termination_reason": "model_or_schema_error", "limitations": limitations,
                            "model_calls": 2, "tool_calls": 0, "accounted_tokens": 100}}],
                }}],
        }}))
    return board


def test_nested_failure_without_evidence_keeps_its_cause_and_avoids_inherited_diagnostic_duplication():
    board = incomplete_board()
    issues = execution_diagnostics(board.query_assessments("audit"))
    assert len(issues) == 3
    manager, coordinator, investigator = issues
    assert manager.diagnostics == coordinator.diagnostics == []
    assert "límite de rondas" in manager.explanation
    assert len(investigator.diagnostics) == 2
    assert any("HTTP 400" in incident for incident in investigator.incidents)
    assert not any("503" in incident for incident in investigator.incidents)
    assert investigator.source_record_ids == ["manager"]


def test_snapshot_and_report_use_the_same_diagnostics_and_generate_a_grounded_summary():
    board = incomplete_board()
    service = AuditService(board)
    service._states["audit"] = AuditState(run_id="audit", invocation_id="manager", status="partial",
        view_url="/blackboard?run_id=audit", created_at=datetime.now(UTC))
    snapshot = service.snapshot("audit")
    report = build(board)
    assert snapshot.execution_issues == report.annexes_and_traceability.execution_issues
    assert {item.invocation_id for item in report.annexes_and_traceability.executions} == {"manager", "modularity-1", "impact-1"}
    summary = " ".join(item.text for item in report.executive_summary.principal_results)
    assert "SUPERVISOR_RAW_TEXT" not in summary
    assert "HTTP 400" in summary and "no constituyen defectos" in summary
    assert "0 registros de hallazgos" in summary
    assert report.recommendations_and_improvement_plan == []
    statement = next(item for item in report.executive_summary.principal_results if "HTTP 400" in item.text)
    assert [item.record_id for item in statement.source_refs] == ["manager"]
