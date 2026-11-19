"""Deterministic traces/logs emitted by the architecture-context agent.

Both channels (trace NDJSON file and backend execution events) must receive a
content-free event whenever the pipeline rejects evidence or degrades, so
console output is never the only place the decision exists.
"""

import asyncio
import json
from types import SimpleNamespace
from typing import get_args

import pytest

from server.agents.architecture_context import (
    extract_knowledge,
    validate_and_finalize,
)
from server.agents.architecture_context import extraction as extraction_module
from server.agents.architecture_context import finalization as finalization_module
from server.agents.architecture_context.schemas import (
    KnowledgeClaim,
    KnowledgeExtraction,
    RetrievalCategory,
)
from server.services.document_indexing import (
    DocumentRecord,
    DocumentSection,
    IndexReference,
)


def heading_only_claim():
    return {
        "category": "components",
        "subject": "Router",
        "statement": "Router routes requests",
        "related_subjects": [],
        "certainty": "explicit",
        "section_ids": ["s1"],
        "reasoning": "Documented",
        "constraint": "unspecified",
        "evidence": [{"section_id": "s1", "start_line": 1, "end_line": 1}],
    }


def valid_claim():
    return {
        "category": "components",
        "subject": "Router",
        "statement": "Router routes requests",
        "related_subjects": [],
        "certainty": "explicit",
        "section_ids": ["s1"],
        "reasoning": "Documented",
        "constraint": "unspecified",
        "evidence": [{"section_id": "s1", "start_line": 1, "end_line": 1}],
    }


def section(section_id="s1", content="Router routes requests."):
    return DocumentSection(
        index_id="i", repository_id="r", commit="c", path="architecture.md",
        content_hash="h", line_count=1, section_id=section_id,
        start_line=1, end_line=1, headings=(), content=content,
    )


def test_heading_only_claim_emits_rejected_event():
    events = []

    class Model:
        limits = SimpleNamespace(max_context_characters=100_000)

        async def call(self, prompt, *, schema):
            if schema is KnowledgeExtraction:
                return SimpleNamespace(content=json.dumps(
                    {"sections": [{"section_id": "s1", "claims": [heading_only_claim()], "issues": []}]}
                ))
            raise AssertionError("coverage must not run without accepted claims")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(extraction_module, "architecture_context_event",
                   lambda kind, **kwargs: events.append((kind, kwargs)))
    try:
        asyncio.run(extract_knowledge({"retrieved_sections": [section(content="### Only heading")]}, model=Model()))
    finally:
        monkey.undo()
    rejected = [kwargs for kind, kwargs in events
                if kind == "architecture_context.claim_rejected"]
    assert rejected
    assert any(kwargs["error_code"] == "heading_only" for kwargs in rejected)


def test_coverage_not_run_emits_event_when_payload_exceeds_limit():
    events = []
    original_prompt = extraction_module._prompt

    def fake_prompt(instructions, schema, label, payload, stage):
        if stage == "coverage_assessment" and payload["category"] == "components":
            return "x" * (Model.limits.max_context_characters + 1)
        return original_prompt(instructions, schema, label, payload, stage)

    class Model:
        limits = SimpleNamespace(max_context_characters=100_000)

        async def call(self, prompt, *, schema):
            if schema is KnowledgeExtraction:
                return SimpleNamespace(content=json.dumps(
                    {"sections": [{"section_id": "s1", "claims": [valid_claim()], "issues": []}]}
                ))
            context = json.loads(prompt.split("Accumulated knowledge:\n", 1)[1])
            return SimpleNamespace(content=json.dumps({
                "category": context["category"],
                "sufficient": False,
                "rationale": "fixture",
            }))

    monkey = pytest.MonkeyPatch()
    monkey.setattr(extraction_module, "_prompt", fake_prompt)
    monkey.setattr(extraction_module, "architecture_context_event",
                   lambda kind, **kwargs: events.append((kind, kwargs)))
    try:
        asyncio.run(extract_knowledge({"retrieved_sections": [section()]}, model=Model()))
    finally:
        monkey.undo()
    coverage_events = [kwargs for kind, kwargs in events
                       if kind == "architecture_context.coverage_not_run"]
    assert coverage_events
    assert coverage_events[0]["error_code"] == "coverage_context_exhausted"
    assert coverage_events[0]["details"]["claims"] >= 1


def test_claim_rejection_reaches_execution_buffer_and_trace_sink():
    from server.agent_services.execution_tracking.buffer import ExecutionEventBuffer
    from server.agent_services.execution_tracking.events import execution_event_scope
    from server.agents.architecture_context import observability

    journal = ExecutionEventBuffer()
    trace_calls = []
    monkey = pytest.MonkeyPatch()
    monkey.setattr(observability, "trace_event", lambda kind, **kwargs: trace_calls.append((kind, kwargs)))

    class Model:
        limits = SimpleNamespace(max_context_characters=100_000)

        async def call(self, prompt, *, schema):
            return SimpleNamespace(content=json.dumps(
                {"sections": [{"section_id": "s1", "claims": [heading_only_claim()], "issues": []}]}
            ))

    try:
        with execution_event_scope(11, buffer=journal):
            asyncio.run(extract_knowledge({"retrieved_sections": [section(content="### Only heading")]}, model=Model()))
    finally:
        monkey.undo()
    payloads = [item for _, _, item in journal.pending()]
    assert any(
        item.get("kind") == "phase.changed"
        and item.get("name") == "architecture_context.claim_rejected"
        and item.get("status") == "rejected"
        for item in payloads
    )
    assert any(call[0] == "architecture_context.claim_rejected" for call in trace_calls)


def test_finalization_emits_status_once():
    events = []
    monkey = pytest.MonkeyPatch()
    monkey.setattr(finalization_module, "architecture_context_event",
                   lambda kind, **kwargs: events.append((kind, kwargs)))
    index = IndexReference(index_id="i", repository_id="r", commit="c")
    document = DocumentRecord(
        **index.model_dump(), path="docs/architecture.md", content_hash="h", line_count=2,
    )
    section_obj = DocumentSection(
        **document.model_dump(), section_id="s1", start_line=1, end_line=2,
        headings=(), content="**Router** routes requests.\r\nclients MUST authenticate.\r\n",
    )
    claims = [KnowledgeClaim(
        category=category, subject="Router", statement=f"Documented {category}",
        certainty="explicit", reasoning="Documented fixture", section_ids=["s1"],
        evidence=[{
            "section_id": "s1", "start_line": 1, "end_line": 1,
            "quote": "**Router** routes requests.\r\n",
        }],
    ) for category in get_args(RetrievalCategory)]
    state = {
        "document_index": index, "documents": [document], "retrieved_sections": [section_obj],
        "knowledge": claims, "knowledge_issues": [],
        "processed_section_ids": ["s1"], "extraction_section_status": {"s1": "completed"},
        "coverage_assessment_status": "completed",
        "evaluated_categories": list(get_args(RetrievalCategory)),
        "covered_categories": list(get_args(RetrievalCategory)),
        "pending_categories": [], "retrieval_history": [],
    }
    try:
        validate_and_finalize(state)
    finally:
        monkey.undo()
    finalization_events = [kwargs for kind, kwargs in events
                           if kind == "architecture_context.finalization"]
    assert len(finalization_events) == 1
    assert finalization_events[0]["details"]["execution_status"] == "complete"
    assert finalization_events[0]["error_code"] == "coverage_complete"
