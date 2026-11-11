"""Salvage keeps conforming candidates when obligation requirements fail after retries."""

import asyncio
import json

from langchain_core.messages import AIMessage
from test_abstraction_doc_driven_investigation import llm_repository

from server.agents.maintainability.v2.reusability.abstraction_doc_driven import (
    AbstractionConfig,
    AbstractionRequest,
)
from server.agents.maintainability.v2.reusability.abstraction_doc_driven.execution import (
    AbstractionExecution,
)


class SequenceModel:
    """Offline model; both identical payloads keep one requirement unanchored each call."""

    def __init__(self):
        self.contexts = []

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages, **kwargs):
        context = json.loads(messages[1].content)
        self.contexts.append(context)
        candidates = context["candidates"][:2]
        requirements = {}
        questions = {}
        for item in candidates:
            name = item["abstraction_name"]
            questions[item["id"]] = f"Does {name} in {item['primary_component']} deliver substitutability?"
            requirements[item["id"]] = [
                f"Check consumers of {name} to ensure they never branch on backend class names.",
                f"{name} must never leak backend configuration shapes into consumers.",
                f"{name} must never leak vendor identifiers anywhere in co-operating consumers.",
                "too short",
            ]
        body = {"candidate_ids": [item["id"] for item in candidates],
            "questions": questions, "evidence_requirements": requirements}
        usage = {"input_tokens": 40, "output_tokens": 20, "total_tokens": 60}
        return AIMessage(content=json.dumps(body), usage_metadata=usage)


def test_salvage_keeps_conforming_candidates_after_retries(tmp_path):
    """A single unanchored requirement on every attempt drops only that requirement, once retries are exhausted."""
    tools = llm_repository(tmp_path)
    model = SequenceModel()
    request = AbstractionRequest()
    execution = AbstractionExecution(model, AbstractionConfig(), tools, request)
    state = execution.initial_state()
    update = asyncio.run(execution.plan_investigation(state))
    plan = update["plan"]
    assert [item.abstraction_name for item in plan.candidates] == ["LlmProvider"]
    evidence = plan.candidates[0].evidence_needed
    assert "too short" not in evidence
    assert len(evidence) == 3
    assert any("never leak vendor identifiers" in rule for rule in evidence)
    assert any("salvaged" in item for item in plan.limitations)
