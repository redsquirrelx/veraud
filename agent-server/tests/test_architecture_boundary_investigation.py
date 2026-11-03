"""Offline graph regressions: model decisions are not treated as final findings."""

import asyncio
import json

import pytest
from langchain_core.messages import AIMessage
from test_architecture_boundary_planning import cycles, tools_for

from config.agents import InvestigationConfig
from config.agents.catalog import describe_agent_config, describe_developer_agent_config
from server.agents.maintainability.modularity.architecture_boundary import (
    ArchitectureBoundaryAgent,
    AuditRequest,
    BoundaryConfig,
)
from server.agents.maintainability.modularity.architecture_boundary.execution import (
    BoundaryExecution,
)
from server.agents.maintainability.modularity.architecture_boundary.schemas import (
    BoundaryResult,
)
from server.blackboard.identity import AuditIdentity
from server.blackboard.impls.memory import MemoryBlackboard
from server.runtimes.repository.context import RepositoryContext
from server.runtimes.repository.schemas import ExecutionBudget, RepositoryInput
from server.runtimes.repository.tools import RepositoryToolset


class Investigator:
    def __init__(self, decide):
        self.decide = decide
        self.contexts = []

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages, **kwargs):
        context = json.loads(messages[1].content)
        self.contexts.append(context)
        value = ({"opportunity_ids": [item["id"] for item in context["opportunities"]]}
            if "opportunities" in context else self.decide(context))
        return AIMessage(content=json.dumps(value), usage_metadata={"input_tokens": 100, "output_tokens": 100, "total_tokens": 200})


def query(tool, arguments, **extra):
    return {"action": "tools", "queries": [{"tool": tool, "arguments": arguments,
        "reason": "Resolve the current boundary question using the relevant implementation.", **extra}]}


def read_scope(context):
    return {"action": "tools", "queries": [{"tool": "get_source_excerpt", "arguments": {"path": path},
        "reason": "Inspect the code declaring and using the candidate boundary."} for path in context["investigation"]["scope"][:4]]}


def close(context, status="no_finding", **extra):
    refs = context["evidence"]
    return {"action": "close", "conclusion": {"investigation_id": context["investigation"]["id"],
        "status": status, "summary": "Scoped boundary investigation.",
        "justification": "Inspected source does not establish a forbidden dependency; a cycle alone is not a violation.",
        "components": list(dict.fromkeys(ref["path"] for ref in refs)),
        "evidence_ids": [ref["id"] for ref in refs], **extra}}


def run(tools, decide, request=None, **overrides):
    # Isolate model-directed retrieval and negative provenance cases here.
    # test_architecture_boundary_citations exercises the unmodified full graph
    # with production automatic initial retrieval, first singly then in sequence.
    model = Investigator(decide)
    config = BoundaryConfig(**({"provider_request_interval_seconds": 0, "max_output_tokens": 1800,
        "max_context_characters": 100_000, "max_total_tokens": 100_000,
        "max_schema_retries": 0} | overrides))
    execution = BoundaryExecution(model, config, tools, request or AuditRequest())
    execution._initial_queries = lambda task: []
    async def invoke():
        with execution.timing.stage("investigation"):
            return await execution.graph.ainvoke(execution.initial_state(), {"recursion_limit": 200})
    state = asyncio.run(invoke())
    assert BoundaryResult.model_validate_json(state["result"].model_dump_json()) == state["result"]
    assert not state["result"].findings and not state["result"].hypotheses
    return state, model, execution


def test_graph_iterates_multiple_queries_and_tasks_in_sequence(tmp_path):
    tools = tools_for(tmp_path, cycles(count=2))
    def decide(context):
        paths = context["investigation"]["scope"]
        if len(context["tool_results"]) < 2:
            return query("get_source_excerpt", {"path": paths[len(context["tool_results"])]})
        return close(context)
    state, model, execution = run(tools, decide)
    results = state["result"].investigation_results
    assert len(results) == 2 and all(item.status == "no_finding" for item in results), [(item.status, item.limitations) for item in results]
    ids = [context["investigation"]["id"] for context in model.contexts if "investigation" in context]
    assert ids == [results[0].investigation_id] * 3 + [results[1].investigation_id] * 3
    assert state["current_investigation"] == 2 and state["next_phase"] == "synthesis"
    assert state["result"].next_phase == "synthesis"
    assert state["result"].tool_calls == 4 and state["result"].model_calls == 7
    assert state["result"].accounted_tokens == 1400
    assert state["consumption"]["tool_calls"] == 4
    edges = {(edge.source, edge.target) for edge in execution.graph.get_graph().edges}
    assert ("tools", "investigate") in edges and ("investigate", "tools") in edges
    assert "synthesis" not in execution.graph.get_graph().nodes
    assert len(state["result"].investigation_progress) == 2
    for result in results:
        assert result.evidence_ids and set(result.evidence_ids) <= {ref.id for ref in state["evidence"]}
    assert all(ref.snapshot_hash == state["result"].snapshot_hash and ref.content_hash and ref.tool_call_id
        for ref in state["result"].evidence)


