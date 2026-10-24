import asyncio
import copy

import pytest
from test_audit_report import assessment, build, evidence, finding, populated

from server.agents.audit_report.execution import ReportExecution
from server.agents.audit_report.references import ReferenceCatalog
from server.blackboard.impls.memory import MemoryBlackboard
from server.services.audit_report_snapshot import (
    BlackboardSnapshot,
    report_from_snapshot,
)


def continued_board(*, changed_receipt=False, unresolved_gap=False, extra_subject=False, unrelated_evidence=False):
    board = MemoryBlackboard()
    question = "Does the component mix responsibilities?"
    hypothesis = {"id": "h1", "question": question, "component_ids": ["component"], "status": "inconclusive", "evidence_ids": ["e1"]}
    if extra_subject:
        hypothesis["component_ids"].append("still-unassessed")
    old_result = {"hypotheses": [hypothesis], "plan": {"hypotheses": [hypothesis]}, "status": "partial",
        "termination_reason": "iteration_limit", "examined_constraints": [{"id": "a1", "hypothesis_id": "h1", "component_id": "component",
            "validation_status": "insufficient_evidence", "validation_issues": ["review_incomplete"]}]}
    old_call = {"assignment": {"invocation_id": "old-child", "investigator_id": "component_adaptability"},
        "result": old_result, "status": "partial"}
    commitment = {"source_invocation_id": "old-child", "hypothesis_id": "h1", "subject_ids": ["component"], "question": question}
    new_result = copy.deepcopy(old_result)
    new_result["hypotheses"][0]["status"] = "confirmed"
    new_result["hypotheses"][0]["evidence_ids"] = ["unpublished"] if unrelated_evidence else ["e2"]
    new_result["hypotheses"][0]["component_ids"] = ["component"]
    new_result["status"] = "completed"
    new_result["termination_reason"] = "sufficient_evidence"
    new_result["examined_constraints"][0].update(validation_status="source_backed", validation_issues=[])
    new_call = {"assignment": {"invocation_id": "new-child", "investigator_id": "component_adaptability",
        "gap_ids": ["g1"], "commitments": [commitment]}, "result": new_result, "status": "completed"}
    baseline = {"assessment_id": "base-local", "initial_plan": [{"investigator_id": "component_adaptability"}], "invocations": [old_call]}
    continuation = {**copy.deepcopy(baseline), "assessment_id": "next-local", "baseline_assessment_id": "base-local"}
    continuation["invocations"].append(new_call)
    if changed_receipt:
        continuation["invocations"][0]["status"] = "completed"
    for identifier, invocation in (("e1", "old-child"), ("e2", "new-child")):
        board.publish_evidence(evidence(identifier, invocation_id=invocation))
    for identifier, invocation, ev, status in (("f1", "old-child", "e1", "insufficient_evidence"), ("f2", "new-child", "e2", "accepted")):
        board.publish_finding(finding(identifier, invocation_id=invocation, agent_id="component_adaptability", components=("component",),
            evidence_ids=(ev,), details={"validation_status": status, "stable_id": "same-constraint", "classification": "verified_obstacle"}))
    board.publish_assessment(assessment("base", agent_id="reusability", invocation_id="coordinator-old", local_id="base-local", status="partial",
        gaps=({"id": "g1", "question": question},), details={"report": baseline}))
    board.publish_assessment(assessment("next", agent_id="reusability", invocation_id="coordinator-new", local_id="next-local", status="completed",
        finding_ids=("f1", "f2"), evidence_ids=("e1", "e2"), resolved_gap_ids=() if unresolved_gap else ("g1",), details={"report": continuation}))
    board.publish_assessment(assessment(assessment_ids=("base", "next"), finding_ids=("f1", "f2"), evidence_ids=("e1", "e2")))
    return board


