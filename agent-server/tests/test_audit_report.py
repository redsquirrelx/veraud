import asyncio
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from server.blackboard.impls.memory import MemoryBlackboard
from server.blackboard.models import Assessment, Evidence, Finding
from server.reporting import (
    AuditReportAgent,
    AuditReportRequest,
    SoftwareAuditReport,
)


def evidence(identifier="e1", **changes):
    values = {"id": identifier, "run_id": "audit", "invocation_id": "investigator", "agent_id": "architecture_boundary",
        "source": "domain/service.py", "kind": "source", "snapshot_hash": "snapshot", "file_id": "file", "content_hash": "hash",
        "tool_call_id": "source-read", "commit": "commit", "commit_verification": "exact", "git_blob_id": "blob",
        "start_line": 1, "end_line": 4, "created_at": datetime(2026, 10, 17, tzinfo=UTC)}
    return Evidence(**(values | changes))


def finding(identifier="f1", status="accepted", **changes):
    values = {"id": identifier, "local_id": identifier, "run_id": "audit", "invocation_id": "investigator",
        "agent_id": "architecture_boundary", "title": "Dependencia concreta del dominio", "description": "El dominio importa storage.",
        "kind": "violation", "criterion_id": "boundary", "criterion": {"id": "boundary", "description": "No importar storage desde dominio.",
            "origin": "explicit", "provenance": "Regla de proyecto publicada"},
        "components": ("domain", "storage"), "justification": "Import inspeccionado", "modularity_impact": "Acoplamiento al almacenamiento.",
        "severity": "high", "evidence_ids": ("e1",), "recommendation": "Inyectar un puerto propiedad del dominio.",
        "details": {"validation_status": status, "review_rationale": "Revisión de fuente y criterio."}}
    return Finding(**(values | changes))


def assessment(identifier="manager", **changes):
    values = {"id": identifier, "run_id": "audit", "invocation_id": identifier, "agent_id": "maintainability_manager",
        "repository_id": "project", "commit": "commit", "snapshot_hash": "snapshot", "objective": "Auditar mantenibilidad.",
        "quality_attribute": "maintainability", "status": "complete", "termination_reason": "sufficient_coverage",
        "finding_ids": ("f1",), "evidence_ids": ("e1",), "summary": "Se evaluó la dependencia del dominio."}
    return Assessment(**(values | changes))


def build(board, run_id="audit"):
    return asyncio.run(AuditReportAgent(blackboard=board).run(AuditReportRequest(run_id=run_id)))


def populated():
    board = MemoryBlackboard()
    board.publish_evidence(evidence())
    board.publish_finding(finding())
    board.publish_assessment(assessment())
    board.publish_assessment(assessment("modularity", agent_id="modularity", status="completed"))
    return board


def test_document_has_all_sections_and_only_verified_findings_drive_risks_and_actions():
    board = populated()
    board.publish_finding(finding("f2", "insufficient_evidence"))
    board.publish_finding(finding("f3", "rejected"))
    report = build(board)
    assert isinstance(SoftwareAuditReport.model_validate_json(report.model_dump_json()), SoftwareAuditReport)
    assert len(report.model_dump()) == 12  # Version, language and the ten formal sections.
    assert report.identification.status == "partial"
    assert report.executive_summary.findings.by_verification == {"verified": 1, "inconclusive": 1, "discarded": 1}
    assert [item.finding_ids for item in report.consolidated_risks.risks] == [["f1"]]
    assert [item.finding_ids for item in report.recommendations_and_improvement_plan] == [["f1"]]
    attributes = {item.id: item for item in report.quality_results.attributes}
    assert attributes["security"].status == attributes["functional_adequacy"].status == "not_evaluated"
    subs = {item.id: item for item in attributes["maintainability"].subcharacteristics}
    assert subs["modularity"].status == "partial"
    assert subs["analysability"].status == subs["modifiability"].status == subs["testability"].status == "not_evaluated"
    ref = report.annexes_and_traceability.evidence_inventory[0]
    assert (ref.commit, ref.snapshot_hash, ref.git_blob_id, ref.start_line, ref.end_line) == ("commit", "snapshot", "blob", 1, 4)


def test_missing_reference_cannot_be_resolved_from_another_audit():
    board = populated()
    board.publish_finding(finding("missing", evidence_ids=("foreign",)))
    board.publish_evidence(evidence("foreign", run_id="another-audit", content="foreign-private-source"))
    report = build(board)
    claim = next(item for item in report.quality_results.findings if item.id == "missing")
    assert claim.verification_status == "inconclusive"
    assert claim.evidence_ids == []
    assert "foreign-private-source" not in report.model_dump_json()
    assert "finding:missing:evidence:foreign" in report.annexes_and_traceability.unresolved_references


@pytest.mark.parametrize("changes, issue", [
    ({"commit_verification": "unverified"}, "commit_attribution_unverified"),
    ({"kind": "metadata"}, "no_technical_evidence"),
])
def test_invalid_support_downgrades_a_claim_even_if_investigator_accepted(changes, issue):
    board = MemoryBlackboard()
    board.publish_evidence(evidence(**changes))
    board.publish_finding(finding())
    report = build(board)
    assert report.quality_results.findings[0].verification_status == "inconclusive"
    assert issue in report.quality_results.findings[0].validation_issues
    assert report.recommendations_and_improvement_plan == []


