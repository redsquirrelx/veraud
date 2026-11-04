from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from pydantic import ValidationError

from server.blackboard.identity import AuditIdentity
from server.blackboard.impls.memory import MemoryBlackboard
from server.blackboard.models import Evidence
from server.blackboard.publication import Publication
from server.contracts.legacy_schemes.coordinator import (
    ModularityAssessment,
    ReusabilityAssessment,
    ReusabilityAssignment,
    ReusabilityInvocationRecord,
)
from server.contracts.legacy_schemes.investigator import (
    AbstractionFinding,
    AbstractionResult,
)
from server.runtimes.investigation.schemas import EvidenceReference
from server.services.execution_failures import (
    ExecutionValidationError,
    failure_from_exception,
)


def reference(identifier="e1", kind="source"):
    return EvidenceReference(
        id=identifier, snapshot_hash="snapshot", commit="commit", path="main.py", file_id="file",
        content_hash="hash", kind=kind, start_line=1 if kind == "source" else None,
        end_line=2 if kind == "source" else None, tool_call_id="read",
    )


def investigation():
    ref = reference()
    finding = AbstractionFinding(
        id="f1", title="Uncertain reuse barrier", description="Requires consumer evidence",
        criterion_id="reuse", criterion={"id": "reuse", "description": "Verify reuse",
            "origin": "design_principle", "provenance": "Caller"}, kind="design_observation",
        components=["component"], evidence_ids=[ref.id], evidence=[ref], justification="Partial inspection",
        modularity_impact="Potential coupling", severity="low", confidence=0.3, recommendation="Inspect consumers",
        validation_status="insufficient_evidence", review_rationale="Consumer source unavailable",
        category="coupling", assessment_ids=["local-analysis"], basis="structure_only", duplicate_of=None,
    )
    return AbstractionResult(
        repository_id="repo", commit="commit", snapshot_hash="snapshot", objective="Assess reuse", plan=None,
        findings=[finding], hypotheses=[], missing_information=["Missing consumer"], limitations=["Bounded scope"],
        termination_reason="model_call_limit", model_calls=4, tool_calls=1, iterations=1,
        accounted_tokens=200, estimated_tokens=100, status="partial", tool_failures=["read:timeout"],
        inconclusive_investigations=["local-analysis"],
    )


def test_investigation_mapping_preserves_uncertainty_domain_data_and_collected_evidence():
    board = MemoryBlackboard()
    publication = Publication(board, "abstraction", run_id="audit", invocation_id="attempt")
    report = investigation()
    receipt = publication.publish_investigation(report, [reference(), reference("metadata", "metadata")])

    assert publication.publish_investigation(report, [reference(), reference("metadata", "metadata")]) == receipt
    stored = board.get_finding("audit", receipt.finding_ids[0])
    assert stored.invocation_id == "attempt" and stored.local_id == "f1"
    assert stored.confidence == 0.3 and stored.assessment_ids == ()
    assert stored.details["assessment_ids"] == ["local-analysis"]
    assert stored.details["basis"] == "structure_only" and stored.details["category"] == "coupling"
    assert stored.details["validation_status"] == "insufficient_evidence"
    assert stored.details["review_rationale"] == "Consumer source unavailable"
    assert stored.details["investigation"]["tool_failures"] == ["read:timeout"]
    assert stored.details["investigation"]["missing_information"] == ["Missing consumer"]
    assert stored.details["investigation"]["status"] == "partial"
    assert stored.details["investigation"]["limitations"] == ["Bounded scope"]
    assert len(receipt.evidence_ids) == 2 and len(board.query_findings("audit")) == 1
    evidence = board.get_evidence("audit", stored.evidence_ids[0])
    assert evidence.source == "main.py" and evidence.snapshot_hash == "snapshot"
    assert evidence.local_id == "e1" and evidence.start_line == 1