def test_finding_candidate_requires_real_source_symbols_and_returned_relationships(tmp_path):
    tools = tools_for(tmp_path, {"parts0/a.py": "from .b import _f\ndef f(): return _f()\n",
        "parts0/b.py": "from .a import f\n__all__ = ['public']\ndef public(): return 1\ndef _f(): return 2\n"})
    def decide(context):
        if not context["tool_results"]:
            return read_scope(context)
        if not context["reference_catalog"]["examined_relationships"]:
            file_id = next(ref["file_id"] for ref in context["evidence"] if ref["path"].endswith("a.py"))
            return query("list_relationships", {"source_id": file_id})
        refs = context["evidence"]
        relation = context["reference_catalog"]["examined_relationships"][0]
        symbol_ids = list(dict.fromkeys(symbol for ref in refs if ref["kind"] == "source" for symbol in ref["symbol_ids"]))
        candidate = {"id": "private-bypass", "title": "Direct access outside the declared export interface",
            "description": "a.py imports b._f despite b exposing public via __all__.",
            "criterion_id": context["criteria"][0]["id"], "kind": "design_observation",
            "components": ["parts0/a.py", "parts0/b.py"], "evidence_ids": [ref["id"] for ref in refs],
            "justification": "Both the export declaration and the direct import were inspected.",
            "modularity_impact": "The consuming path may bypass the declared interface.",
            "severity": "low", "confidence": .7, "recommendation": "Check whether the public entry is the intended access path.",
            "inferred_boundary": "The __all__ declaration names public, not _f.",
            "contradictory_dependency": "a imports _f directly from b.",
            "technical_basis": "Source-backed export declaration and import/use of _f.",
            "symbol_ids": symbol_ids, "relationship_ids": [relation["id"]]}
        return close(context, "finding_candidate", candidates=[candidate], symbol_ids=symbol_ids,
            relationship_ids=[relation["id"]])
    state, _, _ = run(tools, decide)
    assert len(state["result"].candidates) == 1
    assert state["result"].investigation_results[0].status == "finding_candidate"
    candidate = state["result"].candidates[0]
    assert candidate.symbol_ids and candidate.relationship_ids
    assert set(candidate.relationship_ids) <= {row.id for row in tools.accessible_snapshot.relationships}
    assert not state["result"].findings and state["result"].evaluation_evidence_status == "not_evaluated"


@pytest.mark.parametrize("invented", ["evidence", "symbol", "relationship", "component"])
def test_invented_references_fail_closed_without_losing_other_tasks(tmp_path, invented):
    tools = tools_for(tmp_path, cycles(count=2))
    def decide(context):
        if not context["tool_results"]:
            return read_scope(context)
        extra = {"evidence": {"evidence_ids": ["invented"]}, "symbol": {"symbol_ids": ["invented"]},
            "relationship": {"relationship_ids": ["invented"]}, "component": {"components": ["invented.py"]}}[invented]
        return close(context, **extra)
    state, _, _ = run(tools, decide)
    assert len(state["result"].investigation_results) == 2
    assert all(result.status == "inconclusive" and not result.candidates for result in state["result"].investigation_results)
    assert state["result"].evidence


def test_metadata_alone_cannot_be_no_finding(tmp_path):
    tools = tools_for(tmp_path, cycles())
    def decide(context):
        if not context["tool_results"]:
            return query("find_symbols", {"file_path": context["investigation"]["scope"][0]})
        return close(context)
    state, _, _ = run(tools, decide)
    assert state["result"].investigation_results[0].status == "inconclusive"


def test_inconclusive_is_valid_without_fabricated_evidence(tmp_path):
    tools = tools_for(tmp_path, cycles())
    state, _, _ = run(tools, lambda context: close(context, "inconclusive", limitations=["No boundary declaration identified."]))
    result = state["result"].investigation_results[0]
    assert result.status == "inconclusive" and not result.evidence_ids and not result.candidates
    assert state["result"].tool_calls == 0


