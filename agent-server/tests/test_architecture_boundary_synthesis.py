"""Lossless synthesis and deterministic audit-envelope regressions."""

import asyncio

import pytest
from test_architecture_boundary_citations import Model, audit, conclusion
from test_architecture_boundary_planning import cycles, tools_for

from server.agents.maintainability.modularity.architecture_boundary import (
    AuditRequest,
    BoundaryConfig,
)
from server.agents.maintainability.modularity.architecture_boundary.execution import (
    BoundaryExecution,
)
from server.agents.maintainability.modularity.architecture_boundary.schemas import (
    BoundaryCandidate,
    BoundaryInvestigationResult,
    BoundaryResult,
)
from server.agents.maintainability.modularity.architecture_boundary.synthesis import (
    consolidate_candidates,
)


def candidate(**changes):
    return BoundaryCandidate(**({
        "id": "local", "title": "Possible interface bypass", "description": "The consumer reads private state.",
        "criterion_id": "architectural-boundaries", "kind": "design_observation", "components": ["a.py", "b.py"],
        "evidence_ids": ["e1"], "justification": "The export and its use disagree.",
        "modularity_impact": "Implementation state is exposed.", "severity": "medium", "confidence": .7,
        "recommendation": "Use the exported accessor.", "inferred_boundary": "b exports an accessor, not its state.",
        "contradictory_dependency": "a reads b's private state.", "technical_basis": "Export and consuming read.",
        "symbol_ids": ["s1", "s2"], "relationship_ids": ["r1"],
    } | changes))


def investigation(identifier, candidates=(), status="finding_candidate", **changes):
    return BoundaryInvestigationResult(investigation_id=identifier, status=status,
        summary="Original scoped conclusion.", justification="Original reasoning, not a synthesized judgment.",
        candidates=list(candidates), **changes)


def test_exact_duplicates_combine_evidence_and_origins_without_mutating_conclusions():
    original = [investigation("i1", [candidate()]), investigation("i2", [candidate(
        id="other-local", components=["b.py", "a.py"], symbol_ids=["s2", "s1"], evidence_ids=["e2", "e1"])])]
    before = [item.model_dump() for item in original]
    candidates, origins = consolidate_candidates(original)
    assert len(candidates) == 1 and candidates[0].evidence_ids == ["e1", "e2"]
    assert candidates[0].model_dump(exclude={"evidence_ids"}) == candidate().model_dump(exclude={"evidence_ids"})
    assert [origin.model_dump() for origin in origins["local"]] == [
        {"investigation_id": "i1", "candidate_id": "local"},
        {"investigation_id": "i2", "candidate_id": "other-local"}]
    assert [item.model_dump() for item in original] == before
    assert consolidate_candidates(original) == (candidates, origins)


@pytest.mark.parametrize("difference", [
    {"inferred_boundary": "A different boundary."}, {"contradictory_dependency": "b reads a instead."},
    {"relationship_ids": ["r2"]}, {"criterion_id": "different-criterion"},
    {"severity": "high"}, {"confidence": .8}, {"justification": "A different assessment."},
])
def test_shared_paths_and_local_ids_do_not_merge_different_claims(difference):
    results = [investigation("i1", [candidate()]), investigation("i2", [candidate(**difference)])]
    candidates, origins = consolidate_candidates(results)
    assert len(candidates) == 2 and len({item.id for item in candidates}) == 2
    assert candidates[1].model_dump(exclude={"id"}) == candidate(**difference).model_dump(exclude={"id"})
    assert origins[candidates[1].id][0].investigation_id == "i2"
    assert origins[candidates[1].id][0].candidate_id == "local"


def test_generated_ids_do_not_collide_with_existing_model_ids():
    first = investigation("i1", [candidate()])
    second = investigation("i2", [candidate(severity="high")])
    colliding_id = consolidate_candidates([first, second])[0][1].id
    third = investigation("i3", [candidate(id=colliding_id, title="A third concern")])
    candidates, origins = consolidate_candidates([first, second, third])
    assert len({item.id for item in candidates}) == len(origins) == 3
    assert candidates[2].id == colliding_id


