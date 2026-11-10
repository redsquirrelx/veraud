"""investigate loop: ranged reads, scoped coverage, recovery and reuse."""

import asyncio
import json

from langchain_core.messages import AIMessage
from test_abstraction_doc_driven_planning import context
from test_architecture_boundary_planning import tools_for

from server.agents.architecture_context import ArchitectureContextResult
from server.agents.maintainability.v2.reusability.abstraction_doc_driven import (
    AbstractionConfig,
    AbstractionRequest,
)
from server.agents.maintainability.v2.reusability.abstraction_doc_driven.execution import (
    AbstractionExecution,
)


def llm_repository(tmp_path, provider_lines=5):
    provider = ["from typing import Protocol", "", "class LlmProvider(Protocol):", "    def complete(self, prompt): ..."]
    if provider_lines > 4:
        provider += [f"# {i}" for i in range(provider_lines - 4)]
    return tools_for(tmp_path, {
        "src/llm/provider.py": "\n".join(provider) + "\n",
        "src/llm/gemini.py": "class GeminiProvider(LlmProvider):\n    def complete(self, prompt): return 'x'\n",
        "src/app/gateway.py": "from src.llm.provider import LlmProvider\n\nclass Gateway:\n    def use(self, p): return True\n",
    })


def documentary_context():
    return ArchitectureContextResult.model_validate(context(
        knowledge=[{
            "category": "interfaces_and_contracts",
            "subject": "LlmProvider",
            "statement": "LlmProvider is the contract every LLM backend implements.",
            "related_subjects": [],
            "certainty": "explicit",
            "section_ids": ["section-1"],
            "reasoning": "The document declares the abstraction.",
            "constraint": "unspecified",
            "evidence": [{"section_id": "section-1", "start_line": 2, "end_line": 4, "quote": "LlmProvider"}],
        }],
        section_paths={"section-1": "docs/architecture.md"},
    ))


class SequenceModel:
    """Offline model driving the plan + investigate sequence deterministically."""

    def __init__(self, investigate_responses):
        self.contexts = []
        self._it = iter(investigate_responses)

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages, **kwargs):
        context_message = messages[1].content
        context = json.loads(context_message)
        self.contexts.append(context)
        usage = {"input_tokens": 40, "output_tokens": 20, "total_tokens": 60}
        if "budget" in context:
            candidates = context["candidates"][:1]
            ids = [candidate["id"] for candidate in candidates]
            response = {"candidate_ids": ids,
                "questions": {candidate["id"]: f"Does {candidate['abstraction_name']} in {candidate['primary_component']} "
                    f"provide substitutability without consumers depending on implementation details?"
                    for candidate in candidates},
                "evidence_requirements": {
                    candidate["id"]: [f"{candidate['abstraction_name']} must behave as a thin contract for its implementers and consumers",
                        f"{candidate['abstraction_name']} must not leak vendor-specific details to callers"]
                    for candidate in candidates}}
            return AIMessage(content=json.dumps(response), usage_metadata=usage)
        response = next(self._it)
        if callable(response):
            response = response(context)
        return AIMessage(content=json.dumps(response), usage_metadata=usage)


def close_inconclusive(context, *, components=(), limitations=("offline_model",)):
    return {"action": "close", "queries": [], "conclusion": {
        "investigation_id": context["investigation"]["id"],
        "status": "inconclusive",
        "summary": "Investigation done with the resources given.",
        "justification": "Deterministic offline model; closing with explicit limitations.",
        "components": list(components), "symbol_ids": [], "relationship_ids": [],
        "evidence_ids": [], "candidates": [],
        "limitations": list(limitations), "claim_assessments": []}}


def requirement_assessments(context):
    """Mechanical citation fixture; offline tests do not certify semantic support."""
    primary = next(item for item in context["evidence"]
        if item["kind"] == "source" and item["path"] == context["investigation"]["primary_component"])
    related = [item for item in context["evidence"] if item["kind"] == "source"
        and item["path"] != context["investigation"]["primary_component"]]
    citations = [primary, *related[:1]]
    return [{"requirement_index": item["requirement_index"], "status": "resolved",
            "rationale": "Offline fixture maps the inspected contract to this evidence requirement.",
            "evidence_ids": [record["id"] for record in citations],
            "scope_paths": [record["path"] for record in citations]}
        for item in context["investigation"]["evidence_requirements"]]


