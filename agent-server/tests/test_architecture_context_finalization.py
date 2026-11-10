"""Deterministic final integrity checks against the trusted documentary snapshot."""

from copy import deepcopy
from typing import get_args

import pytest
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from server.agents.architecture_context import (
    ArchitectureContextState,
    validate_and_finalize,
)
from server.agents.architecture_context.schemas import (
    ArchitectureContextResult,
    KnowledgeClaim,
    KnowledgeIssue,
    RetrievalCategory,
)
from server.services.document_indexing import (
    DocumentRecord,
    DocumentSection,
    IndexReference,
)


def complete_state():
    index = IndexReference(index_id="i", repository_id="r", commit="c")
    document = DocumentRecord(
        **index.model_dump(), path="docs/architecture.md", content_hash="h", line_count=5,
    )
    section = DocumentSection(
        **document.model_dump(), section_id="s1", start_line=3, end_line=4,
        headings=(), content="**Gateway** routes requests.\r\nClients MUST authenticate.\r\n",
    )
    claims = [KnowledgeClaim(
        category=category, subject="Gateway", statement=f"Documented {category}",
        certainty="explicit", reasoning="Documented fixture", section_ids=["s1"],
        evidence=[{
            "section_id": "s1", "start_line": 3, "end_line": 3,
            "quote": "**Gateway** routes requests.\r\n",
        }],
    ) for category in get_args(RetrievalCategory)]
    return {
        "document_index": index, "documents": [document], "retrieved_sections": [section],
        "document_discovery_status": "ready", "knowledge": claims,
        "knowledge_issues": [KnowledgeIssue(
            category="interfaces_and_contracts", kind="ambiguity", question="What are the error guarantees?",
            section_ids=["s1"], document_references=[document.path],
        )],
        "processed_section_ids": ["s1"], "extraction_section_status": {"s1": "completed"},
        "coverage_assessment_status": "completed",
        "covered_categories": list(get_args(RetrievalCategory)), "pending_categories": [],
    }


def test_final_node_preserves_valid_knowledge_and_confirms_seven_categories():
    state = complete_state()
    before = deepcopy(state)
    graph = StateGraph(ArchitectureContextState)
    graph.add_node("validate_and_finalize", validate_and_finalize)
    graph.add_edge(START, "validate_and_finalize")
    graph.add_edge("validate_and_finalize", END)
    result = graph.compile().invoke(state)
    assert state == before
    assert result["execution_status"] == "complete"
    assert result["finalization_reason"] == "coverage_complete"
    assert result["validation_errors"] == []
    assert result["knowledge"] == state["knowledge"]
    assert result["knowledge_issues"] == state["knowledge_issues"]
    assert result["consulted_documents"] == state["documents"]
    assert len(result["covered_categories"]) == 7 and result["pending_categories"] == []
    output = ArchitectureContextResult.model_validate_json(result["result"].model_dump_json())
    assert output.execution_status == "complete"
    assert output.knowledge == state["knowledge"]
    assert output.section_paths == {"s1": "docs/architecture.md"}
    assert output.document_index == state["document_index"]
    assert "retrieved_sections" not in output.model_dump()
    assert "retrieval_plan" not in output.model_dump()


@pytest.mark.parametrize("change", ["quote", "range", "section", "ids", "blank"])
def test_invalid_claim_does_not_discard_valid_claims_or_repair_evidence(change):
    state = complete_state()
    bad = state["knowledge"][0]
    evidence = bad.evidence[0]
    if change == "quote":
        evidence = evidence.model_copy(update={"quote": "Gateway routes requests."})
    elif change == "range":
        evidence = evidence.model_copy(update={"start_line": 1, "end_line": 1})
    elif change == "section":
        evidence = evidence.model_copy(update={"section_id": "invented"})
    elif change == "blank":
        evidence = evidence.model_copy(update={"quote": ""})
    bad = bad.model_copy(update={"evidence": [evidence]})
    if change == "ids":
        bad = bad.model_copy(update={"section_ids": ["s1", "invented"]})
    state["knowledge"][0] = bad
    result = validate_and_finalize(state)
    assert result["execution_status"] == "partial"
    assert result["knowledge"] == state["knowledge"][1:]
    assert result["knowledge_issues"] == state["knowledge_issues"]
    assert result["validation_errors"][0].target == "claim"
    assert result["validation_errors"][0].position == 0
    assert result["covered_categories"] == []
    assert result["processed_section_ids"] == []
    assert result["extraction_section_status"]["s1"] == "partial"
    assert result["result"].knowledge == result["knowledge"]
    assert result["result"].validation_errors == result["validation_errors"]
    assert result["result"].execution_status == "partial"