def test_finalize_retains_original_results_ledger_and_provisional_candidate_fields(tmp_path):
    tools = tools_for(tmp_path, cycles())
    execution = BoundaryExecution(Model(conclusion), BoundaryConfig(provider_request_interval_seconds=0), tools, AuditRequest())
    state = execution.initial_state()
    state.update(asyncio.run(execution.plan_investigation(state)))
    paths = state["plan"].investigations[0].scope
    for path in paths:
        tools.execute("get_source_excerpt", {"path": path}, tool_call_id=f"test-source-{path}")
    refs = execution.references()
    candidates = [candidate(components=paths, evidence_ids=[refs[0].id]),
        candidate(id="second", components=paths, evidence_ids=[ref.id for ref in refs])]
    results = [investigation("i1", candidates[:1]), investigation("i2", candidates[1:]),
        investigation("i3", status="no_finding"),
        investigation("i4", status="inconclusive", limitations=["An implementation remains unavailable."])]
    originals = [item.model_dump() for item in results]
    state.update(investigation_results=results, iterations=4, termination_reason="investigations_completed")
    calls_before = (execution.calls, tools.budget_usage.tool_calls, execution.tokens)
    state.update(execution.synthesis(state))
    output = execution.finalize(state)
    result = output["result"]
    assert execution.finalize(state)["result"] == result
    assert BoundaryResult.model_validate_json(result.model_dump_json()) == result
    assert [item.model_dump() for item in result.investigation_results] == originals
    assert [item.status for item in result.investigation_results] == ["finding_candidate", "finding_candidate", "no_finding", "inconclusive"]
    assert len(result.findings) == len(result.candidates) == 1
    finding = result.findings[0]
    assert finding.model_dump(include=set(BoundaryCandidate.model_fields) - {
        "inferred_boundary", "contradictory_dependency", "technical_basis", "symbol_ids", "relationship_ids"
    }) == result.candidates[0].model_dump(exclude={
        "inferred_boundary", "contradictory_dependency", "technical_basis", "symbol_ids", "relationship_ids"})
    assert finding.validation_status == "insufficient_evidence" and "Provisional" in finding.review_rationale
    assert finding.criterion == execution.request.criteria[0]
    assert set(finding.evidence_ids) == {ref.id for ref in finding.evidence} == {ref.id for ref in result.evidence}
    assert all(ref.content_hash and ref.tool_call_id and ref.snapshot_hash == result.snapshot_hash for ref in result.evidence)
    assert result.candidate_origins[finding.id][1].candidate_id == "second"
    assert "An implementation remains unavailable." in result.limitations
    assert any("i4" in item for item in result.missing_information)
    assert (execution.calls, tools.budget_usage.tool_calls, execution.tokens) == calls_before
    assert result.critical_review is None and result.next_phase is None


@pytest.mark.parametrize("status", ["no_finding", "inconclusive"])
def test_real_graph_without_findings_preserves_conclusions_and_phase_accounting(tmp_path, status):
    limitation = "The boundary contract is not established."
    result, model, _ = audit(tmp_path, cycles(), lambda context: conclusion(context, status,
        **({"limitations": [limitation]} if status == "inconclusive" else {})))
    assert not result.findings and not result.candidates and not result.candidate_origins
    assert result.investigation_results[0].status == status and result.evidence
    assert len(model.contexts) == result.model_calls == 2 and result.next_phase is None
    for field in ("model_calls", "tool_calls", "accounted_tokens", "estimated_tokens"):
        assert sum(usage[field] for usage in result.consumption_by_phase.values()) == getattr(result, field)
        assert result.consumption_by_phase["synthesis"][field] == result.consumption_by_phase["finalize"][field] == 0
    assert not any("Synthesis remains pending" in item for item in result.missing_information)
    assert bool(result.missing_information) == (status == "inconclusive")


def test_abstention_still_reaches_synthesis_and_finalize_without_extra_calls(tmp_path):
    class AbstainingModel(Model):
        async def ainvoke(self, messages, **kwargs):
            response = await super().ainvoke(messages, **kwargs)
            return response.model_copy(update={"content": '{"opportunity_ids": []}'})
    result, model, _ = audit(tmp_path, cycles(), conclusion, model_type=AbstainingModel)
    assert len(model.contexts) == result.model_calls == 1 and result.tool_calls == 0
    assert result.next_phase is None and not result.findings and not result.investigation_results
    assert set(result.consumption_by_phase) == {"plan_investigation", "investigate", "synthesis", "finalize"}
