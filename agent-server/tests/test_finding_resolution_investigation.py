"""Real compiled-graph tests with controlled LLM decisions and repository tools."""

import asyncio
import json

import pytest
import test_finding_resolution as shared
from test_finding_resolution import PlanningModel, planning_agent

from server.agents.finding_resolution import FindingResolutionRequest

finding = shared.finding
tools = shared.tools


class Investigator(PlanningModel):
    def __init__(self, decide):
        super().__init__(lambda context: self.plan(context) if "plan" not in context else decide(context))

    async def ainvoke(self, messages, **kwargs):
        if json.loads(messages[1].content).get("node") == "investigate":
            assert any("action=tools requests" in message.content for message in messages if message.type == "human")
        return await super().ainvoke(messages, **kwargs)


def ask(context, name="get_source_excerpt", arguments=None):
    return {"finding_id": context["finding"]["id"], "action": "tools", "summary": "Inspect the next relevant implementation.",
        "queries": [{"id": "current-query", "name": name, "arguments": arguments or {"path": "service.py"}}]}


def close(context, **changes):
    return {"finding_id": context["finding"]["id"], "action": "close",
        "summary": "Collected current implementation evidence for later evaluation.",
        "evidence_ids": [reference["id"] for reference in context["current_evidence"]], **changes}


def run(finding, tools, decide, **config):
    request = FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path, findings=[finding])
    model = Investigator(decide)
    state = asyncio.run(planning_agent(model, **config).run(request, tools=tools))
    return state, model


def test_direct_close_records_a_limitation_without_unnecessary_queries(finding, tools):
    state, model = run(finding, tools, lambda context: close(context, limitations=["Current code could not be inspected."]))
    record = state["investigations"][0]
    assert record.stop_reason == "investigation_limited" and not record.evidence and not record.tool_results
    assert len(model.contexts) == 3 and state["consumption"].tool_calls == 0
    assert record.finding == finding and record.plan == state["plans"][0]
    assert not hasattr(record, "status") and state["results"][0].status == "inconclusive"


@pytest.mark.parametrize("native", [False, True], ids=["json", "structured"])
def test_full_investigation_flow_and_visible_evidence(finding, tools, caplog, native):
    """pytest tests/test_finding_resolution_investigation.py::test_full_investigation_flow_and_visible_evidence -s"""
    caplog.set_level("INFO", logger="server.finding-resolution")
    def decide(context):
        if not context["tool_results"]:
            return ask(context)
        assert "def use(): return 1" in context["tool_results"][0]["data"]["content"]
        if len(context["tool_results"]) == 1:
            return ask(context, "find_symbols", {"file_path": "service.py"})
        assert any(view["tool_name"] == "find_symbols" and view["data"]["items"] for view in context["tool_results"])
        return close(context)
    model = Investigator(decide)
    if native:
        class Structured:
            def __init__(self, schema):
                self.schema = schema
            async def ainvoke(self, messages, **kwargs):
                raw = await model.ainvoke(messages, **kwargs)
                return {"raw": raw, "parsed": self.schema.model_validate_json(raw.content)}
        model.with_structured_output = lambda schema, **kwargs: Structured(schema)
    request = FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path, findings=[finding])
    before = request.model_dump()
    agent = planning_agent(model)
    execution = agent.execution_type(model, agent.config, tools, request)
    async def stream():
        with execution.timing.stage("investigation-test"):
            return [update async for update in execution.graph.astream(execution.initial_state(), stream_mode="updates")]
    updates = asyncio.run(stream())
    nodes = [next(iter(update)) for update in updates]
    assert nodes == ["read_finding", "plan_verification", "investigate", "tools", "investigate", "tools", "investigate", "evaluate_resolution", "read_finding", "finalize"]
    record = updates[-4]["investigate"]["investigations"][0]
    assert record.stop_reason == "evidence_collected" and record.evidence and record.tool_results
    assert record.finding == finding and record.plan.finding_id == finding.id
    assert record.consumption.model_calls == 4 and record.consumption.tool_calls == 2 and record.consumption.accounted_tokens == 800
    assert request.model_dump() == before
    ids = {reference.id for reference in record.evidence}
    assert set(record.history[-1].evidence_ids) <= ids and "historical-evidence" not in ids
    assert all(reference.snapshot_hash == tools.accessible_snapshot.repository.snapshot_hash and reference.content_hash
        and reference.tool_call_id for reference in record.evidence)
    events = [json.loads(item.getMessage().split("finding_resolution_trace ", 1)[1]) for item in caplog.records
        if item.getMessage().startswith("finding_resolution_trace ")]
    assert all(event["finding_id"] == finding.id for event in events)
    assert [event["transition"] for event in events].count("tools->investigate") == 2
    closing = next(event for event in events if event["transition"] == "investigate->close")
    assert set(closing["evidence_ids"]) == ids
    print("\n" + " -> ".join(nodes))
    for reference in record.evidence:
        print(f"  {reference.id}: {reference.path}:{reference.start_line}-{reference.end_line} ({reference.kind})")
    for response in record.tool_results:
        if response.data and response.data.get("content"):
            print(response.data["content"])


