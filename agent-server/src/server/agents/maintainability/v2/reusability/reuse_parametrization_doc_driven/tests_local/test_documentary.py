"""Documentary delivery receipts for the reuse-parametrization investigator."""

from pathlib import Path
from types import SimpleNamespace

from server.agents.architecture_context.schemas import KnowledgeClaim, KnowledgeEvidence
from server.agents.maintainability.v2.reusability.reuse_parametrization_doc_driven.documentary import (
    documentary_context,
    pending_assessments,
)
from server.agents.maintainability.v2.reusability.reuse_parametrization_doc_driven.investigation import (
    ParametrizationInvestigation,
)
from server.agents.maintainability.v2.reusability.reuse_parametrization_doc_driven.schemas import (
    DocumentClaimRecord,
    ParametrizationCandidate,
    ParametrizationClaimAssessment,
    ParametrizationInvestigationResult,
    ParametrizationPlan,
    ReuseParametrizationDocDrivenResult,
)
from server.services.document_indexing.schemas import IndexReference
from server.services.document_indexing.service import identifier


def _claim():
    return KnowledgeClaim(
        category="interfaces_and_contracts",
        subject="SchemaSelector",
        statement="SchemaSelector selects the validation schema injected by the caller.",
        related_subjects=[],
        certainty="explicit",
        section_ids=["section-1"],
        reasoning="Documented variation boundary.",
        constraint="required",
        evidence=[KnowledgeEvidence(section_id="section-1", start_line=1, end_line=5,
            quote="SchemaSelector selects the validation schema injected by the caller.")],
    )


def _record(*, index=False):
    repository_id = identifier(str(Path.cwd())) if index else None
    return DocumentClaimRecord(
        claim=_claim(),
        document_index=IndexReference(index_id="index-1", repository_id=repository_id, commit="abc123") if index else None,
        section_paths={"section-1": "docs/selection.md"},
        status="applicable",
        reason="Explicit reference with a single primary match.",
        scope_paths=["src/schema_selector.py"],
    )


def _task(document_claim_ids=("claim-0",)):
    return ParametrizationCandidate(
        id="investigation-1",
        scope=["src/schema_selector.py"],
        primary_component="src/schema_selector.py",
        variation_mechanism="documented variation point",
        observed_indicators=["Documented variation: SchemaSelector selects the validation schema."],
        question="Can callers of src/schema_selector.py select the validation schema without modifying it?",
        evidence_needed=["Declarations in the primary component"],
        document_claim_ids=list(document_claim_ids),
    )


def _plan(task, record):
    return ParametrizationPlan(
        objectives=["objective"],
        components=list(task.scope),
        hypotheses=[],
        candidates=[task],
        limitations=[],
        document_claims={"claim-0": record},
    )


def _snapshot():
    return SimpleNamespace(repository=SimpleNamespace(root_path=".", commit="abc123"))


def _context(section_paths, document_path="docs/selection.md", *, line_count=37, missing_document=False):
    repository_id = identifier(str(Path.cwd()))
    document = SimpleNamespace(path=document_path, line_count=line_count,
        index_id="index-1", repository_id=repository_id, commit="abc123", content_hash="hash-1")
    return SimpleNamespace(
        document_index=IndexReference(index_id="index-1", repository_id=repository_id, commit="abc123"),
        section_paths=dict(section_paths),
        consulted_documents=[] if missing_document else [document],
        knowledge_issues=[],
        validation_errors=[],
        execution_status="partial",
        finalization_reason="extraction_failed",
        coverage_assessment_status="completed")


def test_matching_canonical_context_delivers_claims():
    task = _task()
    record = _record(index=True)
    plan = _plan(task, record)
    context = _context({
        "section-1": "docs/selection.md",
        "other-section": "docs/other.md",  # Superset: canonical context covers more sections than this claim.
    })

    delivered = documentary_context(task, plan, _snapshot(), context, character_limit=100_000)

    assert "claim-0" in delivered["claims"]
    assert delivered["unavailable_claims"] == {}
    assert delivered["claims"]["claim-0"]["section_paths"] == {"section-1": "docs/selection.md"}
    assert delivered["claims"]["claim-0"]["scope_paths"] == ["src/schema_selector.py"]
    assert delivered["scope_notice"].startswith("Local portions only")


def test_divergent_canonical_context_marks_claim_unavailable():
    task = _task()
    record = _record(index=True)
    plan = _plan(task, record)
    context = _context({"section-1": "docs/other-name.md"})

    delivered = documentary_context(task, plan, _snapshot(), context, character_limit=100_000)

    assert "claim-0" not in delivered["claims"]
    assert delivered["unavailable_claims"]["claim-0"] == "Claim section paths or document provenance disagree with canonical context."


def test_missing_consulted_document_marks_claim_unavailable():
    task = _task()
    record = _record(index=True)
    plan = _plan(task, record)
    context = _context({"section-1": "docs/selection.md"}, missing_document=True)

    delivered = documentary_context(task, plan, _snapshot(), context, character_limit=100_000)

    assert "claim-0" not in delivered["claims"]
    assert delivered["unavailable_claims"]["claim-0"] == "Claim section paths or document provenance disagree with canonical context."