def test_coordinator_dispute_and_withdrawal_are_not_presented_as_confirmed_defects():
    board = populated()
    contribution = {"reference": "investigator/f1", "invocation_id": "investigator",
        "finding": {"id": "f1", "validation_status": "accepted"}}
    board.publish_assessment(assessment("review", consolidated_findings=({"id": "group", "status": "disputed",
        "contributions": [contribution]},)))
    report = build(board)
    assert report.quality_results.findings[0].verification_status == "inconclusive"
    assert report.quality_results.findings[0].consolidation_ids == ["review/group"]
    board.publish_assessment(assessment("withdrawal", withdrawn_finding_refs=("investigator/f1",)))
    withdrawn = build(board)
    assert withdrawn.quality_results.findings[0].verification_status == "discarded"
    assert withdrawn.consolidated_risks.risks == []


def test_attribute_neutral_contract_accepts_future_security_results_without_fabricating_other_dimensions():
    board = MemoryBlackboard()
    board.publish_evidence(evidence())
    board.publish_finding(finding(agent_id="security-investigator", details={
        "quality_attribute": "security", "subcharacteristic": "confidentiality", "validation_status": "accepted"}))
    board.publish_assessment(assessment(agent_id="security-manager", quality_attribute="security",
        details={"subcharacteristic": "confidentiality"}))
    report = build(board)
    attributes = {item.id: item for item in report.quality_results.attributes}
    assert attributes["security"].status == "completed"
    assert attributes["security"].subcharacteristics[0].id == "confidentiality"
    assert attributes["maintainability"].status == "not_evaluated"
    assert report.quality_results.findings[0].quality_attribute == "security"


def test_empty_blackboard_and_failed_assessment_do_not_imply_compliance():
    board = MemoryBlackboard()
    empty = build(board)
    assert empty.identification.status == "failed"
    assert empty.identification.project_name is None and empty.identification.executed_at is None
    assert all(item.status == "not_evaluated" for item in empty.quality_results.attributes)
    board.publish_assessment(assessment(status="failed", finding_ids=(), evidence_ids=(), summary="No se pudo evaluar."))
    failed = build(board)
    assert failed.identification.status == "failed"
    assert "fallida" in failed.general_conclusions.general_conclusion


def test_mixed_revisions_remain_explicit_and_cannot_support_one_verified_claim():
    board = populated()
    board.publish_evidence(evidence("different", snapshot_hash="another-snapshot", commit="another-commit"))
    board.publish_finding(finding("mixed", evidence_ids=("e1", "different")))
    report = build(board)
    assert report.identification.status == "partial"
    assert len(report.identification.revisions) == 2
    claim = next(item for item in report.quality_results.findings if item.id == "mixed")
    assert "mixed_evidence_revisions" in claim.validation_issues


def test_read_only_repeated_reports_have_stable_source_digest_and_preserve_original_records():
    board = populated()
    original = board.get_finding("audit", "f1")
    first, second = build(board), build(board)
    assert first.identification.source_digest == second.identification.source_digest
    assert first.quality_results == second.quality_results
    assert board.get_finding("audit", "f1") == original
    assert len(board.query_findings("audit")) == 1
    assert len(board.query_assessments("audit")) == 2


def test_positive_abstraction_is_a_strength_not_a_technical_risk():
    board = MemoryBlackboard()
    board.publish_evidence(evidence())
    board.publish_finding(finding(agent_id="abstraction", kind="design_observation", details={
        "validation_status": "accepted", "category": "useful_abstraction"}))
    report = build(board)
    assert report.general_conclusions.strengths
    assert not report.consolidated_risks.risks
    assert not report.general_conclusions.weaknesses


def test_snapshot_only_evidence_is_not_relabelled_as_commit_verified():
    board = MemoryBlackboard()
    board.publish_evidence(evidence(commit=None, commit_verification=None, git_blob_id=None))
    board.publish_finding(finding())
    report = build(board)
    assert report.quality_results.findings[0].verification_status == "verified"
    assert report.annexes_and_traceability.evidence_inventory[0].commit is None


def test_cyclic_assessments_do_not_produce_a_completed_report():
    board = populated()
    board.publish_assessment(assessment("cycle1", assessment_ids=("cycle2",)))
    board.publish_assessment(assessment("cycle2", assessment_ids=("cycle1",)))
    report = build(board)
    assert report.identification.status == "partial"
    assert "assessment_graph:cycle" in report.annexes_and_traceability.unresolved_references


def test_offline_runner_exports_report_from_saved_blackboard_snapshot(tmp_path):
    board = populated()
    snapshot = {"run_id": "audit", "findings": [item.model_dump(mode="json") for item in board.query_findings("audit")],
        "evidence": [item.model_dump(mode="json") for item in board.query_evidence("audit")],
        "assessments": [item.model_dump(mode="json") for item in board.query_assessments("audit")]}
    source, target = tmp_path / "blackboard.json", tmp_path / "report.json"
    source.write_text(json.dumps(snapshot), encoding="utf-8")
    runner = Path(__file__).resolve().parents[1] / "src" / "test-agents" / "run_audit_report.py"
    result = subprocess.run([sys.executable, str(runner), str(source), "--output", str(target)],
        check=False, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    report = SoftwareAuditReport.model_validate_json(target.read_text(encoding="utf-8"))
    assert report.identification.audit_id == "audit"
    assert report.quality_results.findings[0].verification_status == "verified"
