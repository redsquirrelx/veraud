"""Compiled-graph evaluation protocol tests; scripted outcomes are not LLM accuracy benchmarks."""

import asyncio
import json

import pytest
import test_finding_resolution as shared
from langchain_core.messages import AIMessage
from test_finding_resolution import PlanningModel, planning_agent
from test_finding_resolution_investigation import ask, close

from server.agents.finding_resolution import (
    FindingResolutionRequest,
    FindingResolutionResult,
)
from server.runtimes.repository.context import RepositoryContext

finding = shared.finding


@pytest.fixture
def tools(tmp_path):
    value = shared.tools.__wrapped__(tmp_path)
    value.context = RepositoryContext(value.context.snapshot, value.context.input.model_copy(update={
        "budget": value.context.input.budget.model_copy(update={"max_model_calls": 32})}))
    return value


def verdict(context, status="persists", **changes):
    return {"finding_id": context["finding"]["id"], "action": "record", "result": {
        "finding_id": context["finding"]["id"], "status": status,
        "reason": "Current implementation was contrasted with the original finding, not accepted from the prior summary.",
        "evidence_ids": [item["id"] for item in context["current_evidence"]], **changes}}


def more(context):
    return {"finding_id": context["finding"]["id"], "action": "investigate",
        "missing_checks": ["Inspect the current implementation and consuming access before deciding."]}


def inspect(context):
    return ask(context) if not context["tool_results"] else close(context)


class Model:
    def __init__(self, evaluate, investigate=inspect):
        self.evaluate, self.investigate = evaluate, investigate
        self.contexts = []

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages, **kwargs):
        context = json.loads(messages[1].content)
        self.contexts.append(context)
        value = (PlanningModel.plan(context) if "plan" not in context else
            self.evaluate(context) if context["node"] == "evaluate_resolution" else self.investigate(context))
        return AIMessage(content=value if isinstance(value, str) else json.dumps(value),
            usage_metadata={"input_tokens": 100, "output_tokens": 100, "total_tokens": 200})


def execute(finding, tools, evaluate, investigate=inspect, setup=None, native=False, **settings):
    model = Model(evaluate, investigate)
    if native:
        class Structured:
            def __init__(self, schema):
                self.schema = schema
            async def ainvoke(self, messages, **kwargs):
                raw = await model.ainvoke(messages, **kwargs)
                return {"raw": raw, "parsed": self.schema.model_validate_json(raw.content)}
        model.with_structured_output = lambda schema, **kwargs: Structured(schema)
    config = {"max_model_calls": 32, "max_schema_retries": 0} | settings
    agent = planning_agent(model, **config)
    request = FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path,
        findings=finding if isinstance(finding, list) else [finding])
    original = request.model_dump()
    execution = agent.execution_type(model, agent.config, tools, request)
    if setup:
        setup(execution)
    async def stream():
        updates = []
        with execution.timing.stage("evaluation-test"):
            async for update in execution.graph.astream(execution.initial_state(), stream_mode="updates"):
                updates.append(update)
        return updates
    updates = asyncio.run(stream())
    state = execution.initial_state()
    for update in updates:
        for values in update.values():
            state.update(values)
    assert request.model_dump() == original
    return state, model, updates


@pytest.mark.parametrize("status", ["resolved", "persists", "inconclusive"])
@pytest.mark.parametrize("native", [False, True], ids=["json", "structured"])
def test_evaluation_records_each_status_and_advances_only_after_recording(finding, tools, status, native):
    state, model, updates = execute(finding, tools, lambda context: verdict(context, status), native=native)
    assert [next(iter(update)) for update in updates] == [
        "read_finding", "plan_verification", "investigate", "tools", "investigate", "evaluate_resolution", "read_finding"]
    closed = updates[-3]["investigate"]
    assert "next_finding" not in closed and closed["investigation"].finding == finding
    registered = updates[-2]["evaluate_resolution"]
    assert registered["next_finding"] == 1 and registered["results"][0].status == status
    context = model.contexts[-1]
    assert context["node"] == "evaluate_resolution" and context["finding"] == finding.model_dump(mode="json")
    assert context["investigation"]["summary"] and context["tool_results"][0]["data"]["content"]
    assert set(state["results"][0].evidence_ids) <= {item.id for item in state["investigations"][0].evidence}
    assert state["consumption"].model_calls == 4 and state["investigations"][0].consumption.model_calls == 4
    request = FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path, findings=[finding])
    FindingResolutionResult.model_validate({"results": state["results"]}, context={"request": request})