def test_unavailable_claim_flows_to_host_pending_assessment():
    task = _task()
    record = _record(index=False)  # No document index provenance.
    plan = _plan(task, record)

    delivered = documentary_context(task, plan, _snapshot(), context=None, character_limit=100_000)
    assert delivered["unavailable_claims"]["claim-0"]
    assert "claim-0" not in delivered["claims"]

    pending = pending_assessments(task, [], delivered["unavailable_claims"])
    assert [item.claim_id for item in pending] == ["claim-0"]
    assert pending[0].assessment_origin == "host_pending"
    assert pending[0].status == "inconclusive"


def test_supported_claim_is_delivered_with_verified_provenance():
    task = _task()
    record = _record(index=True)
    plan = _plan(task, record)

    delivered = documentary_context(task, plan, _snapshot(), context=None, character_limit=100_000)
    assert "claim-0" in delivered["claims"]
    assert delivered["claims"]["claim-0"]["statement"] == "SchemaSelector selects the validation schema injected by the caller."
    assert "reasoning" not in delivered["claims"]["claim-0"]
    assert "document_index" not in delivered["claims"]["claim-0"]
    assert delivered["claims"]["claim-0"]["evidence"][0]["quote"]

    assessment = ParametrizationClaimAssessment(
        claim_id="claim-0",
        status="supported",
        rationale="Local implementation honors the documented variation boundary.",
        code_evidence_ids=["e1"],
        scope_paths=["src/schema_selector.py"],
        exceptions_examined=["No delegation path inspected; bounded scope."],
        assessment_origin="investigator",
    )
    assert assessment.assessment_origin == "investigator"
    assert assessment.exceptions_examined == ["No delegation path inspected; bounded scope."]


def _investigation():
    investigator = ParametrizationInvestigation()
    investigator.tools = SimpleNamespace(
        accessible_snapshot=_snapshot(),
        budget_usage=SimpleNamespace(tool_calls=0),
        context=SimpleNamespace(input=SimpleNamespace(
            snapshot_hash="hash-1",
            budget=SimpleNamespace(max_input_tokens_per_call=6000))),
    )
    investigator.config = SimpleNamespace(max_context_characters=100_000, tools=[])
    investigator.request = SimpleNamespace(documented_architecture=None)
    investigator.references = list
    investigator.stop = ""
    investigator.calls = 3
    investigator.tokens = 100
    investigator.estimates = 50
    investigator.issues = []
    investigator.verify_references = lambda refs: (refs, False)
    return investigator


def _result(plan, repository_id="repo"):
    return ReuseParametrizationDocDrivenResult(
        repository_id=repository_id,
        commit="abc123",
        snapshot_hash="hash-1",
        objective="objective",
        plan=plan,
        findings=[],
        hypotheses=[],
        investigation_results=[],
        missing_information=[],
        limitations=[],
        termination_reason="investigating",
        model_calls=1,
        tool_calls=0,
        iterations=0,
        accounted_tokens=50,
        estimated_tokens=25,
        planning_diagnostics={},
    )


def test_close_records_delivery_and_keeps_investigator_assessments():
    investigator = _investigation()
    task = _task()
    plan = _plan(task, _record(index=True))
    conclusion = ParametrizationInvestigationResult(
        investigation_id="investigation-1",
        status="inconclusive",
        summary="Could not conclude.",
        justification="Model did not return a conclusion.",
        components=[],
        claim_assessments=[
            ParametrizationClaimAssessment(
                claim_id="claim-0",
                status="supported",
                rationale="Source honors the documented variation boundary.",
                code_evidence_ids=["e1"],
                scope_paths=["src/schema_selector.py"],
                assessment_origin="investigator",
            ),
        ],
        limitations=["investigation_time_limit"],
    )
    state = {"plan": plan, "current_investigation": 0, "hypotheses": [], "investigation_results": [],
        "limitations": [], "result": _result(plan), "iterations": 0, "termination_reason": "investigating",
        "task_limitations": []}
    outcome = investigator._close_investigation(state, conclusion)

    closed = outcome["investigation_results"][0]
    assert closed.document_claim_delivery == {"claim-0": "delivered"}
    assert [item.assessment_origin for item in closed.claim_assessments] == ["investigator"]
    assert outcome["current_investigation"] == 1


def test_close_marks_unavailable_claims_and_adds_host_pending():
    investigator = _investigation()
    task = _task()
    plan = _plan(task, _record(index=False))
    conclusion = ParametrizationInvestigationResult(
        investigation_id="investigation-1",
        status="inconclusive",
        summary="Could not conclude.",
        justification="Documentary provenance cannot be verified.",
        components=[],
        claim_assessments=[],
        limitations=["investigation_time_limit"],
    )
    state = {"plan": plan, "current_investigation": 0, "hypotheses": [], "investigation_results": [],
        "limitations": [], "result": _result(plan), "iterations": 0, "termination_reason": "investigating",
        "task_limitations": []}
    outcome = investigator._close_investigation(state, conclusion)

    closed = outcome["investigation_results"][0]
    assert closed.document_claim_delivery == {"claim-0": "unavailable"}
    assert [item.assessment_origin for item in closed.claim_assessments] == ["host_pending"]
    assert any("Document claim claim-0" in limitation for limitation in closed.limitations)
    assert outcome["current_investigation"] == 1