def test_repeated_query_reuses_current_finding_cache_and_provenance(finding, tools, caplog):
    caplog.set_level("INFO", logger="server.finding-resolution")
    def decide(context):
        if len(context["history"]) < 2:
            return ask(context)
        return close(context)
    state, model = run(finding, tools, decide)
    record = state["investigations"][0]
    assert record.consumption.tool_calls == len(record.tool_results) == 1
    assert model.contexts[2]["current_evidence"] == model.contexts[3]["current_evidence"]
    events = [json.loads(item.getMessage().split("finding_resolution_trace ", 1)[1]) for item in caplog.records
        if item.getMessage().startswith("finding_resolution_trace ") and '"transition": "tool_result"' in item.getMessage()]
    assert [event["cached"] for event in events] == [False, True]
    assert events[0]["tool_call_id"] == events[1]["tool_call_id"]


def test_missing_original_path_can_be_located_by_repository_search(finding, tools):
    original = finding.model_copy(update={"components": ["old/service.py"]}, deep=True)
    def decide(context):
        views = context["tool_results"]
        if not views:
            return ask(context, arguments={"path": "old/service.py"})
        assert views[0]["status"] == "error" and views[0]["error"]["code"]
        if len(views) == 1:
            return ask(context, "search_repository_text", {"query": "def use"})
        if len(views) == 2:
            assert "service.py" in json.dumps(views[1]["data"])
            return ask(context)
        assert "def use" in views[2]["data"]["content"]
        return close(context)
    state, _ = run(original, tools, decide, max_iterations=4)
    record = state["investigations"][0]
    assert record.stop_reason == "evidence_collected" and record.evidence and record.limitations
    assert any(reference.kind == "source" and reference.path == "service.py" for reference in record.evidence)
    assert record.finding.components == ["old/service.py"] and record.tool_results[0].status == "error"


def test_evidence_and_history_are_isolated_across_findings(finding, tools):
    def decide(context):
        if not context["tool_results"]:
            assert context["current_evidence"] == [] and context["history"] == []
            return ask(context)
        assert all(turn["finding_id"] == context["finding"]["id"] for turn in context["history"])
        return close(context)
    request = FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path,
        findings=[finding, finding.model_copy(update={"id": "f2"})])
    state = asyncio.run(planning_agent(Investigator(decide)).run(request, tools=tools))
    first, second = state["investigations"]
    assert {reference.id for reference in first.evidence}.isdisjoint(reference.id for reference in second.evidence)
    assert first.tool_results[0].tool_call_id != second.tool_results[0].tool_call_id
    assert first.consumption == second.consumption
    assert state["query_cache"] == {} and state["history"] == []


@pytest.mark.parametrize("kind", ["historical", "unknown", "missing_source", "status", "invalid_tool"])
def test_investigation_validation_does_not_accept_unverified_work(finding, tools, kind):
    def decide(context):
        response = close(context)
        if kind in {"historical", "unknown"}:
            response["evidence_ids"] = ["historical-evidence" if kind == "historical" else "invented"]
        elif kind == "status":
            response["status"] = "resolved"
        elif kind == "invalid_tool":
            return ask(context, "write_file", {"path": "service.py"})
        return response
    state, _ = run(finding, tools, decide, max_schema_retries=0)
    record = state["investigations"][0]
    assert record.stop_reason == "model_or_schema_error" and record.limitations and not record.evidence
    assert state["consumption"].tool_calls == 0