def test_continuation_resolves_historical_status_and_preserves_receipts_and_replay_snapshot():
    board = continued_board()
    report = build(board)
    assert report.identification.status == "completed"
    reusability = next(s for a in report.quality_results.attributes for s in a.subcharacteristics if s.id == "reusability")
    assert reusability.status == "completed"
    assert [(f.id, f.lifecycle) for f in report.quality_results.findings] == [("f1", "historical"), ("f2", "current")]
    assert [r.finding_ids for r in report.consolidated_risks.risks] == [["f2"]]
    assert report.executive_summary.findings.total == 2 and report.executive_summary.findings.active_total == 1
    rows = report.annexes_and_traceability.coverage_commitments
    assert [(r.lifecycle, r.status) for r in rows] == [("historical", "deferred"), ("current", "evaluated")]
    assert next(x for x in report.annexes_and_traceability.executions if x.invocation_id == "old-child").recorded_results["examined_constraints"]
    generation = report.annexes_and_traceability.generation
    assert generation.validation_status == "passed" and generation.historical_assessment_ids == ["base"]
    assert any(d.rule == "resolved_same_subject_reassessment" for d in generation.decisions)
    again = asyncio.run(report_from_snapshot(BlackboardSnapshot.model_validate(generation.source_snapshot)))
    assert again.identification.source_digest == report.identification.source_digest
    assert again.quality_results == report.quality_results
    assert again.annexes_and_traceability.generation.generation_id != generation.generation_id
    assert board.get_assessment("audit", "base").status == "partial"


@pytest.mark.parametrize("changed_receipt,unresolved_gap", [(True, False), (False, True)])
def test_invalid_continuation_does_not_hide_unresolved_original_work(changed_receipt, unresolved_gap):
    report = build(continued_board(changed_receipt=changed_receipt, unresolved_gap=unresolved_gap))
    assert report.identification.status == "partial"
    assert report.annexes_and_traceability.generation.historical_assessment_ids == []
    assert any("invalid_continuation" in issue for issue in report.annexes_and_traceability.unresolved_references)


def test_resolving_one_subject_does_not_close_another_or_count_unrelated_source_as_coverage():
    report = build(continued_board(extra_subject=True))
    assert report.identification.status == "partial"
    rows = report.annexes_and_traceability.coverage_commitments
    assert any(r.subject_ids == ["still-unassessed"] and r.lifecycle == "current" and r.status == "deferred" for r in rows)
    assert any(r.subject_ids == ["component"] and r.lifecycle == "historical" for r in rows)
    no_support = build(continued_board(unrelated_evidence=True))
    assert no_support.identification.status == "partial"
    assert any(r.invocation_id == "new-child" and r.status == "pending" and not r.evidence_ids
        for r in no_support.annexes_and_traceability.coverage_commitments)


def test_specific_objectives_use_current_subjects_instead_of_internal_repair_instructions():
    report = build(continued_board())
    objectives = report.objectives_and_scope.specific_objectives
    assert len(objectives) == 1
    assert objectives[0].text.startswith("Evaluar las restricciones de adaptación")
    assert "component" in objectives[0].text
    assert "Does the component mix responsibilities?" not in objectives[0].text
    assert objectives[0].source_refs


def test_conflicting_symbol_metadata_is_not_guessed_and_source_is_not_scanned_for_names():
    identifier = "symbol:" + "d" * 24
    catalog = ReferenceCatalog({"entities": [
        {"id": identifier, "name": "first", "path": "a.py"},
        {"id": identifier, "name": "other", "path": "b.py"}], "content": "component:" + "f" * 24})
    assert "nombre no publicado" in catalog.resolve(identifier)
    assert "first" not in catalog.resolve(identifier)
    assert "component:" + "f" * 24 not in catalog.labels


