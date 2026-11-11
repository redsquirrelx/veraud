"""Closure gates require an explicit source-backed resolution, not just reads."""

import asyncio

import pytest
from pydantic_core import PydanticCustomError
from test_abstraction_doc_driven_investigation import (
    SequenceModel,
    close_inconclusive,
    drive,
    llm_repository,
    requirement_assessments,
)

from server.agents.maintainability.v2.reusability.abstraction_doc_driven import (
    AbstractionRequest,
)
from server.agents.maintainability.v2.reusability.abstraction_doc_driven.schemas import (
    AbstractionClaimAssessment,
    AbstractionEvidenceAssessment,
    AbstractionInvestigationResult,
)


@pytest.fixture
def inspected(tmp_path):
    execution, state = asyncio.run(drive(llm_repository(tmp_path),
        SequenceModel([close_inconclusive]), AbstractionRequest()))
    task = state["plan"].candidates[0]
    source = next(record for record in execution.references()
        if record.kind == "source" and record.path == task.primary_component)
    result = AbstractionInvestigationResult(investigation_id=task.id, status="no_finding",
        summary="No problem in the inspected sample.", justification="Scoped offline citation test.",
        components=[task.primary_component], evidence_ids=[source.id])
    return execution, task, source, result


def test_reads_without_requirement_resolution_cannot_close(inspected):
    execution, task, source, result = inspected
    with pytest.raises(PydanticCustomError) as error:
        execution._validate_evidence_requirements(result, task, {source.id: source})
    assert error.value.type == "evidence_requirements_unresolved"


@pytest.mark.parametrize("defect", ["missing", "duplicate", "pending", "metadata", "fabricated", "wrong_scope"])
def test_insufficient_or_invalid_requirement_support_is_rejected(inspected, defect):
    execution, task, source, result = inspected
    assessments = [AbstractionEvidenceAssessment(requirement_index=index, status="resolved",
        rationale="The cited contract resolves this requirement in the inspected sample.",
        evidence_ids=[source.id], scope_paths=[source.path]) for index in range(len(task.evidence_needed))]
    references = {source.id: source}
    if defect == "missing":
        assessments.pop()
    elif defect == "duplicate":
        assessments.append(assessments[0])
    elif defect == "pending":
        assessments[0] = assessments[0].model_copy(update={"status": "inconclusive"})
    elif defect == "metadata":
        references[source.id] = source.model_copy(update={"kind": "metadata"})
    elif defect == "fabricated":
        assessments[0] = assessments[0].model_copy(update={"evidence_ids": ["invented"]})
    else:
        assessments[0] = assessments[0].model_copy(update={"scope_paths": ["unread.py"]})
    with pytest.raises(PydanticCustomError):
        execution._validate_evidence_requirements(result.model_copy(update={"evidence_assessments": assessments}),
            task, references)


def test_inconclusive_retains_partial_requirement_assessment(inspected):
    execution, task, source, result = inspected
    partial = result.model_copy(update={"status": "inconclusive", "limitations": ["Consumer not inspected."],
        "evidence_assessments": [AbstractionEvidenceAssessment(requirement_index=0,
            status="inconclusive", rationale="Relevant consumer implementation is still unread.",
            evidence_ids=[source.id])]})
    execution._validate_evidence_requirements(partial, task, {source.id: source})


def test_unresolved_documentary_claim_blocks_no_finding(inspected):
    execution, task, source, result = inspected
    task = task.model_copy(update={"document_claim_ids": ["claim:0"]})
    result = result.model_copy(update={"claim_assessments": [AbstractionClaimAssessment(
        claim_id="claim:0", status="inconclusive", rationale="Relevant behavior is unread.")]})
    with pytest.raises(PydanticCustomError) as error:
        execution._validate_claims(result, task, {source.id: source})
    assert error.value.type == "documentary_claims_unresolved"


def test_documentary_exclusion_does_not_require_code_or_resolve_requirements(inspected):
    execution, task, source, result = inspected
    task = task.model_copy(update={"document_claim_ids": ["claim:0"]})
    result = result.model_copy(update={"claim_assessments": [AbstractionClaimAssessment(
        claim_id="claim:0", status="not_applicable",
        rationale="Build/lint is a process requirement, outside this abstraction question.",
        scope_paths=[task.primary_component])]})
    execution._validate_claims(result, task, {})
    with pytest.raises(PydanticCustomError) as error:
        execution._validate_evidence_requirements(result, task, {source.id: source})
    assert error.value.type == "evidence_requirements_unresolved"


def test_substitution_requirement_citing_only_primary_is_rejected(inspected):
    execution, task, source, result = inspected
    task = task.model_copy(update={
        "question": "Does LlmProvider permit substitution?",
        "evidence_needed": ["Substitution: does LlmProvider allow a drop-in replacement implementation?"],
        "related_components": ["src/llm/gemini.py", "src/app/gateway.py"],
    })
    assessments = [AbstractionEvidenceAssessment(requirement_index=0, status="resolved",
        rationale="Contract declares substitution once.",
        evidence_ids=[source.id], scope_paths=[source.path])]
    with pytest.raises(PydanticCustomError) as error:
        execution._validate_evidence_requirements(result.model_copy(update={"evidence_assessments": assessments}),
            task, {source.id: source})
    assert error.value.type == "substitution_assessment_requires_implementer_or_consumer_scope"