def test_local_ids_are_namespaced_by_invocation_and_audit():
    board = MemoryBlackboard()
    first = Publication(board, "abstraction", run_id="audit", invocation_id="first")
    second = Publication(board, "abstraction", run_id="audit", invocation_id="second")
    other = Publication(board, "abstraction", run_id="other", invocation_id="first")
    receipts = [p.publish_investigation(investigation(), []) for p in (first, second, other)]

    assert len({r.finding_ids[0] for r in receipts}) == 3
    assert len({r.evidence_ids[0] for r in receipts}) == 3
    assert len(board.query_findings("audit")) == 2
    assert len(board.query_findings("audit", "first")) == 1
    assert board.get_finding("other", receipts[0].finding_ids[0]) is None


def test_query_evidence_is_scoped_filterable_and_returns_detached_records():
    board = MemoryBlackboard()
    first = Evidence(**reference().model_dump(), agent_id="agent", run_id="audit", invocation_id="first",
        details={"nested": ["original"]})
    second = first.model_copy(update={"id": "e2", "invocation_id": "second"})
    foreign = first.model_copy(update={"run_id": "other", "details": {"nested": ["foreign"]}})
    for record in (first, second, foreign):
        board.publish_evidence(record)

    assert {record.id for record in board.query_evidence("audit")} == {"e1", "e2"}
    assert board.query_evidence("audit", "first") == [first]
    assert board.query_evidence("other") == [foreign]
    assert board.query_evidence("missing") == []
    assert board.query_evidence("audit", "missing") == []
    detached = board.query_evidence("audit", "first")[0]
    detached.details["nested"].append("changed")
    assert board.get_evidence("audit", "e1").details == {"nested": ["original"]}
    with pytest.raises(ValueError):
        board.query_evidence(" ")
    with pytest.raises(ValueError):
        board.query_evidence("audit", " ")


def test_audit_identity_is_immutable_and_children_reuse_assignment_ids():
    identity = AuditIdentity(run_id="audit", invocation_id="manager")
    child = identity.child("assigned-invocation")

    assert child.run_id == identity.run_id and child.invocation_id == "assigned-invocation"
    assert AuditIdentity.model_validate_json(identity.model_dump_json()) == identity
    with pytest.raises(ValidationError):
        identity.run_id = "different-audit"


@pytest.mark.parametrize("values", [{"run_id": ""}, {"invocation_id": "  "}])
def test_blank_identity_is_rejected_instead_of_silently_generating_a_new_one(values):
    with pytest.raises(ValidationError):
        AuditIdentity(**values)


def test_reconstructed_publication_is_idempotent_and_preserves_original_timestamps():
    board = MemoryBlackboard()
    identity = AuditIdentity(run_id="audit", invocation_id="investigator")
    first = Publication(board, "abstraction", identity=identity)
    original = first.publish_investigation(investigation(), [])
    stored = board.get_finding(identity.run_id, original.finding_ids[0])
    retry = Publication(board, "abstraction", identity=AuditIdentity.model_validate_json(identity.model_dump_json()))
    retry.created_at = first.created_at + timedelta(seconds=1)

    assert retry.publish_investigation(investigation(), []) == original
    assert board.get_finding(identity.run_id, original.finding_ids[0]) == stored
    assert len(board.query_findings(identity.run_id, identity.invocation_id)) == 1
    assert board.get_evidence(identity.run_id, original.evidence_ids[0]).created_at == first.created_at


def test_conflicting_publication_preserves_original_and_reports_safe_host_cause():
    board = MemoryBlackboard()
    publication = Publication(board, "abstraction", run_id="audit", invocation_id="investigator")
    receipt = publication.publish_investigation(investigation(), [])
    original = board.get_evidence("audit", receipt.evidence_ids[0])
    altered = investigation().model_copy(update={"limitations": ["PRIVATE_CONTENT_MUST_NOT_LEAK"]})
    with pytest.raises(ExecutionValidationError) as caught:
        publication.publish_investigation(altered, [])
    failure = failure_from_exception(caught.value, "invoke_child")
    assert failure.code == "blackboard_publication_conflict" and failure.stage == "publish_result"
    assert failure.diagnostics == ["record_type=Evidence", "differing_fields=details"]
    assert "PRIVATE_CONTENT" not in failure.model_dump_json()
    assert board.get_evidence("audit", receipt.evidence_ids[0]) == original