def test_limited_investigation_can_still_establish_persistence(finding, tools):
    def evaluate(context):
        assert context["investigation"]["stop_reason"] == "investigation_iteration_limit"
        assert context["investigation"]["limitations"] and context["current_evidence"]
        return verdict(context)
    state, _, _ = execute(finding, tools, evaluate, max_iterations=1)
    assert state["results"][0].status == "persists" and state["consumption"].model_calls == 3


def test_concrete_checks_return_to_investigation_with_same_plan_and_new_evidence(finding, tools):
    def investigate(context):
        if not context["history"]:
            return close(context, limitations=["Implementation still unread."])
        assert context["verification_gaps"] == more(context)["missing_checks"]
        return inspect(context)
    def evaluate(context):
        return verdict(context, "resolved") if context["current_evidence"] else more(context)
    state, model, updates = execute(finding, tools, evaluate, investigate, max_iterations=4)
    assert len(state["results"]) == len(state["investigations"]) == 1
    assert state["results"][0].status == "resolved" and state["evaluation_returns"] == 1
    assert state["investigations"][0].plan == state["plans"][0]
    assert [item.action for item in state["investigations"][0].history] == ["close", "tools", "close"]
    evaluations = [update["evaluate_resolution"] for update in updates if "evaluate_resolution" in update]
    assert "next_finding" not in evaluations[0] and evaluations[0]["evaluation_return"]
    assert evaluations[1]["next_finding"] == 1 and len(model.contexts) == 6


@pytest.mark.parametrize("returns", [0, 1])
def test_repeated_requests_are_bounded_and_fall_back_to_inconclusive(finding, tools, returns):
    state, model, _ = execute(finding, tools, more,
        lambda context: close(context, limitations=["No source available in this controlled scenario."]),
        max_evaluation_returns=returns)
    assert state["results"][0].status == "inconclusive" and "evaluation_return_limit" in state["results"][0].reason
    assert len([context for context in model.contexts if context.get("node") == "evaluate_resolution"]) == returns + 1
    assert state["consumption"].tool_calls == 0


@pytest.mark.parametrize("failure", ["schema", "historical", "unsupported_resolved"])
def test_invalid_evaluations_are_inconclusive_and_keep_valid_evidence(finding, tools, failure):
    def evaluate(context):
        if failure == "schema":
            return "not JSON"
        return verdict(context, "resolved", evidence_ids=["historical-evidence"] if failure == "historical" else [])
    state, _, _ = execute(finding, tools, evaluate, max_schema_retries=1)
    result = state["results"][0]
    assert result.status == "inconclusive" and "Evaluation failed" in result.reason
    assert state["investigations"][0].evidence and state["investigations"][0].limitations
    assert "historical-evidence" not in result.evidence_ids
    assert state["consumption"].model_calls == 5


def test_absence_and_tool_errors_are_not_resolution(finding, tools):
    def investigate(context):
        if not context["tool_results"]:
            return ask(context, arguments={"path": "absent.py"})
        return close(context, limitations=["The original path is unavailable; current behavior is not established."])
    state, _, _ = execute(finding, tools, lambda context: verdict(context, "resolved", evidence_ids=[]), investigate)
    assert state["results"][0].status == "inconclusive" and state["results"][0].evidence_ids == []
    assert state["investigations"][0].tool_results[0].error


def test_evaluation_call_reserve_is_used_after_investigation_is_preempted(finding, tools):
    def investigate(context):
        return ask(context) if not context["tool_results"] else ask(context, "find_symbols", {"file_path": "service.py"})
    state, _, _ = execute(finding, tools, lambda context: verdict(context), investigate, max_model_calls=4)
    assert state["investigations"][0].stop_reason == "evaluation_call_reserve"
    assert state["results"][0].status == "persists" and state["consumption"].model_calls == 4