async def drive(tools, model, request):
    execution = AbstractionExecution(model, AbstractionConfig(), tools, request)
    state = execution.initial_state()
    state = {**state, **await execution.plan_investigation(state)}
    while True:
        route = execution.route_investigation(state)
        if route == "tools":
            state = {**state, **await execution.execute_investigation_tools(state)}
        elif route == "investigate":
            state = {**state, **await execution.investigate(state)}
        else:
            return execution, state


def test_unexamined_references_are_dropped_with_limitations(tmp_path):
    tools = llm_repository(tmp_path)

    def fake_close(context):
        source = [item for item in context["evidence"]
            if item["kind"] == "source"]
        return {"action": "close", "queries": [], "conclusion": {
            "investigation_id": context["investigation"]["id"],
            "status": "no_finding",
            "summary": "Contract satisfied in the sample.",
            "justification": "Deterministic offline model; drop invalid references.",
            "components": [*{record["path"] for record in source}],
            "symbol_ids": ["symbol-that-does-not-exist"],
            "relationship_ids": ["retrieval:invented-relationship-id"],
            "evidence_ids": [record["id"] for record in source],
            "candidates": [], "limitations": [],
            "claim_assessments": [], "evidence_assessments": requirement_assessments(context)}}

    _, state = asyncio.run(drive(tools, SequenceModel([fake_close]), AbstractionRequest()))
    conclusion = state["result"].investigation_results[0]
    assert conclusion.status == "no_finding"
    assert conclusion.relationship_ids == []
    assert conclusion.symbol_ids == []
    assert any("not derived from list_relationships" in limitation for limitation in conclusion.limitations)
    assert any("not grounded in delivered source" in limitation for limitation in conclusion.limitations)


def test_delivered_ranges_are_reported_and_continuation_possible(tmp_path):
    tools = llm_repository(tmp_path, provider_lines=150)

    def request_reads(context):
        return {"action": "tools", "queries": [
            {"tool": "get_source_excerpt",
             "arguments": {"path": "src/llm/provider.py", "start_line": 61, "end_line": 500},
             "reason": "Continue beyond the first delivered range.",
             "scope_expansion": ""}],
            "conclusion": None}

    def close(context):
        # Initial contract-span excerpt ([1, 9] for the 3-line fixture symbol) plus the
        # explicit continuation requests issued by the model.
        assert context["delivered_ranges"]["src/llm/provider.py"] == [[1, 9], [1, 60], [61, 120]]
        assert context["uninspected_primary_ranges"] == {"src/llm/provider.py": [[121, 150]]}
        return close_inconclusive(context, limitations=["range_actually_delivered_verified"])

    model = SequenceModel([
        {"action": "tools", "queries": [
            {"tool": "get_source_excerpt",
             "arguments": {"path": "src/llm/provider.py", "start_line": 1, "end_line": 60},
             "reason": "Seed read.", "scope_expansion": ""}],
            "conclusion": None},
        request_reads,
        close,
    ])

    _, state = asyncio.run(drive(tools, model, AbstractionRequest()))

    assert state["termination_reason"] == "investigations_completed"
    assert "range_actually_delivered_verified" in state["result"].limitations


def test_coverage_gap_is_scoped_to_the_question(tmp_path):
    tools = llm_repository(tmp_path)

    def close(context):
        # Irrelevant declarations do not prevent closing; only the question's evidence matters.
        assert context["coverage_gap"] == []
        return close_inconclusive(context, limitations=["scoped_coverage_verified"])

    model = SequenceModel([close])

    _, state = asyncio.run(drive(tools, model, AbstractionRequest()))

    assert state["termination_reason"] == "investigations_completed"
    assert "scoped_coverage_verified" in state["result"].limitations