def test_duplicate_queries_are_reused_and_stall_is_bounded(tmp_path):
    tools = tools_for(tmp_path, cycles())
    state, _, _ = run(tools, lambda context: query("get_source_excerpt", {"path": context["investigation"]["scope"][0]}))
    assert state["result"].tool_calls == 1
    assert len(state["query_cache"]) == 1
    assert state["result"].investigation_results[0].status == "inconclusive"
    assert "no_investigation_progress" in state["result"].investigation_results[0].limitations
    assert state["result"].model_calls == 4


def test_query_cache_is_reused_between_investigations(tmp_path):
    tools = tools_for(tmp_path, cycles(count=2))
    shared = "parts0/a.py"
    def decide(context):
        if not context["tool_results"]:
            return query("get_source_excerpt", {"path": shared}, scope_expansion="Compare the already inspected access pattern with this boundary.")
        return close(context)
    state, _, _ = run(tools, decide)
    assert state["result"].tool_calls == 1
    assert [result.status for result in state["result"].investigation_results] == ["no_finding", "no_finding"]
    assert state["result"].investigation_results[0].evidence_ids == state["result"].investigation_results[1].evidence_ids


@pytest.mark.parametrize("limits", [{"max_calls_per_investigation": 1}, {"max_tools_per_investigation": 0}])
def test_task_limits_preserve_fairness_and_terminate(tmp_path, limits):
    tools = tools_for(tmp_path, cycles(count=3))
    state, _, _ = run(tools, lambda context: read_scope(context), **limits)
    assert len(state["result"].investigation_results) == 3
    assert all(result.status == "inconclusive" for result in state["result"].investigation_results)
    assert state["result"].model_calls <= 10 and state["result"].tool_calls <= 6
    if limits.get("max_tools_per_investigation") == 0:
        assert state["result"].tool_calls == 0


def test_tool_count_caps_are_disabled_without_disabling_usage_or_other_limits(tmp_path):
    contents = {path: content + "\n".join(f"value{i} = {i}" for i in range(40)) + "\n"
        for path, content in cycles().items()}
    original = tools_for(tmp_path, contents)
    snapshot = original.accessible_snapshot
    tools = RepositoryToolset(RepositoryContext(snapshot, RepositoryInput(snapshot_hash=snapshot.repository.snapshot_hash,
        budget=ExecutionBudget(max_model_calls=16, max_tool_calls=1, max_input_tokens_per_call=50_000,
            max_total_tokens=200_000, max_tokens_per_objective=200_000))), workspace_root=tmp_path)
    next_line = 1
    def decide(context):
        nonlocal next_line
        assert context["remaining_tool_calls"] is None
        if next_line > 28:
            return close(context)
        batch = [{"tool": "get_source_excerpt", "arguments": {"path": context["investigation"]["scope"][0],
            "start_line": line, "end_line": line}, "reason": "Inspect the next concrete implementation range."}
            for line in range(next_line, next_line + 4)]
        next_line += 4
        return {"action": "tools", "queries": batch}
    state, model, execution = run(tools, decide, max_tool_calls=1, max_calls_per_investigation=10, unlimited_model_calls=False,
        max_tokens_per_investigation=150_000, max_total_tokens=200_000)
    assert state["result"].tool_calls == tools.budget_usage.tool_calls == 28
    assert tools.tool_call_limit is None
    assert state["result"].investigation_results[0].status == "no_finding"
    assert model.contexts[0]["budget"]["remaining_tool_calls"] is None
    assert execution.call_limit == 16 and execution.token_limit == 200_000
    assert execution.config.max_seconds_per_investigation == 60
    json.dumps(model.contexts, allow_nan=False)  # No Infinity sentinel leaks into model JSON.


def test_finite_tool_limits_can_be_explicitly_reenabled(tmp_path):
    tools = tools_for(tmp_path, cycles())
    state, _, _ = run(tools, lambda context: read_scope(context) if not context["tool_results"] else close(context),
        unlimited_tool_calls=False, max_tool_calls=1)
    assert state["result"].tool_calls == 1
    assert tools.tool_call_limit == tools.context.input.budget.max_tool_calls
    assert "investigation_tool_limit" in state["result"].investigation_results[0].limitations


