"""Source range correction and bounded recovery through the actual graph."""

import asyncio
import json

import pytest
import test_finding_resolution as shared
from test_finding_resolution import planning_agent
from test_finding_resolution_investigation import Investigator, ask, close

from server.agents.finding_resolution import FindingResolutionRequest
from server.runtimes.repository.context import RepositoryContext
from server.runtimes.repository.schemas import RepositoryInput
from server.runtimes.repository.tools import RepositoryToolset, ToolRequestError
from server.services.repository_analysis import RepositoryAnalysisService

finding = shared.finding


def tools_for(root):
    snapshot = RepositoryAnalysisService().analyze_sync(root)
    return RepositoryToolset(RepositoryContext(snapshot, RepositoryInput(snapshot_hash=snapshot.repository.snapshot_hash)),
        workspace_root=root.parent)


@pytest.fixture
def tools(tmp_path):
    (tmp_path / "service.py").write_text("def use():\n    value = 1\n    return value\n", encoding="utf-8")
    return tools_for(tmp_path)


def run(finding, tools, decide, setup=None, **settings):
    request = FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path, findings=[finding])
    before = request.model_dump()
    model = Investigator(decide)
    agent = planning_agent(model, **settings)
    execution = agent.execution_type(model, agent.config, tools, request)
    if setup:
        setup(execution)
    async def invoke():
        with execution.timing.stage("source-range-test"):
            return await execution.graph.ainvoke(execution.initial_state())
    state = asyncio.run(invoke())
    assert request.model_dump() == before
    return state["investigations"][0], model


@pytest.mark.parametrize(("arguments", "expected_start"), [
    ({"path": "service.py", "start_line": 1, "end_line": 100}, 1),
    ({"path": "service.py", "start_line": 100, "end_line": 200}, 1),
    ({"path": "service.py", "start_line": 2, "end_line": 1}, 2),
    ({"path": "service.py"}, 1),
])
def test_short_files_use_actual_valid_ranges_and_return_source_to_model(finding, tools, arguments, expected_start, caplog):
    caplog.set_level("INFO", logger="server.finding-resolution")
    def decide(context):
        if not context["tool_results"]:
            return ask(context, arguments=arguments)
        view = context["tool_results"][0]
        assert view["status"] == "ok" and "return value" in view["data"]["content"]
        assert view["data"]["start_line"] == expected_start and view["data"]["end_line"] == 3
        assert context["current_evidence"] and context["current_evidence"][0]["end_line"] == 3
        return close(context)
    record, _ = run(finding, tools, decide)
    assert record.stop_reason == "evidence_collected" and record.consumption.tool_calls == 1
    assert record.history[0].queries[0].arguments == arguments  # Original request is not rewritten.
    assert set(record.history[-1].evidence_ids) == {reference.id for reference in record.evidence}
    if "end_line" in arguments:
        events = [json.loads(item.getMessage().split("finding_resolution_trace ", 1)[1]) for item in caplog.records
            if item.getMessage().startswith("finding_resolution_trace ")]
        adjusted = next(event for event in events if event["transition"] == "source_range_adjusted")
        assert adjusted["requested_arguments"]["end_line"] == arguments["end_line"]


def test_shared_tool_still_rejects_invalid_ranges_but_agent_recovers(finding, tools, monkeypatch):
    # The shared contract is unchanged. Simulate an invalid range reaching the
    # tool despite preflight, e.g. incomplete file metadata, using its real error.
    raw = tools.execute("get_source_excerpt", {"path": "service.py", "end_line": 100}, tool_call_id="raw-range")
    assert raw.error.code == "invalid_source_range" and not raw.evidence
    def decide(context):
        if not context["tool_results"]:
            return ask(context, arguments={"path": "service.py", "start_line": 2, "end_line": 100})
        assert context["tool_results"][0]["error"]["code"] == "invalid_source_range"
        assert context["tool_results"][1]["status"] == "ok"
        assert "return value" in context["tool_results"][1]["data"]["content"]
        assert context["current_evidence"]
        return close(context)
    record, _ = run(finding, tools, decide,
        setup=lambda execution: monkeypatch.setattr(execution, "_valid_source_range", lambda arguments: arguments))
    assert record.stop_reason == "evidence_collected" and record.consumption.tool_calls == 2
    assert [response.status for response in record.tool_results] == ["error", "ok"]
    assert record.tool_results[0].tool_call_id != record.tool_results[1].tool_call_id
    assert record.evidence and any("invalid_source_range" in item for item in record.limitations)


def test_empty_source_range_error_uses_text_search_then_inspects_current_consumer(finding, tmp_path):
    (tmp_path / "service.py").write_text("", encoding="utf-8")
    (tmp_path / "consumer.py").write_text("from service import use\n", encoding="utf-8")
    tools = tools_for(tmp_path)
    def decide(context):
        views = context["tool_results"]
        if not views:
            return ask(context)
        assert views[0]["error"]["code"] == "invalid_source_range"
        assert context["affected_paths"] == [{"path": "service.py", "in_current_snapshot": True}]
        assert views[1]["tool_name"] == "search_repository_text" and "consumer.py" in json.dumps(views[1]["data"])
        if len(views) == 2:
            return ask(context, arguments={"path": "consumer.py"})
        assert "from service import use" in views[2]["data"]["content"]
        return close(context, limitations=["The empty original file does not establish resolution; consumers require evaluation."])
    record, _ = run(finding, tools, decide)
    assert record.consumption.tool_calls == 3 and record.evidence and not hasattr(record, "status")
    assert any(reference.path == "consumer.py" and reference.kind == "source" for reference in record.evidence)


def test_recovery_respects_tool_budget_and_does_not_claim_absence(finding, tools, monkeypatch):
    record, model = run(finding, tools, lambda context: ask(context, arguments={"path": "service.py", "end_line": 100}),
        setup=lambda execution: monkeypatch.setattr(execution, "_valid_source_range", lambda arguments: arguments),
        max_tool_calls=1)
    assert record.stop_reason == "tool_call_limit" and record.consumption.tool_calls == 1
    assert len(model.contexts) == 3 and record.evidence == [] and record.limitations
    assert record.tool_results[0].error.code == "invalid_source_range" and not hasattr(record, "status")


def test_repeated_oversized_requests_reuse_corrected_range_cache(finding, tools):
    def decide(context):
        if len(context["history"]) < 2:
            return ask(context, arguments={"path": "service.py", "end_line": 100})
        return close(context)
    record, model = run(finding, tools, decide)
    assert record.consumption.tool_calls == 1 and len(record.tool_results) == 1
    assert model.contexts[2]["current_evidence"] == model.contexts[3]["current_evidence"]


def test_fallback_attempt_is_bounded_when_range_errors_persist(finding, tools, monkeypatch):
    query = tools._query
    def unavailable_range(name, arguments):
        if name == "get_source_excerpt":
            raise ToolRequestError("invalid_source_range", "The retained range is unavailable.")
        return query(name, arguments)
    monkeypatch.setattr(tools, "_query", unavailable_range)
    def decide(context):
        if not context["tool_results"]:
            return ask(context, arguments={"path": "service.py", "end_line": 100})
        assert len(context["tool_results"]) == 2 and context["current_evidence"] == []
        return close(context, limitations=["Requested and corrected source ranges remain unavailable; no resolution can be inferred."])
    record, _ = run(finding, tools, decide)
    assert record.consumption.tool_calls == 2 and record.stop_reason == "investigation_limited" and not record.evidence
