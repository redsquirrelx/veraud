"""Deterministic evidence checks and extraction state transitions."""

import asyncio
import json
from copy import deepcopy
from functools import partial
from types import SimpleNamespace
from typing import get_args

import pytest
from langgraph.graph import END, START, StateGraph

from server.agents.architecture_context import extract_knowledge
from server.agents.architecture_context.extraction import (
    _section_payload,
    _validate_section,
)
from server.agents.architecture_context.routing import route_after_extraction
from server.agents.architecture_context.schemas import (
    KnowledgeClaim,
    KnowledgeExtraction,
    KnowledgeIssue,
    RetrievalCategory,
)
from server.services.document_indexing import DocumentRecord, DocumentSection


def section(section_id="s1", content="The gateway routes requests."):
    line_count = max(1, len(content.splitlines()))
    return DocumentSection(
        index_id="i", repository_id="r", commit="c", path="architecture.md",
        content_hash="h", line_count=line_count, section_id=section_id,
        start_line=1, end_line=line_count, headings=(), content=content,
    )


def claim(quote, subject):
    return {
            "category": "components", "subject": subject,
            "statement": f"{subject} routes requests", "related_subjects": [],
            "certainty": "explicit", "section_ids": ["s1"],
            "reasoning": "Documented", "constraint": "unspecified",
            "evidence": [{
                "section_id": "s1", "start_line": 99 if quote == "fabricated" else 1,
                "end_line": 99 if quote == "fabricated" else 1,
            }],
        }


def test_empty_section_is_processed_and_coverage_is_assessed_once():
    class Model:
        limits = SimpleNamespace(max_context_characters=100_000)

        def __init__(self):
            self.schemas = []

        async def call(self, prompt, *, schema):
            self.schemas.append(schema)
            if schema is KnowledgeExtraction:
                value = {"sections": [{"section_id": "s1", "claims": [], "issues": []}]}
            else:
                value = {"categories": [
                    {"category": category, "sufficient": False, "rationale": "Insufficient evidence"}
                    for category in get_args(RetrievalCategory)
                ]}
            return SimpleNamespace(content=json.dumps(value))

    model = Model()
    graph = StateGraph(dict)
    graph.add_node("extract_knowledge", partial(extract_knowledge, model=model))
    graph.add_edge(START, "extract_knowledge")
    graph.add_edge("extract_knowledge", END)
    state = {"retrieved_sections": [section()]}
    result = asyncio.run(graph.compile().ainvoke(state))
    assert result["processed_section_ids"] == ["s1"]
    assert result["knowledge"] == []
    assert result["covered_categories"] == [] and len(result["pending_categories"]) == 7
    assert model.schemas == [KnowledgeExtraction]
    assert result["coverage_assessment_status"] == "not_run"
    assert "processed_section_ids" not in state


@pytest.mark.parametrize(("updates", "destination"), [
    ({}, "plan_retrieval"),
    ({"pending_categories": []}, END),
    ({"context_stop_reason": "extraction_failed"}, END),
    ({"coverage_assessment_status": "failed"}, END),
])
def test_extraction_route_continues_only_with_pending_needs_and_no_failure(updates, destination):
    state = {
        "pending_categories": ["interfaces_and_contracts"],
        "coverage_assessment_status": "completed", **updates,
    }
    assert route_after_extraction(state) == destination


def test_extraction_exception_is_logged_and_empty_knowledge_skips_coverage(caplog):
    class Model:
        limits = SimpleNamespace(max_context_characters=100_000)

        async def call(self, prompt, *, schema):
            if schema is KnowledgeExtraction:
                raise ValueError("provider unavailable")
            return SimpleNamespace(content=json.dumps({"categories": [
                {"category": category, "sufficient": True, "rationale": "Claimed"}
                for category in get_args(RetrievalCategory)
            ]}))

    result = asyncio.run(extract_knowledge(
        {"retrieved_sections": [section()]}, model=Model()
    ))
    assert result["processed_section_ids"] == []
    assert result["covered_categories"] == []
    assert len(result["pending_categories"]) == 7
    assert result["context_stop_reason"] == "extraction_failed"
    assert result["coverage_assessment_status"] == "not_run"
    assert "ValueError" in caplog.text and "provider unavailable" in caplog.text