def test_conflicting_references_are_rejected_before_any_claim_is_published():
    board = MemoryBlackboard()
    publication = Publication(board, "abstraction", run_id="audit", invocation_id="investigator")
    with pytest.raises(ExecutionValidationError) as caught:
        publication.publish_investigation(investigation(), [reference().model_copy(update={"content_hash": "PRIVATE_HASH"})])
    failure = failure_from_exception(caught.value, "invoke_child")
    assert failure.stage == "publish_result" and failure.code == "blackboard_publication_conflict"
    assert "differing_fields=content_hash" in failure.diagnostics
    assert "PRIVATE_HASH" not in failure.model_dump_json()
    assert not board.query_evidence("audit") and not board.query_findings("audit")


def test_reconstructed_retry_resumes_after_evidence_was_written(monkeypatch):
    board = MemoryBlackboard()
    identity = AuditIdentity(run_id="audit", invocation_id="investigator")
    publish = board.publish_finding
    attempts = 0

    def fail_once(record):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("Interrupted publication")
        return publish(record)

    monkeypatch.setattr(board, "publish_finding", fail_once)
    first = Publication(board, "abstraction", identity=identity)
    with pytest.raises(OSError):
        first.publish_investigation(investigation(), [])
    evidence = board.get_evidence(identity.run_id, first.record_id("evidence", "e1"))

    retry = Publication(board, "abstraction", identity=identity)
    retry.created_at = first.created_at + timedelta(seconds=1)
    receipt = retry.publish_investigation(investigation(), [])

    assert len(board.query_findings(identity.run_id)) == 1
    assert board.get_evidence(identity.run_id, receipt.evidence_ids[0]) == evidence
    assert board.get_finding(identity.run_id, receipt.finding_ids[0]).evidence_ids == receipt.evidence_ids


def test_conflicting_retry_keeps_the_original_claim():
    board = MemoryBlackboard()
    identity = AuditIdentity(run_id="audit", invocation_id="investigator")
    first = Publication(board, "abstraction", identity=identity)
    report = investigation()
    receipt = first.publish_investigation(report, [])
    stored = board.get_finding(identity.run_id, receipt.finding_ids[0])
    changed = report.model_copy(update={"findings": [report.findings[0].model_copy(update={"confidence": 0.9})]})

    with pytest.raises(ValueError):
        Publication(board, "abstraction", identity=identity).publish_investigation(changed, [])

    assert board.get_finding(identity.run_id, receipt.finding_ids[0]) == stored
    assert len(board.query_findings(identity.run_id)) == 1


def test_concurrent_reconstructed_publications_do_not_conflict_on_generated_timestamps():
    barrier = Barrier(4)

    class ConcurrentBlackboard(MemoryBlackboard):
        def publish_evidence(self, evidence):
            # All sessions read before any one session appends its first record.
            barrier.wait(timeout=10)
            return super().publish_evidence(evidence)

    board = ConcurrentBlackboard()
    identity = AuditIdentity(run_id="audit", invocation_id="investigator")
    publications = [Publication(board, "abstraction", identity=identity) for _ in range(4)]
    for index, publication in enumerate(publications):
        publication.created_at = publications[0].created_at + timedelta(seconds=index)
    with ThreadPoolExecutor(max_workers=4) as workers:
        receipts = list(workers.map(lambda publication: publication.publish_investigation(investigation(), []), publications))

    assert all(receipt == receipts[0] for receipt in receipts)
    assert len(board.query_findings(identity.run_id)) == 1
    assert board.get_evidence(identity.run_id, receipts[0].evidence_ids[0]) is not None