def test_unlimited_default_is_boundary_only_and_repository_defaults_remain_limited(tmp_path):
    assert BoundaryConfig().unlimited_tool_calls is True
    assert BoundaryConfig().unlimited_model_calls is True
    assert BoundaryConfig().max_calls_per_investigation is None
    assert BoundaryConfig().max_tools_per_investigation is None
    assert InvestigationConfig().unlimited_tool_calls is False
    assert InvestigationConfig().unlimited_model_calls is False
    panel = describe_developer_agent_config("architecture_boundary")
    assert panel["defaults"]["unlimited_tool_calls"] is True
    assert panel["defaults"]["unlimited_model_calls"] is True
    assert panel["defaults"]["max_tools_per_investigation"] is None
    assert "unlimited_tool_calls" not in describe_agent_config("architecture_boundary")["config_schema"]["properties"]
    original = tools_for(tmp_path, cycles())
    snapshot = original.accessible_snapshot
    tools = RepositoryToolset(RepositoryContext(snapshot, RepositoryInput(snapshot_hash=snapshot.repository.snapshot_hash,
        budget=ExecutionBudget(max_tool_calls=1))), workspace_root=tmp_path)
    assert tools.execute("find_symbols", {"file_path": "parts0/a.py"}, tool_call_id="first").status == "ok"
    assert tools.execute("find_symbols", {"file_path": "parts0/b.py"}, tool_call_id="second").error.code == "tool_budget_exhausted"


def test_global_model_budget_marks_remaining_tasks_inconclusive(tmp_path):
    tools = tools_for(tmp_path, cycles(count=5))
    state, _, _ = run(tools, lambda context: read_scope(context), max_model_calls=4, unlimited_model_calls=False)
    assert state["result"].model_calls == 4
    assert len(state["result"].investigation_results) == 5
    assert all(result.status == "inconclusive" for result in state["result"].investigation_results)


def test_model_and_task_call_caps_are_disabled_including_indirect_graph_step_cap(tmp_path):
    contents = {path: content + "\n".join(f"value{i} = {i}" for i in range(70)) + "\n"
        for path, content in cycles().items()}
    original = tools_for(tmp_path, contents)
    snapshot = original.accessible_snapshot
    tools = RepositoryToolset(RepositoryContext(snapshot, RepositoryInput(snapshot_hash=snapshot.repository.snapshot_hash,
        budget=ExecutionBudget(max_model_calls=1, max_input_tokens_per_call=50_000,
            max_total_tokens=200_000, max_tokens_per_objective=200_000))), workspace_root=tmp_path)
    next_line = 41  # Inspect new ranges, not the automatically delivered first 40 lines.
    def decide(context):
        nonlocal next_line
        assert context["remaining_investigation_calls"] is None
        if next_line > 60:
            return close(context)
        line = next_line
        next_line += 1
        return query("get_source_excerpt", {"path": context["investigation"]["scope"][0],
            "start_line": line, "end_line": line})
    model = Investigator(decide)
    config = BoundaryConfig(provider_request_interval_seconds=0, max_model_calls=4,
        max_output_tokens=1800, max_total_tokens=200_000, max_tokens_per_investigation=150_000,
        provider_rate_limits={"requests_per_minute": None, "tokens_per_minute": None})
    result = asyncio.run(ArchitectureBoundaryAgent(model, config).run(tools))
    assert result.model_calls == 22  # Exceeds both the former total and per-task caps.
    assert result.tool_calls == 23  # Includes bootstrap; exceeds the former 36 graph steps.
    assert result.investigation_results[0].status == "no_finding"
    assert result.accounted_tokens == 4400
    assert model.contexts[0]["budget"]["remaining_model_calls"] is None
    json.dumps(model.contexts, allow_nan=False)


def test_tools_errors_are_visible_and_do_not_prevent_next_task(tmp_path):
    tools = tools_for(tmp_path, cycles(count=2))
    def decide(context):
        if not context["tool_results"]:
            return query("get_source_excerpt", {"path": context["investigation"]["scope"][0], "start_line": 999})
        assert context["tool_results"][0]["status"] == "error"
        return close(context, "inconclusive", limitations=["Requested source range unavailable."])
    state, _, _ = run(tools, decide)
    assert len(state["result"].investigation_results) == 2
    assert state["result"].tool_calls == 2
    assert any("invalid_source_range" in item for item in state["result"].limitations)