def test_tool_budget_does_not_prevent_evaluation_of_existing_source(finding, tools):
    def investigate(context):
        return ask(context) if not context["tool_results"] else ask(context, "find_symbols", {"file_path": "service.py"})
    state, _, _ = execute(finding, tools, lambda context: verdict(context), investigate, max_tool_calls=1)
    assert state["results"][0].status == "persists" and state["termination_reason"] == "tool_call_limit"


def test_global_token_shortage_records_inconclusive_without_provider_call(finding, tools, finite_token_budget):
    state, model, _ = execute(finding, tools, lambda context: verdict(context), max_total_tokens=1000)
    assert state["results"][0].status == "inconclusive" and state["termination_reason"] == "token_limit"
    assert model.contexts == []


def test_failed_evaluation_is_local_and_cannot_cite_other_finding_evidence(finding, tools):
    first_ids = []
    def evaluate(context):
        if context["finding"]["id"] == "first":
            first_ids.extend(item["id"] for item in context["current_evidence"])
            return verdict(context)
        if context["finding"]["id"] == "middle":
            assert not set(first_ids) & {item["id"] for item in context["current_evidence"]}
            return verdict(context, "resolved", evidence_ids=first_ids)
        return verdict(context, "resolved")
    findings = [finding.model_copy(update={"id": name}) for name in ("first", "middle", "last")]
    state, _, _ = execute(findings, tools, evaluate)
    assert [item.status for item in state["results"]] == ["persists", "inconclusive", "resolved"]
    assert [item.finding_id for item in state["results"]] == [item.id for item in findings]
    assert sum(item.consumption.model_calls for item in state["investigations"]) == state["consumption"].model_calls


def test_evaluator_receives_conflicting_summary_and_can_conclude_persistence(finding, tools):
    def investigate(context):
        return ask(context) if not context["tool_results"] else close(context, summary="Prior investigator speculated that this was fixed.")
    def evaluate(context):
        assert "speculated" in context["investigation"]["summary"]
        assert context["tool_results"][0]["data"]["content"] and context["finding"]["justification"] == finding.justification
        return verdict(context, "persists", reason="The prior summary is not proof; current inspected behavior supports persistence.")
    state, _, _ = execute(finding, tools, evaluate, investigate)
    assert state["results"][0].status == "persists"


def test_evaluation_token_reserve_preempts_only_investigation(finding, tools, monkeypatch, finite_token_budget):
    def setup(execution):
        estimate = execution._evaluation_tokens
        monkeypatch.setattr(execution, "_evaluation_tokens", lambda state: 20_000 if state["query_cache"] else estimate(state))
    state, _, _ = execute(finding, tools, lambda context: verdict(context), setup=setup, max_total_tokens=20_000)
    assert state["investigations"][0].stop_reason == "evaluation_token_reserve"
    assert state["results"][0].status == "persists" and state["consumption"].model_calls == 3


def test_evaluation_provider_failure_retains_source_and_stops_globally(finding, tools):
    def evaluate(context):
        raise ValueError("Provider unavailable during evaluation.")
    findings = [finding, finding.model_copy(update={"id": "unstarted"})]
    state, model, _ = execute(findings, tools, evaluate)
    assert state["results"][0].status == "inconclusive" and state["investigations"][0].evidence
    assert state["termination_reason"] == "model_or_schema_error" and state["next_finding"] == 1
    assert all(context["finding"]["id"] != "unstarted" for context in model.contexts)


def test_unverified_current_provenance_cannot_support_decisive_evaluation(finding, tools, monkeypatch):
    def setup(execution):
        references = execution._current_references
        monkeypatch.setattr(execution, "_current_references", lambda state: [
            item.model_copy(update={"commit_verification": "unverified"}) for item in references(state)])
    state, _, _ = execute(finding, tools, lambda context: verdict(context), setup=setup)
    assert state["results"][0].status == "inconclusive" and state["investigations"][0].evidence


def test_return_requires_concrete_checks_not_an_empty_request(finding, tools):
    state, _, _ = execute(finding, tools, lambda context: {"finding_id": context["finding"]["id"],
        "action": "investigate", "missing_checks": ["   "]})
    assert state["results"][0].status == "inconclusive" and state["evaluation_returns"] == 0