def test_invalid_citation_does_not_discard_valid_claim_or_prior_knowledge(caplog):
    original = KnowledgeExtraction.model_validate({"sections": [{
        "section_id": "s1",
        "claims": [claim("The gateway routes", "Gateway"), claim("fabricated", "Invented")],
        "issues": [],
    }]})
    categories = get_args(RetrievalCategory)

    class Model:
        limits = SimpleNamespace(max_context_characters=100_000)

        def __init__(self):
            self.schemas = []

        async def call(self, prompt, *, schema):
            self.schemas.append(schema)
            if schema is KnowledgeExtraction:
                return SimpleNamespace(content=original.model_dump_json())
            return SimpleNamespace(content=json.dumps({"categories": [
                {"category": category, "sufficient": True, "rationale": "Claims appear sufficient"}
                for category in categories
            ]}))

    prior_data = claim("Prior evidence", "Prior component")
    prior_data["section_ids"] = ["old"]
    prior_data["evidence"] = [{
        "section_id": "old", "start_line": 1, "end_line": 1,
        "quote": "Prior evidence",
    }]
    prior = KnowledgeExtraction.model_validate({"sections": [{
        "section_id": "old", "claims": [prior_data], "issues": [],
    }]}).sections[0].claims[0]
    result = asyncio.run(extract_knowledge(
        {"retrieved_sections": [section()], "knowledge": [prior]}, model=Model()
    ))
    assert len(result["knowledge"]) == 2
    assert result["knowledge"][0] == prior
    assert result["knowledge"][1].subject == "Gateway"
    assert result["processed_section_ids"] == []
    assert result["context_stop_reason"] == "extraction_failed"
    assert result["extraction_section_status"]["s1"] == "partial"
    assert result["covered_categories"] == []
    assert "section_id=s1" in caplog.text
    assert "lines=99-99" in caplog.text
    assert result["evaluated_categories"] == ["components"]


def test_original_line_ranges_reconstruct_markdown_table_and_mermaid_verbatim():
    content = "# Gateway\n\n| Operation | Result |\n|---|---|\n| route | response |\n\n```mermaid\ngraph TD\n  A-->B\n```"
    source = section(content=content)
    result = KnowledgeExtraction.model_validate({"sections": [{
        "section_id": "s1",
        "claims": [
            {**claim("", "Table"), "evidence": [{"section_id": "s1", "start_line": 3, "end_line": 5}]},
            {**claim("", "Diagram"), "evidence": [{"section_id": "s1", "start_line": 7, "end_line": 10}]},
        ],
        "issues": [],
    }]})

    class Model:
        limits = SimpleNamespace(max_context_characters=100_000)

        async def call(self, prompt, *, schema):
            if schema is KnowledgeExtraction:
                return SimpleNamespace(content=result.model_dump_json())
            return SimpleNamespace(content=json.dumps({"categories": [
                {"category": category, "sufficient": False, "rationale": "Not enough"}
                for category in get_args(RetrievalCategory)
            ]}))

    extracted = asyncio.run(extract_knowledge({"retrieved_sections": [source]}, model=Model()))
    assert [e.quote for c in extracted["knowledge"] for e in c.evidence] == [
        "| Operation | Result |\n|---|---|\n| route | response |\n",
        "```mermaid\ngraph TD\n  A-->B\n```",
    ]
    assert extracted["extraction_section_status"]["s1"] == "completed"