@pytest.mark.parametrize(("field", "value"), [
    ("repository_id", "foreign"), ("commit", "other"), ("index_id", "other"),
    ("content_hash", "other"), ("path", "invented.md"), ("line_count", 6),
    ("end_line", 5),
])
def test_section_provenance_must_match_index_document_and_text(field, value):
    state = complete_state()
    state["retrieved_sections"][0] = state["retrieved_sections"][0].model_copy(update={field: value})
    result = validate_and_finalize(state)
    assert result["execution_status"] == "failed"
    assert result["knowledge"] == result["knowledge_issues"] == []
    assert result["consulted_documents"] == []
    assert any(error.target == "section" for error in result["validation_errors"])


@pytest.mark.parametrize("change", ["section", "document"])
def test_invalid_issue_references_are_reported_without_removing_valid_claims(change):
    state = complete_state()
    update = {"section_ids": ["missing"]} if change == "section" else {"document_references": ["missing.md"]}
    state["knowledge_issues"][0] = state["knowledge_issues"][0].model_copy(update=update)
    result = validate_and_finalize(state)
    assert result["execution_status"] == "partial"
    assert result["knowledge"] == state["knowledge"]
    assert result["knowledge_issues"] == []
    assert "interfaces_and_contracts" in result["pending_categories"]
    assert any(error.target == "issue" for error in result["validation_errors"])


def test_early_termination_keeps_valid_knowledge_but_never_reports_complete():
    state = complete_state()
    state.update(context_stop_reason="planning_context_exhausted", covered_categories=[],
                 coverage_assessment_status="not_run")
    result = validate_and_finalize(state)
    assert result["execution_status"] == "partial"
    assert result["finalization_reason"] == "planning_context_exhausted"
    assert result["knowledge"] == state["knowledge"]
    assert len(result["pending_categories"]) == 7


def test_discovery_failure_has_a_failed_final_result_without_invented_sources():
    state = {"document_index": complete_state()["document_index"], "document_discovery_status": "error"}
    result = validate_and_finalize(state)
    assert result["execution_status"] == "failed"
    assert result["consulted_documents"] == result["knowledge"] == []
    assert result["result"].execution_status == "failed"


def test_result_contract_rejects_complete_with_unconfirmed_coverage():
    output = validate_and_finalize(complete_state())["result"].model_dump()
    output["covered_categories"] = ["components"]
    with pytest.raises(ValidationError, match="seven confirmed categories"):
        ArchitectureContextResult.model_validate(output)


def test_duplicate_section_ids_are_not_silently_resolved():
    state = complete_state()
    state["retrieved_sections"].append(state["retrieved_sections"][0])
    result = validate_and_finalize(state)
    assert result["execution_status"] == "failed"
    assert any("Duplicate section ID" in error.reason for error in result["validation_errors"])


@pytest.mark.parametrize("field", ["repository_id", "commit", "index_id"])
def test_catalog_document_must_belong_to_the_trusted_index(field):
    state = complete_state()
    state["documents"][0] = state["documents"][0].model_copy(update={field: "foreign"})
    result = validate_and_finalize(state)
    assert result["execution_status"] == "failed"
    assert any(error.target == "document" for error in result["validation_errors"])
    assert result["consulted_documents"] == []


def test_foreign_section_does_not_discard_other_valid_documentary_knowledge():
    state = complete_state()
    foreign = state["retrieved_sections"][0].model_copy(update={
        "section_id": "foreign", "commit": "other",
    })
    state["retrieved_sections"].append(foreign)
    bad = state["knowledge"][0].model_copy(update={
        "section_ids": ["foreign"], "evidence": [
            state["knowledge"][0].evidence[0].model_copy(update={"section_id": "foreign"}),
        ],
    })
    valid = list(state["knowledge"])
    state["knowledge"].append(bad)
    result = validate_and_finalize(state)
    assert result["execution_status"] == "partial"
    assert result["knowledge"] == valid
    assert result["knowledge_issues"] == state["knowledge_issues"]
    assert result["consulted_documents"] == state["documents"]
    assert result["extraction_section_status"]["foreign"] == "failed"
    assert {error.target for error in result["validation_errors"]} >= {"section", "claim"}