def test_substitution_requirement_citing_related_component_is_accepted(inspected):
    execution, task, source, result = inspected
    task = task.model_copy(update={
        "question": "Does LlmProvider permit substitution?",
        "evidence_needed": ["Substitution: does LlmProvider allow a drop-in replacement implementation?"],
        "related_components": ["src/llm/gemini.py"]})
    related_source = next(record for record in execution.references()
        if record.kind == "source" and record.path == task.related_components[0])
    assessments = [AbstractionEvidenceAssessment(requirement_index=0, status="resolved",
        rationale="GeminiProvider implements LlmProvider behind the same contract surface.",
        evidence_ids=[source.id, related_source.id], scope_paths=[related_source.path])]
    execution._validate_evidence_requirements(
        result.model_copy(update={"evidence_assessments": assessments,
            "components": [source.path, related_source.path]}),
        task, {source.id: source, related_source.id: related_source})


def test_no_finding_with_guarantee_question_citing_only_primary_is_rejected(inspected):
    execution, task, source, result = inspected
    task = task.model_copy(update={
        "question": "Does LlmProvider permit substitution?",
        "evidence_needed": ["Contract and declarations in the primary component"],
        "related_components": ["src/llm/gemini.py"]})
    assessments = [AbstractionEvidenceAssessment(requirement_index=0, status="resolved",
        rationale="Contract resolves the question in the inspected sample.",
        evidence_ids=[source.id], scope_paths=[source.path])]
    with pytest.raises(PydanticCustomError) as error:
        execution._validate_evidence_requirements(result.model_copy(update={"evidence_assessments": assessments}),
            task, {source.id: source})
    assert error.value.type == "no_finding_guarantee_requires_reachable_scope"


def test_no_finding_with_guarantee_question_citing_related_component_is_accepted(inspected):
    execution, task, source, result = inspected
    task = task.model_copy(update={
        "question": "Does LlmProvider permit substitution?",
        "evidence_needed": ["Contract and declarations in the primary component"],
        "related_components": ["src/llm/gemini.py"]})
    related_source = next(record for record in execution.references()
        if record.kind == "source" and record.path == task.related_components[0])
    assessments = [AbstractionEvidenceAssessment(requirement_index=0, status="resolved",
        rationale="GeminiProvider fulfils the contract used by its consumer call sites.",
        evidence_ids=[source.id, related_source.id], scope_paths=[source.path, related_source.path])]
    execution._validate_evidence_requirements(
        result.model_copy(update={"evidence_assessments": assessments,
            "components": [source.path, related_source.path]}),
        task, {source.id: source, related_source.id: related_source})


@pytest.mark.parametrize("defect", ["fabricated", "metadata", "wrong_scope", "blank_rationale"])
def test_documentary_exclusion_still_validates_supplied_evidence(inspected, defect):
    execution, task, source, result = inspected
    task = task.model_copy(update={"document_claim_ids": ["claim:0"]})
    assessment = AbstractionClaimAssessment(claim_id="claim:0", status="not_applicable",
        rationale="The inspected contract shows this requirement applies elsewhere.",
        code_evidence_ids=[source.id], scope_paths=[source.path])
    references = {source.id: source}
    if defect == "fabricated":
        assessment = assessment.model_copy(update={"code_evidence_ids": ["invented"]})
    elif defect == "metadata":
        references[source.id] = source.model_copy(update={"kind": "metadata"})
    elif defect == "wrong_scope":
        assessment = assessment.model_copy(update={"scope_paths": ["unread.py"]})
    else:
        assessment = assessment.model_copy(update={"rationale": " "})
    with pytest.raises(PydanticCustomError):
        execution._validate_claims(result.model_copy(update={"claim_assessments": [assessment]}), task, references)


def test_rejected_premature_closure_can_retrieve_and_resolve_without_reset(tmp_path):
    seen_ids = []

    def premature(context):
        seen_ids.append(context["investigation"]["id"])
        response = close_inconclusive(context)
        response["conclusion"].update(status="no_finding", limitations=[],
            components=["src/llm/provider.py", "src/llm/gemini.py"],
            evidence_ids=[item["id"] for item in context["evidence"]
                if item["kind"] == "source"])
        return response

    def inspect_on_retry(context):
        seen_ids.append(context["investigation"]["id"])
        return {"action": "tools", "queries": [{"tool": "get_source_excerpt",
            "arguments": {"path": "src/llm/provider.py", "start_line": 1, "end_line": 4},
            "reason": "Revisit the contract before resolving evidence requirements."}]}

    def resolved(context):
        response = premature(context)
        response["conclusion"]["evidence_assessments"] = requirement_assessments(context)
        return response

    execution, state = asyncio.run(drive(llm_repository(tmp_path),
        SequenceModel([premature, inspect_on_retry, resolved]), AbstractionRequest()))
    assert len(set(seen_ids)) == 1
    assert state["result"].investigation_results[0].status == "no_finding"
    assert state["result"].evidence
    assert execution.calls == 4  # planning, rejected closure, repair, resolved closure