@pytest.mark.parametrize("content", [
    "A paragraph describes the gateway.\r\nAnother paragraph.\r\n",
    "| Operation | Result |\n|---|---|\n| route | response |\n",
    "```mermaid\ngraph TD\n  A-->B\n```",
])
def test_absolute_line_payload_and_literal_reconstruction(content):
    source = section(content=content)
    source = source.model_copy(update={
        "start_line": 42, "end_line": 41 + source.end_line,
        "line_count": 41 + source.line_count,
    })
    payload = _section_payload(source)
    assert payload["lines"] == [
        {"line_number": number, "text": text}
        for number, text in enumerate(content.splitlines(keepends=True), start=42)
    ]
    data = claim("", "Gateway")
    data["evidence"] = [{
        "section_id": "s1", "start_line": 42, "end_line": source.end_line,
    }]
    item = KnowledgeExtraction.model_validate({"sections": [{
        "section_id": "s1", "claims": [data], "issues": [],
    }]}).sections[0]
    accepted, _, errors = _validate_section(item, source, {"s1": source})
    assert not errors
    assert accepted[0].evidence[0].quote == content
    data["evidence"][0].update(start_line=1, end_line=1)
    item = KnowledgeExtraction.model_validate({"sections": [{
        "section_id": "s1", "claims": [data], "issues": [],
    }]}).sections[0]
    accepted, _, errors = _validate_section(item, source, {"s1": source})
    assert not accepted and errors  # Never auto-offset relative line numbers.


@pytest.mark.parametrize("content", ["   \n\t\n", "## Gateway\n", "Gateway\n=======\n"])
def test_empty_or_heading_only_evidence_is_rejected(content):
    source = section(content=content)
    data = claim("", "Gateway")
    data["evidence"] = [{"section_id": "s1", "start_line": 1, "end_line": source.end_line}]
    item = KnowledgeExtraction.model_validate({"sections": [{
        "section_id": "s1", "claims": [data], "issues": [],
    }]}).sections[0]
    accepted, _, errors = _validate_section(item, source, {"s1": source})
    assert not accepted and errors


def test_coverage_receives_full_catalog_and_pending_sources_not_just_generic_claims():
    documents = [DocumentRecord(
        index_id="i", repository_id="r", commit="c", path=f"doc-{number}.md",
        content_hash="h", line_count=20,
    ) for number in range(23)]
    sections = [section(f"s{number}", "A CLI and HTTP interface are available.").model_copy(
        update={"path": documents[number].path, "line_count": 20}
    ) for number in range(4)]

    class Model:
        limits = SimpleNamespace(max_context_characters=100_000)

        def __init__(self):
            self.calls = []

        async def call(self, prompt, *, schema):
            self.calls.append(prompt.measurement.stage)
            if schema is KnowledgeExtraction:
                generic = []
                for number in range(3):
                    item = claim("", f"Interface {number}")
                    item.update(category="interfaces_and_contracts", statement="Provides an interface")
                    item["evidence"][0]["section_id"] = "s0"
                    item["section_ids"] = ["s0"]
                    generic.append(item)
                payload = {"sections": [
                    {"section_id": source.section_id,
                     "claims": generic if source.section_id == "s0" else [], "issues": []}
                    for source in sections
                ]}
            else:
                context = json.loads(prompt.split("Accumulated knowledge:\n", 1)[1])
                sources = context["documentary_sources"]
                assert sources["catalog_available"] is True
                assert len(sources["documents"]) == 23
                assert sources["unretrieved_document_paths"] == [doc.path for doc in documents[4:]]
                assert sources["documents"][0] == {
                    "path": "doc-0.md", "line_count": 20,
                    "retrieved_sections": [{
                        "section_id": "s0", "start_line": 1, "end_line": 1,
                        "processing_status": "completed",
                    }],
                }
                assert all(doc["retrieved_sections"] == [] for doc in sources["documents"][4:])
                assert "contents solely from filenames" in prompt
                assert "general claims or mentions of CLI/HTTP are insufficient" in prompt
                assert len(context["claims"]) == 3
                payload = {"categories": [
                    {"category": category, "sufficient": False,
                     "rationale": "General interface descriptions lack operations and schemas; potential sources remain."}
                    for category in get_args(RetrievalCategory)
                ]}
            return SimpleNamespace(content=json.dumps(payload))

    model = Model()
    result = asyncio.run(extract_knowledge(
        {"documents": documents, "retrieved_sections": sections}, model=model
    ))
    assert model.calls == ["initial_extraction", "coverage_assessment"]
    assert len(result["knowledge"]) == 3
    assert len(result["processed_section_ids"]) == 4
    assert result["coverage_assessment_status"] == "completed"
    assert "interfaces_and_contracts" not in result["covered_categories"]
    assert "interfaces_and_contracts" in result["pending_categories"]