def test_scope_expansion_requires_reason_and_documentation_is_unavailable(tmp_path):
    tools = tools_for(tmp_path, cycles() | {"external/impl.py": "def f(): return 1\n", "docs/rules.py": "RULE='forbidden'\n"})
    state, _, _ = run(tools, lambda context: query("get_source_excerpt", {"path": "external/impl.py"}))
    assert state["result"].tool_calls == 0
    assert state["result"].investigation_results[0].status == "inconclusive"


@pytest.mark.parametrize("path", ["docs/rules.py", "fixtures/fake.py", "README.md"])
def test_documentation_and_nonproduction_cannot_be_read_by_default(tmp_path, path):
    tools = tools_for(tmp_path, cycles() | {path: "RULE = 'not architectural evidence'\n"})
    state, _, _ = run(tools, lambda context: query("get_source_excerpt", {"path": path}, scope_expansion="Inspect an alleged boundary declaration."))
    assert state["result"].tool_calls == 0
    assert state["result"].investigation_results[0].status == "inconclusive"


def test_source_metadata_filters_nonproduction_rows(tmp_path):
    tools = tools_for(tmp_path, cycles() | {"fixtures/fake.py": "def forbidden_fixture_symbol(): pass\n"})
    def decide(context):
        if not context["tool_results"]:
            return query("find_symbols", {}, scope_expansion="Find the concrete declaration used by the boundary.")
        assert all("forbidden_fixture_symbol" != row["name"] for row in context["tool_results"][0]["data"]["items"])
        return close(context, "inconclusive", limitations=["Metadata alone does not establish the boundary."])
    state, _, _ = run(tools, decide)
    assert state["result"].tool_calls == 1


def test_per_task_token_admission_does_not_consume_calls_for_later_tasks(tmp_path):
    tools = tools_for(tmp_path, cycles(count=3))
    state, model, _ = run(tools, lambda context: read_scope(context), max_tokens_per_investigation=1000)
    assert len(model.contexts) == state["result"].model_calls == 1  # planning only
    assert len(state["result"].investigation_results) == 3
    assert all("investigation_token_limit" in result.limitations for result in state["result"].investigation_results)


def test_explicit_fixture_target_is_preserved_during_investigation(tmp_path):
    tools = tools_for(tmp_path, cycles("fixtures"))
    state, _, _ = run(tools, lambda context: read_scope(context) if not context["tool_results"] else close(context),
        request=AuditRequest(targets=["fixtures"]))
    assert state["result"].investigation_results[0].status == "no_finding"
    assert all(ref.path.startswith("fixtures/") for ref in state["result"].evidence)


def test_schema_corrections_cannot_escape_per_task_call_limit(tmp_path):
    tools = tools_for(tmp_path, cycles(count=2))
    state, _, _ = run(tools, lambda context: close(context, evidence_ids=["invented"]),
        max_schema_retries=2, max_calls_per_investigation=1)
    assert state["result"].model_calls == 3
    assert len(state["result"].investigation_results) == 2
    assert all(progress["model_calls"] == 1 for progress in state["result"].investigation_progress)


def test_tool_exception_is_sanitized_and_retained_as_a_limitation(tmp_path, monkeypatch):
    tools = tools_for(tmp_path, cycles())
    def broken(*args, **kwargs):
        raise RuntimeError("SECRET: untrusted source must not leak through diagnostics")
    monkeypatch.setattr(tools, "execute", broken)
    state, _, _ = run(tools, lambda context: read_scope(context) if not context["tool_results"] else
        close(context, "inconclusive", limitations=["Implementation source could not be retrieved."]))
    result = state["result"].investigation_results[0]
    assert result.status == "inconclusive" and "Tool query failed: tool_execution_error" in result.limitations
    assert "SECRET" not in json.dumps(state["query_cache"])


def test_native_structured_provider_uses_same_tool_cycle(tmp_path):
    tools = tools_for(tmp_path, cycles())
    class NativeInvestigator(Investigator):
        def with_structured_output(self, schema, **kwargs):
            parent = self
            class Structured:
                async def ainvoke(self, messages, **options):
                    response = await parent.ainvoke(messages, **options)
                    return {"raw": response, "parsed": schema.model_validate_json(response.content)}
            return Structured()
    model = NativeInvestigator(lambda context: read_scope(context) if not context["tool_results"] else close(context))
    result = asyncio.run(ArchitectureBoundaryAgent(model, BoundaryConfig(provider_request_interval_seconds=0)).run(tools))
    assert result.investigation_results[0].status == "no_finding"
    assert result.model_calls == 2 and result.tool_calls == 3