def test_uninspected_components_fail_validation_and_are_retried(tmp_path):
    tools = llm_repository(tmp_path)
    calls = []

    def bad_close(context):
        calls.append("bad")
        return {"action": "close", "queries": [], "conclusion": {
            "investigation_id": context["investigation"]["id"],
            "status": "no_finding",
            "summary": "Uninspected context.",
            "justification": "Deterministic offline model.",
            "components": ["src/llm/provider.py", "src/llm/uninspected.py"],
            "symbol_ids": [], "relationship_ids": [],
            "evidence_ids": [item["id"] for item in context["evidence"]
            if item["path"] == "src/llm/provider.py" and item["kind"] == "source"],
            "candidates": [], "limitations": [],
            "claim_assessments": []}}

    def good_close(context):
        calls.append("good")
        return {"action": "close", "queries": [], "conclusion": {
            "investigation_id": context["investigation"]["id"],
            "status": "no_finding",
            "summary": "Scoped satisfied contract.",
            "justification": "Deterministic offline model.",
            "components": ["src/llm/provider.py", "src/llm/gemini.py"],
            "symbol_ids": [], "relationship_ids": [],
            "evidence_ids": [item["id"] for item in context["evidence"]
            if item["path"] == "src/llm/provider.py" and item["kind"] == "source"],
            "candidates": [], "limitations": [],
            "claim_assessments": [], "evidence_assessments": requirement_assessments(context)}}

    model = SequenceModel([bad_close, good_close])

    _, state = asyncio.run(drive(tools, model, AbstractionRequest()))

    assert calls == ["bad", "good"]
    assert state["result"].investigation_results[0].status == "no_finding"


def test_claim_assessment_evidence_is_unioned_with_the_conclusion(tmp_path):
    tools = llm_repository(tmp_path)

    def close_without_conclusion_evidence(context):
        source = [item for item in context["evidence"] if item["path"] == "src/llm/provider.py"]
        return {"action": "close", "queries": [], "conclusion": {
            "investigation_id": context["investigation"]["id"],
            "status": "no_finding",
            "summary": "Claim verified with the delivered excerpt.",
            "justification": "Deterministic offline model; evidence only in the assessment.",
            "components": ["src/llm/provider.py", "src/llm/gemini.py"],
            "symbol_ids": source[0]["symbol_ids"] if source else [],
            "relationship_ids": [],
            "evidence_ids": [],
            "candidates": [],
            "limitations": [],
            "evidence_assessments": requirement_assessments(context),
            "claim_assessments": [{
                "claim_id": "index-sha:0",
                "status": "supported",
                "rationale": "The excerpt shows the contract behavior.",
                "code_evidence_ids": [source[0]["id"]] if source else [],
                "scope_paths": ["src/llm/provider.py"],
                "limitations": []}]}}

    model = SequenceModel([close_without_conclusion_evidence])

    _, state = asyncio.run(drive(tools, model, AbstractionRequest(documented_architecture=documentary_context())))

    conclusion = state["result"].investigation_results[0]
    assert conclusion.status == "no_finding"
    assert conclusion.evidence_ids  # union applied automatically
    assert any(claim.claim_id == "index-sha:0" for claim in conclusion.claim_assessments)


def test_identical_tool_requests_are_reused_without_reexecuting(tmp_path):
    tools = llm_repository(tmp_path)

    def request_again(context):
        return {"action": "tools", "queries": [
            {"tool": "get_source_excerpt",
             "arguments": {"path": "src/llm/provider.py", "start_line": 1, "end_line": 60},
             "reason": "Request the already-delivered range.",
             "scope_expansion": ""}],
            "conclusion": None}

    def close(context):
        assert tools.budget_usage.tool_calls == 5
        return close_inconclusive(context, limitations=["tool_reuse_verified"])

    initial = {"action": "tools", "queries": [
        {"tool": "get_source_excerpt",
         "arguments": {"path": "src/llm/provider.py", "start_line": 1, "end_line": 60},
         "reason": "Seed read.", "scope_expansion": ""}],
        "conclusion": None}

    model = SequenceModel([initial, request_again, close])

    _, state = asyncio.run(drive(tools, model, AbstractionRequest()))

    assert state["termination_reason"] == "investigations_completed"
    assert "tool_reuse_verified" in state["result"].limitations


def test_notification_evidence_kinds_remain_distinct(tmp_path):
    tools = llm_repository(tmp_path)

    def close(context):
        kinds = {item["kind"] for item in context["evidence"]}
        return close_inconclusive(context, limitations=[f"evidence_kinds={','.join(sorted(kinds))}"])

    model = SequenceModel([close])

    _, state = asyncio.run(drive(tools, model, AbstractionRequest()))

    assert any(line.startswith("evidence_kinds=") for line in state["result"].limitations)