@pytest.mark.parametrize(("text", "constraint"), [
    ("aims to keep modules independent", "unspecified"),
    ("requests are routed through the gateway", "unspecified"),
    ("HTTP is not implemented", "unspecified"),
    ("the server does not expose HTTP", "unspecified"),
    ("all clients MUST authenticate", "required"),
    ("clients MUST NOT bypass authentication", "prohibited"),
])
def test_extraction_prompt_distinguishes_normative_rules_from_goals_and_behavior(text, constraint):
    """Guard the model's instructions and enum preservation, not real LLM accuracy."""
    class Model:
        limits = SimpleNamespace(max_context_characters=100_000)

        async def call(self, prompt, *, schema):
            if schema is KnowledgeExtraction:
                assert "Separate architectural goals from obligations" in prompt
                assert "behavioral descriptions from rules" in prompt
                assert f'"{text}"' in prompt
                assert "do not strengthen descriptive language into normative language" in prompt
                item = claim("", "Gateway")
                item.update(statement=text, constraint=constraint)
                payload = {"sections": [{"section_id": "s1", "claims": [item], "issues": []}]}
            else:
                payload = {"categories": [
                    {"category": category, "sufficient": False, "rationale": "Only one fact"}
                    for category in get_args(RetrievalCategory)
                ]}
            return SimpleNamespace(content=json.dumps(payload))

    result = asyncio.run(extract_knowledge({"retrieved_sections": [section(content=text)]}, model=Model()))
    assert result["knowledge"][0].constraint == constraint
    assert result["knowledge"][0].evidence[0].quote == text


def test_normative_prompt_separates_permissions_and_prohibitions_without_rewriting_evidence():
    text = "clients may read public data but must not modify it"

    class Model:
        limits = SimpleNamespace(max_context_characters=100_000)

        async def call(self, prompt, *, schema):
            if schema is KnowledgeExtraction:
                assert "normatively atomic" in prompt
                assert "separate allowed/read and prohibited/modify claims" in prompt
                assert '"the server does not expose HTTP" is still descriptive' in prompt
                claims = []
                for action, constraint in [("read public data", "allowed"), ("modify public data", "prohibited")]:
                    item = claim("", "Clients")
                    item.update(statement=action, constraint=constraint)
                    claims.append(item)
                payload = {"sections": [{"section_id": "s1", "claims": claims, "issues": []}]}
            else:
                payload = {"categories": [
                    {"category": category, "sufficient": False, "rationale": "Only one rule"}
                    for category in get_args(RetrievalCategory)
                ]}
            return SimpleNamespace(content=json.dumps(payload))

    result = asyncio.run(extract_knowledge({"retrieved_sections": [section(content=text)]}, model=Model()))
    assert [(c.statement, c.constraint) for c in result["knowledge"]] == [
        ("read public data", "allowed"), ("modify public data", "prohibited"),
    ]
    assert all(c.evidence[0].quote == text for c in result["knowledge"])


