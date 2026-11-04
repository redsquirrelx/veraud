"""A malformed investigation response is local; resource/provider failures are not."""

import asyncio
import json

import pytest
import test_finding_resolution as shared
from langchain_core.messages import AIMessage
from test_finding_resolution import PlanningModel, planning_agent
from test_finding_resolution_investigation import ask, close

from server.agents.finding_resolution import FindingResolutionRequest
from server.runtimes.repository.context import RepositoryContext

finding = shared.finding
tools = shared.tools


class Model:
    def __init__(self, decide):
        self.decide = decide
        self.contexts = []

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages, **kwargs):
        context = json.loads(messages[1].content)
        self.contexts.append(context)
        value = PlanningModel.plan(context) if "plan" not in context else self.decide(context)
        return AIMessage(content=value if isinstance(value, str) else json.dumps(value),
            usage_metadata={"input_tokens": 100, "output_tokens": 100, "total_tokens": 200})


def request_for(finding, tools):
    return FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path,
        findings=[finding.model_copy(update={"id": identifier}, deep=True) for identifier in ("first", "middle", "last")])


@pytest.mark.parametrize("invalid", ["json", "citation"])
def test_middle_finding_exhausts_retries_but_later_finding_is_processed(finding, tools, caplog, invalid):
    caplog.set_level("INFO", logger="server.finding-resolution")
    # This scenario needs ten attempts (including two invalid responses). Both
    # test-only envelopes allow them; the separate limit test deliberately does not.
    tools.context = RepositoryContext(tools.context.snapshot, tools.context.input.model_copy(update={
        "budget": tools.context.input.budget.model_copy(update={"max_model_calls": 12})}))
    def decide(context):
        if not context["tool_results"]:
            assert context["current_evidence"] == [] and context["history"] == []
            return ask(context)
        if context["finding"]["id"] == "middle":
            return "not valid JSON" if invalid == "json" else close(context, evidence_ids=["invented"])
        return close(context)
    request = request_for(finding, tools)
    before = request.model_dump()
    model = Model(decide)
    state = asyncio.run(planning_agent(model, max_schema_retries=1, max_model_calls=12).run(request, tools=tools))
    assert [item.finding_id for item in state["investigations"]] == ["first", "middle", "last"]
    first, failed, last = state["investigations"]
    assert first.stop_reason == last.stop_reason == "evidence_collected"
    assert failed.stop_reason == "model_or_schema_error" and failed.evidence and failed.tool_results
    assert failed.plan == state["plans"][1] and failed.finding == request.findings[1]
    assert failed.consumption.model_calls == 4 and failed.consumption.tool_calls == 1
    assert len([item for item in failed.limitations if "response_schema attempt" in item]) == 2
    assert "invented" not in {reference.id for reference in failed.evidence}
    assert {reference.id for reference in failed.evidence}.isdisjoint(reference.id for reference in last.evidence)
    assert [turn.action for turn in failed.history] == ["tools"]
    assert state["termination_reason"] == "investigations_completed_with_errors" and state["next_finding"] == 3
    assert state["consumption"].model_calls == 10 and state["consumption"].tool_calls == 3
    assert sum(item.consumption.accounted_tokens for item in state["investigations"]) == state["consumption"].accounted_tokens
    assert state["limitations"] and request.model_dump() == before
    assert any('"finding_id": "middle"' in item.getMessage() and '"transition": "investigate->read_finding"' in item.getMessage()
        for item in caplog.records)


def test_call_limit_at_invalid_response_does_not_start_the_next_finding(finding, tools):
    def decide(context):
        if not context["tool_results"]:
            return ask(context)
        return "bad JSON" if context["finding"]["id"] == "middle" else close(context)
    model = Model(decide)
    state = asyncio.run(planning_agent(model, max_schema_retries=1, max_model_calls=7).run(request_for(finding, tools), tools=tools))
    assert [item.finding_id for item in state["investigations"]] == ["first", "middle"]
    assert state["investigations"][-1].evidence and state["investigations"][-1].stop_reason == "model_or_schema_error"
    assert state["termination_reason"] == "model_call_limit" and state["consumption"].model_calls == 7
    assert all(context["finding"]["id"] != "last" for context in model.contexts)


def test_provider_failure_after_invalid_response_is_not_cleared(finding, tools):
    invalid_attempts = 0
    def decide(context):
        nonlocal invalid_attempts
        if not context["tool_results"]:
            return ask(context)
        if context["finding"]["id"] == "middle":
            invalid_attempts += 1
            if invalid_attempts == 1:
                return "bad JSON"
            raise ValueError("Provider transport failed.")
        return close(context)
    model = Model(decide)
    state = asyncio.run(planning_agent(model, max_schema_retries=1).run(request_for(finding, tools), tools=tools))
    assert [item.finding_id for item in state["investigations"]] == ["first", "middle"]
    assert state["termination_reason"] == "model_or_schema_error" and state["investigations"][-1].evidence
    assert any("provider_request:" in item for item in state["investigations"][-1].limitations)
    assert all(context["finding"]["id"] != "last" for context in model.contexts)


def test_cancellation_during_middle_finding_propagates(finding, tools):
    entered = asyncio.Event()
    class CancellableModel(Model):
        async def ainvoke(self, messages, **kwargs):
            context = json.loads(messages[1].content)
            if "plan" in context and context["finding"]["id"] == "middle":
                self.contexts.append(context)
                entered.set()
                await asyncio.Event().wait()
            return await super().ainvoke(messages, **kwargs)
    model = CancellableModel(lambda context: close(context,
        limitations=["No source was inspected in this cancellation test."]))
    request = request_for(finding, tools)
    before = request.model_dump()
    async def invoke():
        task = asyncio.create_task(planning_agent(model).run(request, tools=tools))
        await asyncio.wait_for(entered.wait(), timeout=5)
        task.cancel()
        return await task
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(invoke())
    assert request.model_dump() == before
    assert all(context["finding"]["id"] != "last" for context in model.contexts)
