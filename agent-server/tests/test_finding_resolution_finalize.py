"""Deterministic graph closure and original-ID coverage, including interrupted runs."""

import asyncio

import pytest
import test_finding_resolution as shared
from test_finding_resolution_evaluation import execute, verdict

from server.agents.finding_resolution import (
    FindingResolutionRequest,
    FindingResolutionResult,
)
from server.agents.finding_resolution.schemas import FindingVerificationResult

finding = shared.finding
tools = shared.tools


def execution_for(findings, tools):
    model = shared.PlanningModel()
    agent = shared.planning_agent(model)
    request = FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path, findings=findings)
    return agent.execution_type(model, agent.config, tools, request)


def test_complete_finalization_reuses_decisions_without_extra_calls(finding, tools):
    findings = [finding, finding.model_copy(update={"id": "second"})]
    state, model, updates = execute(findings, tools, verdict)
    final = state["final_result"]
    assert [item.finding_id for item in final.results] == [item.id for item in findings]
    assert [item.status for item in final.results] == ["persists", "persists"]
    assert all(result is evaluated for result, evaluated in zip(final.results, state["results"], strict=True))
    assert list(updates[-1]) == ["finalize"]
    assert state["consumption"].model_calls == len(model.contexts) == 8


def test_missing_results_are_completed_in_original_order_without_mutation(finding, tools, monkeypatch):
    findings = [finding, finding.model_copy(update={"id": "missing"})]
    execution = execution_for(findings, tools)
    original = execution.request.model_dump()
    state = execution.initial_state()
    result = shared.PlanningModel.evaluation({"finding": {"id": finding.id}, "current_evidence": []})["result"]
    existing = FindingVerificationResult.model_validate(result)
    state.update(results=[existing], termination_reason="time_limit")
    monkeypatch.setattr(execution, "call", lambda *args: pytest.fail("finalize must not call the model"))
    final = execution.finalize(state)["final_result"]
    assert final.results[0] is existing
    assert final.results[1].finding_id == "missing" and final.results[1].status == "inconclusive"
    assert "missing_evaluation" in final.results[1].reason and "time_limit" in final.results[1].reason
    assert final.results[1].evidence_ids == [] and execution.request.model_dump() == original
    FindingResolutionResult.model_validate(final.model_dump(), context={"request": execution.request})


@pytest.mark.parametrize("failure", ["historical", "duplicate", "blank", "no_source"])
def test_invalid_decisions_fall_back_without_unverifiable_citations(finding, tools, failure):
    execution = execution_for([finding], tools)
    state = execution.initial_state()
    candidate = FindingVerificationResult(finding_id=finding.id, status="inconclusive", reason="Current evidence unavailable.", evidence_ids=[])
    if failure == "historical":
        candidate = candidate.model_copy(update={"evidence_ids": finding.evidence_ids})
    elif failure == "blank":
        candidate = candidate.model_copy(update={"reason": " "})
    elif failure == "no_source":
        candidate = candidate.model_copy(update={"status": "resolved"})
    state["results"] = [candidate, candidate] if failure == "duplicate" else [candidate]
    final = execution.finalize(state)["final_result"]
    assert len(final.results) == 1 and final.results[0].status == "inconclusive"
    assert "No valid evaluation" in final.results[0].reason and final.results[0].evidence_ids == []


@pytest.mark.parametrize("stop", ["model_call_limit", "token_limit", "time_limit", "tool_call_limit", "model_or_schema_error"])
def test_global_stops_reach_finalize_and_cover_unstarted_findings(finding, tools, stop):
    findings = [finding, finding.model_copy(update={"id": "unstarted"})]
    execution = execution_for(findings, tools)
    execution.stop = stop
    with execution.timing.stage("finalize-test"):
        state = asyncio.run(execution.graph.ainvoke(execution.initial_state()))
    assert [item.finding_id for item in state["final_result"].results] == [item.id for item in findings]
    assert all(item.status == "inconclusive" and stop in item.reason for item in state["final_result"].results)
    assert state["consumption"].model_calls == 0


def test_local_evaluation_error_still_finalizes_later_findings(finding, tools):
    findings = [finding, finding.model_copy(update={"id": "later"})]
    state, _, _ = execute(findings, tools, lambda context: "bad JSON" if context["finding"]["id"] == finding.id else verdict(context))
    assert [item.status for item in state["final_result"].results] == ["inconclusive", "persists"]


def test_empty_request_has_valid_empty_final_result(tools):
    state = asyncio.run(shared.planning_agent(shared.PlanningModel()).run(
        FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path, findings=[]), tools=tools))
    assert state["final_result"].model_dump() == {"results": []}


def test_finalization_retains_only_current_finding_citations(finding, tools):
    state, _, _ = execute(finding, tools, verdict)
    execution = execution_for([finding, finding.model_copy(update={"id": "other"})], tools)
    # An existing decision cannot lend its current source IDs to another finding.
    candidate = state["results"][0].model_copy(update={"finding_id": "other"})
    state["results"].append(candidate)
    final = execution.finalize(state)["final_result"]
    assert final.results[0].status == "persists"
    assert final.results[1].status == "inconclusive" and final.results[1].evidence_ids == []


def test_missing_evaluation_retains_verifiable_source_without_deciding_resolution(finding, tools):
    state, _, _ = execute(finding, tools, verdict)
    execution = execution_for([finding], tools)
    state["results"] = []
    final = execution.finalize(state)["final_result"]
    assert final.results[0].status == "inconclusive" and "missing_evaluation" in final.results[0].reason
    assert set(final.results[0].evidence_ids) == {item.id for item in state["investigations"][0].evidence}
