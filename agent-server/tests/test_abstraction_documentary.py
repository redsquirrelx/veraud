"""Documentary traceability checks for the abstraction investigator."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from pydantic_core import PydanticCustomError

from server.agents.architecture_context.schemas import KnowledgeClaim, KnowledgeEvidence
from server.agents.maintainability.v2.reusability.abstraction_doc_driven.documentary import (
    documentary_context,
    pending_assessments,
)
from server.agents.maintainability.v2.reusability.abstraction_doc_driven.investigation import (
    AbstractionInvestigation,
)
from server.agents.maintainability.v2.reusability.abstraction_doc_driven.schemas import (
    AbstractionCandidate,
    AbstractionClaimAssessment,
    AbstractionInvestigationCandidate,
    AbstractionInvestigationResult,
    AbstractionPlan,
    AbstractionResult,
    ConsolidatedClaimAssessments,
    DocumentarySynthesis,
    DocumentClaimRecord,
)
from server.agents.maintainability.v2.reusability.abstraction_doc_driven.synthesis import (
    consolidate_candidates,
    synthesize_documentary,
)
from server.contracts.audit import EvidenceReference
from server.services.document_indexing.schemas import IndexReference
from server.services.document_indexing.service import identifier


def _claim():
    return KnowledgeClaim(
        category="interfaces_and_contracts",
        subject="WidgetGateway",
        statement="WidgetGateway is the contract every widget backend implements.",
        related_subjects=[],
        certainty="explicit",
        section_ids=["section-1"],
        reasoning="Documented contract boundary.",
        constraint="unspecified",
        evidence=[KnowledgeEvidence(section_id="section-1", start_line=1, end_line=5,
            quote="WidgetGateway is the contract every widget backend implements.")],
    )


def _record(*, index=False):
    repository_id = identifier(str(Path.cwd())) if index else None
    return DocumentClaimRecord(
        claim=_claim(),
        document_index=IndexReference(index_id="index-1", repository_id=repository_id, commit="abc123") if index else None,
        section_paths={"section-1": "docs/widget.md"},
        status="applicable",
        reason="Explicit reference with a single primary match.",
        scope_paths=["src/widget_gateway.py"],
    )


def _task(document_claim_ids=("claim-0",)):
    return AbstractionCandidate(
        id="investigation-1",
        abstraction_name="WidgetGateway",
        abstraction_kind="interface",
        scope=["src/widget_gateway.py"],
        primary_component="src/widget_gateway.py",
        related_components=["src/widget_stripe.py"],
        documented_purpose="WidgetGateway is the contract every widget backend implements.",
        observed_indicators=["Documented purpose: WidgetGateway is the contract every widget backend implements."],
        question="Does src/widget_gateway.py deliver substitutability for its implementations and consumers?",
        evidence_needed=["Declarations in the primary component"],
        document_claim_ids=list(document_claim_ids),
    )


def _plan(task, record):
    return AbstractionPlan(
        objectives=["objective"],
        components=list(task.scope),
        hypotheses=[],
        candidates=[task],
        limitations=[],
        document_claims={"claim-0": record},
    )


def _snapshot():
    return SimpleNamespace(repository=SimpleNamespace(root_path=".", commit="abc123"))


def _context(section_paths, document_path="docs/widget.md", *, line_count=37, missing_document=False):
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


def _source_evidence():
    return EvidenceReference(
        id="e1",
        snapshot_hash="hash-1",
        commit="abc123",
        path="src/widget_gateway.py",
        file_id="f0",
        content_hash="content-hash",
        kind="source",
        start_line=1,
        end_line=20,
        symbol_ids=[],
        tool_call_id="tool-1",
        commit_verification="exact",
    )


def _component_candidate(document_claim_ids=()):
    return AbstractionInvestigationCandidate(
        id="candidate-1",
        title="Substitution leak",
        description="Consumers depend on implementation details the contract cannot exclude.",
        criterion_id="abstraction-purpose",
        kind="design_observation",
        components=["src/widget_gateway.py"],
        evidence_ids=["e1"],
        justification="Implementations fail the shared contract.",
        modularity_impact="Substitutability lost.",
        severity="medium",
        confidence=0.7,
        recommendation="Restore the contract boundary.",
        guarantees=["substitutability"],
        implementers=["src/widget_gateway.py"],
        consumers=[],
        document_claim_ids=list(document_claim_ids),
    )


def test_matching_canonical_context_delivers_claims():
    task = _task()
    record = _record(index=True)
    plan = _plan(task, record)
    context = _context({
        "section-1": "docs/widget.md",
        "other-section": "docs/other.md",  # Superset: canonical context covers more sections than this claim.
    })

    delivered = documentary_context(task, plan, _snapshot(), context, character_limit=100_000)

    assert "claim-0" in delivered["claims"]
    assert delivered["unavailable_claims"] == {}
    assert delivered["claims"]["claim-0"]["section_paths"] == {"section-1": "docs/widget.md"}


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
    context = _context({"section-1": "docs/widget.md"}, missing_document=True)

    delivered = documentary_context(task, plan, _snapshot(), context, character_limit=100_000)

    assert "claim-0" not in delivered["claims"]
    assert delivered["unavailable_claims"]["claim-0"] == "Claim section paths or document provenance disagree with canonical context."


def test_unavailable_claim_flows_to_host_pending_and_visible_coverage():
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

    result = AbstractionInvestigationResult(
        investigation_id="investigation-1",
        status="inconclusive",
        summary="Claim unavailable.",
        justification="Documentary provenance cannot be verified.",
        components=["src/widget_gateway.py"],
        claim_assessments=pending,
        document_claim_delivery={"claim-0": "unavailable"},
        limitations=["Document claim claim-0: provenance incompatible."],
    )
    synthesis = synthesize_documentary([result], plan, evidence=[], snapshot_hash="hash-1")
    assert synthesis.coverage.selected_claim_ids == ["claim-0"]
    assert synthesis.coverage.evaluated_claim_ids == []
    assert synthesis.coverage.selected_not_evaluated_claim_ids == ["claim-0"]
    assert synthesis.claims["claim-0"].has_inconclusive is True
    assert synthesis.claims["claim-0"].coverage_status == "not_evaluated"
    assert synthesis.global_compliance_established is False
    assert any(issue.code == "invalid_documentary_provenance" for issue in synthesis.integrity_issues)


def test_supported_claim_is_evaluated_with_source_and_scope():
    task = _task()
    record = _record(index=True)
    plan = _plan(task, record)

    delivered = documentary_context(task, plan, _snapshot(), context=None, character_limit=100_000)
    assert "claim-0" in delivered["claims"]
    assert delivered["claims"]["claim-0"]["statement"] == "WidgetGateway is the contract every widget backend implements."
    assert "reasoning" not in delivered["claims"]["claim-0"]
    assert "document_index" not in delivered["claims"]["claim-0"]
    assert delivered["claims"]["claim-0"]["evidence"][0]["quote"]

    reference = _source_evidence()
    assessment = AbstractionClaimAssessment(
        claim_id="claim-0",
        status="supported",
        rationale="Local implementation honors the documented contract.",
        code_evidence_ids=["e1"],
        scope_paths=["src/widget_gateway.py"],
        exceptions_examined=["No alternative path inspected; bounded scope."],
        assessment_origin="investigator",
    )
    result = AbstractionInvestigationResult(
        investigation_id="investigation-1",
        status="no_finding",
        summary="Contract held in the inspected scope.",
        justification="Declaration and implementations align with the documented purpose.",
        components=["src/widget_gateway.py"],
        evidence_ids=["e1"],
        claim_assessments=[assessment],
        document_claim_delivery={"claim-0": "delivered"},
    )
    synthesis = synthesize_documentary([result], plan, evidence=[reference], snapshot_hash="hash-1")
    assert synthesis.coverage.evaluated_claim_ids == ["claim-0"]
    assert synthesis.coverage.locally_supported_claim_ids == ["claim-0"]
    assert synthesis.coverage.source_examined_claim_ids == ["claim-0"]
    assert synthesis.coverage.delivered_claim_ids == ["claim-0"]
    assert synthesis.coverage.selected_not_evaluated_claim_ids == []
    assert synthesis.coverage.contradicted_claim_ids == []
    assert synthesis.integrity_issues == []
    assert synthesis.claims["claim-0"].coverage_status == "partial"
    assert synthesis.global_compliance_established is False


def test_result_rejects_consolidated_claim_absent_from_plan_catalog():
    task = _task()
    record = _record(index=True)
    plan = _plan(task, record)
    synthesize_documentary([], plan, evidence=[], snapshot_hash="hash-1")
    foreign = ConsolidatedClaimAssessments(
        claim_id="claim-9",
        assessments=[],
        selected_investigation_ids=["investigation-1"],
        evaluated_investigation_ids=[],
        has_contradiction=False,
        has_inconclusive=False,
        coverage_status="not_evaluated",
        comparisons=[],
        limitations=[],
    )
    documentary = DocumentarySynthesis(claims={"claim-9": foreign}, integrity_issues=[])
    with pytest.raises(ValidationError):
        AbstractionResult(
            repository_id="repo",
            commit="abc123",
            snapshot_hash="hash-1",
            objective="objective",
            plan=plan,
            findings=[],
            hypotheses=[],
            missing_information=[],
            limitations=[],
            termination_reason="investigations_completed",
            model_calls=0,
            tool_calls=0,
            iterations=1,
            accounted_tokens=0,
            estimated_tokens=0,
            documentary_synthesis=documentary,
        )


def test_finding_candidate_requires_contradicted_claim_linked_to_candidate():
    investigator = AbstractionInvestigation()
    reference = _source_evidence()
    references = {"e1": reference}
    task = SimpleNamespace(primary_component="src/widget_gateway.py",
        related_components=["src/widget_stripe.py"], document_claim_ids=["claim-0"])
    assessment = AbstractionClaimAssessment(
        claim_id="claim-0",
        status="contradicted",
        rationale="Observed implementations contradict the documented contract.",
        code_evidence_ids=["e1"],
        scope_paths=["src/widget_gateway.py"],
        assessment_origin="investigator",
    )

    unlinked = AbstractionInvestigationResult(
        investigation_id="investigation-1",
        status="finding_candidate",
        summary="Contract leak.",
        justification="Consumers bound to implementation details.",
        components=["src/widget_gateway.py"],
        evidence_ids=["e1"],
        claim_assessments=[assessment],
        candidates=[_component_candidate([])],
    )
    with pytest.raises(PydanticCustomError) as error:
        investigator._validate_claims(unlinked, task, references)
    assert error.value.type == "candidate_document_claim_mismatch"

    linked = unlinked.model_copy(update={"candidates": [_component_candidate(["claim-0"])]})
    investigator._validate_claims(linked, task, references)


def test_consolidated_origins_keep_documentary_references():
    result = AbstractionInvestigationResult(
        investigation_id="investigation-1",
        status="finding_candidate",
        summary="Contract leak.",
        justification="Consumers bound to implementation details.",
        components=["src/widget_gateway.py"],
        evidence_ids=["e1"],
        candidates=[_component_candidate(["claim-0"])],
    )
    _, origins = consolidate_candidates([result])
    assert origins["candidate-1"][0]["document_claim_ids"] == ["claim-0"]
    assert origins["candidate-1"][0]["evidence_ids"] == ["e1"]


def test_close_records_delivery_and_host_pending_assessment():
    investigator = AbstractionInvestigation()
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
    investigator.deferred_stages = []
    investigator.issues = []
    investigator.verify_references = lambda refs: (refs, False)

    task = _task()
    plan = _plan(task, _record(index=True))
    conclusion = AbstractionInvestigationResult(
        investigation_id="investigation-1",
        status="inconclusive",
        summary="Could not conclude.",
        justification="Model did not return a conclusion.",
        components=[],
        claim_assessments=[],
        limitations=["investigation_time_limit"],
    )
    result = AbstractionResult(
        repository_id="repo",
        commit="abc123",
        snapshot_hash="hash-1",
        objective="objective",
        plan=plan,
        findings=[],
        hypotheses=[],
        missing_information=[],
        limitations=[],
        termination_reason="investigating",
        model_calls=1,
        tool_calls=0,
        iterations=0,
        accounted_tokens=50,
        estimated_tokens=25,
    )
    state = {"plan": plan, "current_investigation": 0, "hypotheses": [], "investigation_results": [],
        "limitations": [], "result": result, "iterations": 0, "termination_reason": "investigating",
        "task_limitations": []}
    outcome = investigator._close_investigation(state, conclusion)
    closed = outcome["investigation_results"][0]
    assert closed.document_claim_delivery == {"claim-0": "delivered"}
    assert any(item.assessment_origin == "host_pending" for item in closed.claim_assessments)
    assert outcome["current_investigation"] == 1