def test_compact_coverage_across_rounds_preserves_all_claims_and_large_evidence():
    prior = []
    for number in range(120):
        data = claim("", f"Component {number}")
        data["reasoning"] = "Full extraction reasoning. " * 50
        data["evidence"][0]["quote"] = "Long source excerpt. " * 500
        prior.append(KnowledgeClaim.model_validate(data))
    issue = KnowledgeIssue(
        category="interfaces_and_contracts", kind="unknown",
        question="Which error guarantees apply?", section_ids=["s1"],
        document_references=["pending.md"],
    )
    original = deepcopy(prior)
    source = section()
    document = DocumentRecord.model_validate({
        name: getattr(source, name) for name in DocumentRecord.model_fields
    })
    pending = document.model_copy(update={"path": "pending.md"})
    state = {
        "knowledge": prior, "knowledge_issues": [issue],
        "retrieved_sections": [source], "processed_section_ids": ["s1"],
        "documents": [document, pending],
    }

    class Model:
        limits = SimpleNamespace(max_context_characters=100_000)

        def __init__(self):
            self.coverage_counts = []
            self.extractions = 0

        async def call(self, prompt, *, schema):
            assert len(prompt) <= self.limits.max_context_characters
            if schema is KnowledgeExtraction:
                self.extractions += 1
                sources = json.loads(prompt.split("Retrieved sections:\n", 1)[1])
                item = claim("", f"New component {self.extractions}")
                item["section_ids"] = [sources[0]["section_id"]]
                item["evidence"][0]["section_id"] = sources[0]["section_id"]
                payload = {"sections": [{
                    "section_id": sources[0]["section_id"], "claims": [item], "issues": [],
                }]}
            else:
                context = json.loads(prompt.split("Accumulated knowledge:\n", 1)[1])
                self.coverage_counts.append(len(context["claims"]))
                assert len(context["claims"]) == 120 + self.extractions
                assert all(set(item) == {
                    "category", "subject", "statement", "certainty", "constraint", "references"
                } for item in context["claims"])
                assert context["claims"][0]["references"] == [["s1", 1, 1]]
                assert "Long source excerpt" not in prompt
                assert "Full extraction reasoning" not in prompt
                assert context["issues"] == [issue.model_dump(mode="json")]
                assert context["section_processing"]["s1"] == "completed"
                assert context["documentary_sources"]["unretrieved_document_paths"] == ["pending.md"]
                payload = {"categories": [
                    {"category": category, "sufficient": False, "rationale": "Needs more documentation"}
                    for category in get_args(RetrievalCategory)
                ]}
            return SimpleNamespace(content=json.dumps(payload))

    assert len(json.dumps([item.model_dump() for item in prior])) > 100_000
    model = Model()
    for number in range(2):
        new_source = section(f"new-{number}")
        state = {**state, "retrieved_sections": [*state["retrieved_sections"], new_source]}
        before = deepcopy(state)
        result = asyncio.run(extract_knowledge(state, model=model))
        assert state == before
        assert result["coverage_assessment_status"] == "completed"
        assert result["knowledge"][:120] == original
        assert result["knowledge_issues"] == [issue]
        state = {**state, **result}
    assert model.coverage_counts == [121, 122]
    assert len(state["knowledge"]) == 122
    assert prior == original


def test_compact_coverage_overflow_is_explicit_and_does_not_truncate(caplog):
    data = claim("", "Component")
    data["statement"] = "Architectural fact. " * 6000
    original = KnowledgeClaim.model_validate(data)

    class Model:
        limits = SimpleNamespace(max_context_characters=100_000)

        async def call(self, prompt, *, schema):
            raise AssertionError("Oversized coverage must not be sent")

    result = asyncio.run(extract_knowledge({"knowledge": [original]}, model=Model()))
    assert result["knowledge"] == [original]
    assert result["context_stop_reason"] == "coverage_context_exhausted"
    assert result["coverage_assessment_status"] == "not_run"
    assert result["evaluated_categories"] == result["covered_categories"] == []
    assert "compact coverage context exceeds limit" in caplog.text
    assert "max_context_characters=100000" in caplog.text
    assert "no claims omitted" in caplog.text


def test_cross_section_evidence_ids_are_rejected_and_section_is_partial(caplog):
    data = KnowledgeExtraction.model_validate({"sections": [{
        "section_id": "s1", "claims": [{
            **claim("", "Gateway"), "section_ids": ["s1", "s2"],
            "evidence": [
                {"section_id": "s1", "start_line": 1, "end_line": 1},
                {"section_id": "s2", "start_line": 1, "end_line": 1},
            ],
        }], "issues": [],
    }]})

    class Model:
        limits = SimpleNamespace(max_context_characters=100_000)

        async def call(self, prompt, *, schema):
            if schema is KnowledgeExtraction:
                return SimpleNamespace(content=data.model_dump_json())
            raise AssertionError("No accepted claims; coverage must not run")

    result = asyncio.run(extract_knowledge(
        {"retrieved_sections": [section()]}, model=Model()
    ))
    assert result["knowledge"] == []
    assert result["extraction_section_status"]["s1"] == "partial"
    assert "outside its batch" in caplog.text