@pytest.mark.parametrize("limit", ["iterations", "tools", "calls", "no_progress"])
def test_limits_retain_collected_evidence_without_infinite_loops(finding, tools, limit):
    settings = {"max_schema_retries": 0}
    if limit == "iterations":
        settings["max_iterations"] = 1
    elif limit == "tools":
        settings["max_tool_calls"] = 1
    elif limit == "calls":
        settings.update(max_model_calls=4, max_iterations=10)
    else:
        settings["max_iterations"] = 10
    def decide(context):
        if limit == "tools" and context["tool_results"]:
            return ask(context, "find_symbols", {"file_path": "service.py"})
        return ask(context)
    state, _ = run(finding, tools, decide, **settings)
    record = state["investigations"][0]
    assert record.evidence and record.limitations and record.consumption.tool_calls == 1
    assert record.stop_reason == {"iterations": "investigation_iteration_limit", "tools": "tool_call_limit",
        "calls": "evaluation_call_reserve", "no_progress": "no_investigation_progress"}[limit]
    assert record.consumption.model_calls <= (4 if limit == "calls" else 5)


def test_token_admission_after_retrieval_preserves_evidence(finding, tools, monkeypatch, finite_token_budget):
    model = Investigator(lambda context: ask(context) if not context["tool_results"] else close(context))
    agent = planning_agent(model)
    request = FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path, findings=[finding])
    execution = agent.execution_type(model, agent.config, tools, request)
    execute = tools.execute
    def exhaust_remaining_tokens(*args, **kwargs):
        response = execute(*args, **kwargs)
        # Simulate consumption elsewhere in the shared budget before the next call.
        execution.token_limit = execution.tokens + 1
        return response
    monkeypatch.setattr(tools, "execute", exhaust_remaining_tokens)
    async def invoke():
        with execution.timing.stage("token-test"):
            return await execution.graph.ainvoke(execution.initial_state())
    state = asyncio.run(invoke())
    record = state["investigations"][0]
    assert record.stop_reason == "token_limit" and record.evidence
    assert record.consumption.model_calls == 2 and record.consumption.tool_calls == 1


def test_other_finding_evidence_cannot_be_cited(finding, tools):
    previous_ids = []
    def decide(context):
        if context["finding"]["id"] == finding.id:
            if not context["tool_results"]:
                return ask(context)
            previous_ids.extend(reference["id"] for reference in context["current_evidence"])
            return close(context)
        assert context["current_evidence"] == []
        return close(context, evidence_ids=previous_ids, limitations=["No source was read for this finding."])
    request = FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path,
        findings=[finding, finding.model_copy(update={"id": "f2"})])
    state = asyncio.run(planning_agent(Investigator(decide), max_schema_retries=0).run(request, tools=tools))
    assert state["investigations"][0].evidence
    second = state["investigations"][1]
    assert second.stop_reason == "model_or_schema_error" and second.evidence == []


def test_access_error_is_returned_to_model_and_retained_without_a_verdict(finding, tools):
    def decide(context):
        if not context["tool_results"]:
            return ask(context, arguments={"path": "../outside.py"})
        assert context["tool_results"][0]["status"] == "error"
        assert context["current_evidence"] == []
        return close(context, limitations=["Repository access policy prevented inspection."])
    state, _ = run(finding, tools, decide)
    record = state["investigations"][0]
    assert record.stop_reason == "investigation_limited" and record.evidence == []
    assert record.tool_results[0].error and record.limitations and not hasattr(record, "status")


def test_time_limit_after_retrieval_keeps_collected_source(finding, tools, monkeypatch):
    model = Investigator(lambda context: ask(context))
    agent = planning_agent(model)
    request = FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path, findings=[finding])
    execution = agent.execution_type(model, agent.config, tools, request)
    remaining = execution.remaining_seconds
    monkeypatch.setattr(execution, "remaining_seconds", lambda: 0 if tools.retrieved_evidence else remaining())
    async def invoke():
        with execution.timing.stage("deadline-test"):
            return await execution.graph.ainvoke(execution.initial_state())
    state = asyncio.run(invoke())
    record = state["investigations"][0]
    assert record.stop_reason == "time_limit" and record.evidence
    assert record.consumption.model_calls == 2 and record.consumption.tool_calls == 1