@pytest.mark.parametrize("status", ["partial", "failed"])
def test_empty_incomplete_assessments_are_published_with_the_original_report(status):
    board = MemoryBlackboard()
    publication = Publication(board, "modularity", run_id="audit", invocation_id="coordinator")
    report = ModularityAssessment(
        assessment_id="local-assessment", repository_id="repo", commit=None, snapshot_hash="snapshot",
        objective="Assess modularity", targets=["main.py"], status=status, termination_reason="resource_limit",
        summary="Insufficient coverage", investigator_registry=[], initial_plan=[], invocations=[],
        consolidated_findings=[], material_gaps=[], resolved_gap_ids=[], withdrawn_finding_refs=[],
        limitations=["No investigator completed"], rounds_completed=1,
        consumption={"model_calls": 1, "accounted_tokens": 100}, duration_seconds=0.5, node_transitions=[],
    )
    receipt = publication.publish_assessment(report)
    stored = board.get_assessment("audit", receipt.assessment_ids[0])

    assert stored.status == status and stored.finding_ids == () and stored.assessment_ids == ()
    assert stored.limitations == ("No investigator completed",)
    assert stored.consumption.accounted_tokens == 100
    assert stored.details["report"] == report.model_dump(mode="json")
    retry = Publication(board, "modularity", identity=publication.identity)
    assert retry.publish_assessment(report) == receipt
    assert board.get_assessment("audit", stored.id) == stored
    # The same execution cannot acquire a second Assessment by changing a local ID.
    with pytest.raises(ValueError):
        retry.publish_assessment(report.model_copy(update={"assessment_id": "another-local-id"}))
    assert len(board.query_assessments("audit")) == 1


def test_assessment_references_published_claims_without_replacing_them_after_collection():
    board = MemoryBlackboard()
    publication = Publication(board, "reusability", run_id="audit", invocation_id="coordinator")
    child = publication.child("investigator", "abstraction")
    original = investigation()
    receipt = child.publish_investigation(original, [])
    # Collection can judge a claim differently; the published original must survive.
    reviewed = original.model_copy(update={"findings": [original.findings[0].model_copy(
        update={"validation_status": "rejected", "review_rationale": "Rejected by supervisor"})]})
    report = ReusabilityAssessment(
        assessment_id="synthesis", repository_id="repo", commit="commit", snapshot_hash="snapshot",
        objective="Assess reuse", targets=["main.py"], status="partial", termination_reason="round_limit",
        summary="Unresolved coverage", investigator_registry=[], initial_plan=[],
        invocations=[ReusabilityInvocationRecord(
            assignment=ReusabilityAssignment(invocation_id="investigator", investigator_id="abstraction",
                request_id="request", round_id="round", round=1, question="Inspect", targets=["main.py"]),
            status="partial", result=reviewed, evidence=[reference()],
        )], consolidated_findings=[], material_gaps=[], resolved_gap_ids=[], withdrawn_finding_refs=[],
        limitations=["Unknown consumers"], rounds_completed=1, consumption={}, duration_seconds=1, node_transitions=[],
        continuation_decision={"route": "no", "reason": "round_limit", "material_gap_ids": [], "pending_request_ids": []},
    )
    parent = publication.publish_assessment(report)
    stored = board.get_assessment("audit", parent.assessment_ids[0])

    assert stored.finding_ids == receipt.finding_ids and stored.evidence_ids == receipt.evidence_ids
    assert board.get_finding("audit", stored.finding_ids[0]).details["validation_status"] == "insufficient_evidence"
    assert stored.details["report"]["invocations"][0]["result"]["findings"][0]["validation_status"] == "rejected"
    assert len(board.query_findings("audit")) == 1
    assert Publication(board, "reusability", identity=publication.identity).publish_assessment(report) == parent