def test_extraction_batches_at_most_four_sections_without_truncating():
    sections = [section(f"s{index}", f"Section {index} complete text.") for index in range(9)]

    class Model:
        limits = SimpleNamespace(max_context_characters=100_000)

        def __init__(self):
            self.batch_sizes = []

        async def call(self, prompt, *, schema):
            payload = json.loads(prompt.split("Retrieved sections:\n", 1)[1])
            self.batch_sizes.append(len(payload))
            return SimpleNamespace(content=json.dumps({"sections": [
                {"section_id": item["section_id"], "claims": [], "issues": []}
                for item in payload
            ]}))

    model = Model()
    result = asyncio.run(extract_knowledge({"retrieved_sections": sections}, model=model))
    assert model.batch_sizes == [4, 4, 1]
    assert len(result["processed_section_ids"]) == 9
    assert all(status == "completed" for status in result["extraction_section_status"].values())


def test_quote_accepts_original_lines_not_model_reformatted_text(caplog):
    extracted = KnowledgeExtraction.model_validate({"sections": [{
        "section_id": "s1",
        "claims": [claim("reformatted quote is ignored", "Gateway")],
        "issues": [],
    }]})

    class Model:
        limits = SimpleNamespace(max_context_characters=100_000)

        async def call(self, prompt, *, schema):
            if schema is KnowledgeExtraction:
                return SimpleNamespace(content=extracted.model_dump_json())
            return SimpleNamespace(content=json.dumps({"categories": [
                {"category": category, "sufficient": True, "rationale": "Documented"}
                for category in get_args(RetrievalCategory)
            ]}))

    result = asyncio.run(extract_knowledge({"retrieved_sections": [section()]}, model=Model()))
    assert len(result["knowledge"]) == 1
    assert result["processed_section_ids"] == ["s1"]
    assert result["extraction_section_status"]["s1"] == "completed"
    assert result["knowledge"][0].evidence[0].quote == "The gateway routes requests."


def test_model_none_preserves_accumulated_knowledge_and_categories():
    prior = KnowledgeExtraction.model_validate({"sections": [{
        "section_id": "old", "claims": [claim("The gateway routes", "Gateway")], "issues": [],
    }] }).sections[0].claims[0]
    result = asyncio.run(extract_knowledge({
        "knowledge": [prior], "covered_categories": ["components"],
        "pending_categories": ["relationships"], "processed_section_ids": ["old"],
    }, model=None))
    assert result["knowledge"] == [prior]
    assert result["covered_categories"] == ["components"]
    assert result["pending_categories"] == ["relationships"]


def test_coverage_exception_is_logged_and_call_has_coverage_stage(caplog):
    data = KnowledgeExtraction.model_validate({"sections": [{
        "section_id": "s1", "claims": [claim("The gateway routes", "Gateway")],
        "issues": [],
    }]})

    class Model:
        limits = SimpleNamespace(max_context_characters=100_000)

        def __init__(self):
            self.stages = []

        async def call(self, prompt, *, schema):
            self.stages.append(prompt.measurement.stage)
            if schema is KnowledgeExtraction:
                return SimpleNamespace(content=data.model_dump_json())
            raise RuntimeError("coverage provider unavailable")

    model = Model()
    result = asyncio.run(extract_knowledge(
        {"retrieved_sections": [section()]}, model=model
    ))
    assert result["knowledge"]
    assert result["covered_categories"] == []
    assert result["context_stop_reason"] == "coverage_assessment_failed"
    assert model.stages == ["initial_extraction", "coverage_assessment"]
    assert "RuntimeError" in caplog.text and "coverage provider unavailable" in caplog.text