def test_planning_tool_result_is_reused_without_executing_same_query_again(tmp_path):
    tools = tools_for(tmp_path, cycles())
    class DiscoveryInvestigator(Investigator):
        async def ainvoke(self, messages, **kwargs):
            context = json.loads(messages[1].content)
            if "opportunities" in context:
                value = {"opportunity_ids": [item["id"] for item in context["opportunities"]]}
                if not context["discovery_results"]:
                    value["discovery_queries"] = [{"tool": "find_symbols", "arguments": {
                        "file_path": context["opportunities"][0]["scope"][0], "limit": 3}}]
                return AIMessage(content=json.dumps(value), usage_metadata={"input_tokens": 100, "output_tokens": 100, "total_tokens": 200})
            return await super().ainvoke(messages, **kwargs)
    first_turn = True
    def decide(context):
        nonlocal first_turn
        if first_turn:
            first_turn = False
            return query("find_symbols", {"file_path": context["investigation"]["scope"][0], "limit": 3})
        return close(context)
    model = DiscoveryInvestigator(decide)
    result = asyncio.run(ArchitectureBoundaryAgent(model, BoundaryConfig(provider_request_interval_seconds=0)).run(tools))
    assert result.investigation_results[0].status == "no_finding"
    assert result.tool_calls == 4
    assert sum(item.tool == "find_symbols" for item in tools.tool_measurements) == 1
    assert not any(item.repeated for item in tools.tool_measurements)


def test_commit_mismatch_cannot_be_closed_as_no_finding(tmp_path):
    tools = tools_for(tmp_path, cycles(), transform=lambda snapshot: snapshot.model_copy(update={
        "repository": snapshot.repository.model_copy(update={"commit": "0" * 40})}))
    state, _, _ = run(tools, lambda context: read_scope(context) if not context["tool_results"] else close(context))
    assert state["result"].investigation_results[0].status == "inconclusive"
    assert state["result"].evidence
    assert all(ref.commit is None and ref.commit_verification == "unverified" for ref in state["result"].evidence)


def test_one_slow_task_times_out_without_restarting_completed_or_blocking_later_tasks(tmp_path):
    tools = tools_for(tmp_path, cycles(count=2))
    class SlowFirstTask(Investigator):
        first_id = None
        async def ainvoke(self, messages, **kwargs):
            context = json.loads(messages[1].content)
            if "investigation" in context:
                identifier = context["investigation"]["id"]
                self.first_id = self.first_id or identifier
                if identifier == self.first_id:
                    await asyncio.sleep(.1)
            return await super().ainvoke(messages, **kwargs)
    model = SlowFirstTask(lambda context: close(context, "inconclusive", limitations=["No concrete boundary was established."]))
    # Isolate timeout handling from production prompt growth: the failed request
    # is conservatively charged. Keep the same token envelope for both tasks.
    config = BoundaryConfig(provider_request_interval_seconds=0, max_seconds_per_investigation=.05,
        max_output_tokens=1800, max_schema_retries=0,
        prompts={"investigate": "Return a boundary investigation turn grounded in the supplied evidence."})
    agent = ArchitectureBoundaryAgent(model, config)
    result = asyncio.run(agent.run(tools))
    assert len(result.investigation_results) == 2
    assert "investigation_time_limit" in result.investigation_results[0].limitations
    assert "No concrete boundary was established." in result.investigation_results[1].limitations
    assert result.model_calls == 3 and result.next_phase == "synthesis"


def test_blackboard_publishes_evidence_not_provisional_candidates_as_findings(tmp_path):
    tools = tools_for(tmp_path, cycles())
    board = MemoryBlackboard()
    model = Investigator(lambda context: read_scope(context) if not context["tool_results"] else close(context))
    identity = AuditIdentity()
    agent = ArchitectureBoundaryAgent(model, BoundaryConfig(provider_request_interval_seconds=0), blackboard=board, audit_identity=identity)
    result = asyncio.run(agent.run(tools))
    assert result.investigation_results and result.evidence and not result.findings
    assert result.next_phase == "synthesis"
    assert not board.query_findings(identity.run_id)
    evidence = board.query_evidence(identity.run_id)
    assert len(evidence) == len(result.evidence)
    assert evidence[0].details["investigation"]["investigation_results"] == [item.model_dump() for item in result.investigation_results]