@pytest.mark.parametrize("classification,disposition,has_risk", [
    ("conditional", "conditional_proposal", False), ("recommended", "opportunity", False),
    ("context_dependent_risk", "contextual_risk", True), ("verified_obstacle", "defect", True),
])
def test_qualified_observations_do_not_become_unconditional_corrections(classification, disposition, has_risk):
    board = MemoryBlackboard()
    board.publish_evidence(evidence())
    qualifications = {"assessed_context": "Another jurisdiction", "sharing_boundary": "Parsing only",
        "conditions": ["Inspect callers first"], "assumptions": ["New schema is required"],
        "unknowns": ["Actual consumers"], "limitations": ["No runtime testing"]}
    board.publish_finding(finding(kind="design_observation", details={"validation_status": "accepted", "classification": classification, **qualifications}))
    report = build(board)
    assert report.quality_results.findings[0].disposition == disposition
    assert bool(report.consolidated_risks.risks) == has_risk
    action = report.recommendations_and_improvement_plan[0]
    for key, value in qualifications.items():
        assert getattr(action, key) == value
    if classification != "verified_obstacle":
        assert "confirmen la corrección" not in action.proposed_verification_criterion
    if classification == "conditional":
        assert any("Propuesta condicionada" in s.text and "Inspect callers first" in s.text for s in report.executive_summary.principal_results)
    assert bool(report.general_conclusions.weaknesses) == has_risk


def test_manager_group_relationships_resolve_to_original_findings():
    board = populated()
    board.publish_finding(finding("f2"))
    for identifier, child in (("coord1", "f1"), ("coord2", "f2")):
        board.publish_assessment(assessment(identifier, agent_id="modularity", consolidated_findings=({"id": "group", "status": "supported",
            "contributions": [{"reference": f"investigator/{child}", "finding": {"validation_status": "accepted"}}]},)))
    board.publish_assessment(assessment("review", relationships=({"kind": "tradeoff", "finding_refs": ["coord1/group", "coord2/group"],
        "rationale": "An explicit cross-dimension relationship."},)))
    report = build(board)
    assert report.consolidated_risks.relationships[0].finding_ids == ["f1", "f2"]
    assert not report.annexes_and_traceability.unresolved_references


def test_failed_child_without_published_source_keeps_specialized_analysis():
    board = MemoryBlackboard()
    board.publish_assessment(assessment(status="partial", finding_ids=(), evidence_ids=(), details={"report": {
        "invocations": [{"assignment": {"invocation_id": "empty-child", "investigator_id": "abstraction"}, "status": "partial",
            "result": {"abstractions_investigated": [{"id": "a", "validation_issues": ["consumer_unread"]}],
                "coverage": {"unassessed_candidates": ["decl"]}, "hypotheses": [], "missing_information": ["Inspect consumers"]}}]}}))
    report = build(board)
    child = next(e for e in report.annexes_and_traceability.executions if e.invocation_id == "empty-child")
    assert child.recorded_results["abstractions_investigated"][0]["validation_issues"] == ["consumer_unread"]
    assert child.recorded_results["coverage"]["unassessed_candidates"] == ["decl"]


def test_traceability_checks_reject_forged_provenance_and_lost_conditions():
    report = build(populated())
    f = report.quality_results.findings[0]
    changed = f.model_copy(update={"source_refs": [f.source_refs[0].model_copy(update={"invocation_id": "wrong"})]})
    invalid = report.model_copy(update={"quality_results": report.quality_results.model_copy(update={"findings": [changed]})})
    with pytest.raises(ValueError, match="provenance"):
        ReportExecution.validate_traceability({"report": invalid})
    action = report.recommendations_and_improvement_plan[0].model_copy(update={"conditions": ["invented condition"]})
    with pytest.raises(ValueError, match="qualifications"):
        ReportExecution.validate_traceability({"report": report.model_copy(update={"recommendations_and_improvement_plan": [action]})})
    original = report.annexes_and_traceability.evidence_inventory[0]
    annexes = report.annexes_and_traceability.model_copy(update={"evidence_inventory": [original.model_copy(update={"content_hash": "forged"})]})
    with pytest.raises(ValueError, match="inventory"):
        ReportExecution.validate_traceability({"report": report.model_copy(update={"annexes_and_traceability": annexes})})
