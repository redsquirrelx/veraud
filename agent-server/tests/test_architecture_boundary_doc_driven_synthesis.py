"""Deterministic, scoped documentary synthesis without model or repository reads."""

import asyncio
import importlib.util
import itertools
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_architecture_boundary_doc_driven_investigation import (
    Model,
    assess_all,
    run,
    verified_tools,
)
from test_architecture_boundary_doc_driven_planning import claim, context
from test_architecture_boundary_synthesis import candidate as original_candidate

from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.schemas import (
    BoundaryCandidate,
    BoundaryInvestigation,
    BoundaryInvestigationResult,
    BoundaryPlan,
    BoundaryResult,
    ClaimAssessment,
    DocumentarySynthesis,
    DocumentClaimRecord,
    EvidenceReference,
)
from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.synthesis import (
    consolidate_candidates,
    consolidate_claim_assessments,
)
from server.services.document_indexing import IndexReference


def plan(keys=("c1",), count=3):
    catalog = {key: DocumentClaimRecord(claim=claim(), document_index=IndexReference(
        index_id="index", repository_id="repo", commit="commit"), section_paths={"s1": "docs/rules.md"},
        status="applicable", reason="Known documentary ownership.", scope_paths=["a.py", "b.py"])
        for key in keys}
    return BoundaryPlan(objectives=[], components=[], snapshot_hash="snapshot", document_claims=catalog,
        investigations=[BoundaryInvestigation(id=f"i{i}", priority="medium", scope=["a.py", "b.py"],
            structural_signal={"kind": "documented_boundary", "observed": ["Indexed scope."], "inference": "Provisional mapping."},
            question="Examine the local interaction.", evidence_needed=["Implementation and usage."],
            investigation_strategy=[{"tool": "find_symbols", "arguments": {"file_path": "a.py"}}],
            completion_condition="Scoped observation or limitation.", document_claim_ids=list(keys)) for i in range(1, count + 1)])


def evidence():
    return [EvidenceReference(id=identifier, snapshot_hash="snapshot", commit="commit", path=path, file_id=path,
        content_hash="hash", kind="source", start_line=start, end_line=start + 9, tool_call_id="read-" + identifier,
        commit_verification="exact") for identifier, path, start in [("e1", "a.py", 1), ("e2", "b.py", 1), ("e3", "a.py", 30)]]


def assessment(status="supported", key="c1", refs=("e1",), paths=("a.py",), **changes):
    return ClaimAssessment(**({"claim_id": key, "status": status, "rationale": "Observed local contract and mechanism.",
        "code_evidence_ids": list(refs), "scope_paths": list(paths), "assessment_origin": "investigator"} | changes))


def result(identifier="i1", assessments=None, **changes):
    assessments = [assessment()] if assessments is None else assessments
    return BoundaryInvestigationResult(**({"investigation_id": identifier, "status": "no_finding",
        "summary": "Original local conclusion.", "justification": "Original observations.",
        "claim_assessments": assessments, "evidence_ids": sorted({key for item in assessments for key in item.code_evidence_ids}),
        "document_claim_delivery": {item.claim_id: "delivered" for item in assessments}} | changes))


def test_single_assessment_preserves_original_provenance_scope_and_limits():
    p, r = plan(), result(assessments=[assessment(exceptions_examined=["Inspected composition exception."], limitations=["Only a.py."])])
    summary = consolidate_claim_assessments([r], p, evidence())
    group = summary.claims["c1"]
    assert group.assessments[0].assessment == r.claim_assessments[0]
    assert group.evaluated_investigation_ids == ["i1"] and group.coverage_status == "partial"
    assert summary.coverage.delivered_claim_ids == summary.coverage.evaluated_claim_ids == ["c1"]
    assert not summary.global_compliance_established
    assert p.document_claims[group.claim_id].section_paths == {"s1": "docs/rules.md"}
    assert p.document_claims[group.claim_id].claim.evidence[0].quote


def test_supported_and_contradicted_disjoint_scopes_are_not_a_logical_conflict():
    results = [result("i1"), result("i2", [assessment("contradicted", refs=("e2",), paths=("b.py",))])]
    before = [r.model_dump() for r in results]
    summary = consolidate_claim_assessments(results, plan(), evidence())
    group = summary.claims["c1"]
    assert len(group.assessments) == 2 and group.has_contradiction
    assert group.evaluated_investigation_ids == ["i1", "i2"]
    assert group.comparisons[0].scope_relation == "different_scopes"
    assert summary.coverage.locally_supported_claim_ids == summary.coverage.contradicted_claim_ids == ["c1"]
    assert [r.model_dump() for r in results] == before


@pytest.mark.parametrize("anchors,expected", [(["r1"], "same_technical_anchors"), ([], "overlapping_or_unknown")])
def test_opposed_outcomes_on_same_scope_remain_separate_and_require_review(anchors, expected):
    results = [result("i1", relationship_ids=anchors), result("i2", [assessment("contradicted")], relationship_ids=anchors)]
    summary = consolidate_claim_assessments(results, plan(), evidence())
    group = summary.claims["c1"]
    assert [row.assessment.status for row in group.assessments] == ["supported", "contradicted"]
    assert group.comparisons[0].scope_relation == expected
    assert group.comparisons[0].limitation  # Equal file paths/anchors are not semantic equivalence.


def test_disjoint_source_ranges_on_same_file_are_not_the_same_interaction():
    results = [result("i1", relationship_ids=["r1"]),
        result("i2", [assessment("contradicted", refs=("e3",))], relationship_ids=["r1"])]
    summary = consolidate_claim_assessments(results, plan(), evidence())
    comparison = summary.claims["c1"].comparisons[0]
    assert comparison.scope_relation == "different_scopes"
    assert "windows are disjoint" in comparison.limitation


def test_not_applicable_is_local_and_inconclusive_keeps_its_missing_information():
    results = [result("i1", [assessment("not_applicable")]), result("i2", [assessment("contradicted")]),
        result("i3", [assessment("inconclusive", refs=(), paths=(), limitations=["Exception owner remains unknown."])], status="inconclusive")]
    summary = consolidate_claim_assessments(results, plan(), evidence())
    group = summary.claims["c1"]
    assert group.has_contradiction and group.has_inconclusive
    assert group.assessments[2].assessment.limitations == ["Exception owner remains unknown."]
    assert summary.coverage.locally_not_applicable_claim_ids == summary.coverage.contradicted_claim_ids == ["c1"]
    assert len(summary.coverage.evaluated_claim_ids) == 1


def test_selected_but_never_assessed_or_delivered_stays_pending():
    summary = consolidate_claim_assessments([], plan(), evidence())
    assert summary.coverage.selected_not_evaluated_claim_ids == ["c1"]
    assert not summary.coverage.evaluated_claim_ids
    assert summary.claims["c1"].coverage_status == "not_evaluated"


@pytest.mark.parametrize("origin", ["host_pending", "unknown"])
def test_synthetic_budget_placeholder_does_not_count_as_effective(origin):
    r = result(assessments=[assessment("inconclusive", refs=(), paths=(), assessment_origin=origin,
        limitations=["investigation_token_limit"])], status="inconclusive", limitations=["investigation_token_limit"],
        document_claim_delivery={"c1": "not_delivered"})
    summary = consolidate_claim_assessments([r], plan(), evidence())
    assert not summary.coverage.evaluated_claim_ids and summary.coverage.selected_not_evaluated_claim_ids == ["c1"]
    assert summary.claims["c1"].assessments[0].investigation_limitations == ["investigation_token_limit"]
    assert not summary.claims["c1"].assessments[0].effective


def test_empty_exception_list_is_not_evidence_of_no_exceptions():
    summary = consolidate_claim_assessments([result()], plan(), evidence())
    assert not summary.claims["c1"].assessments[0].assessment.exceptions_examined
    assert any("does not establish absence" in text for text in summary.claims["c1"].limitations)


@pytest.mark.parametrize("damage,code", [
    ("missing_claim", "claim_missing_from_catalog"), ("doc_as_code", "documentary_id_used_as_technical_evidence"),
    ("unknown_evidence", "unknown_technical_evidence"), ("wrong_task", "claim_not_associated_with_investigation"),
    ("bad_source", "unverified_technical_provenance"), ("bad_scope", "assessment_scope_without_source"),
    ("bad_document", "invalid_documentary_provenance"),
])
def test_inconsistent_references_are_retained_but_not_counted(damage, code):
    p, refs, r = plan(), evidence(), result()
    if damage == "missing_claim":
        p.document_claims.clear()
    elif damage in {"doc_as_code", "unknown_evidence"}:
        r = result(assessments=[assessment(refs=("c1" if damage == "doc_as_code" else "invented",))])
    elif damage == "wrong_task":
        r = result("missing-investigation")
    elif damage == "bad_source":
        refs[0] = refs[0].model_copy(update={"commit_verification": "unverified"})
    elif damage == "bad_scope":
        r = result(assessments=[assessment(paths=("unread.py",))])
    elif damage == "bad_document":
        p.document_claims["c1"] = p.document_claims["c1"].model_copy(update={"section_paths": {}})
    summary = consolidate_claim_assessments([r], p, refs)
    assert code in {issue.code for issue in summary.integrity_issues}
    assert not summary.coverage.evaluated_claim_ids
    retained = summary.unresolved_assessments if damage == "missing_claim" else summary.claims["c1"].assessments
    assert retained[0].assessment == r.claim_assessments[0]
    assert set(summary.claims) <= p.document_claims.keys()


def test_duplicate_input_is_deduplicated_but_different_assessments_are_not_overwritten():
    r = result()
    summary = consolidate_claim_assessments([r, r], plan(), evidence())
    assert len(summary.claims["c1"].assessments) == 1
    assert "duplicate_assessment" in {issue.code for issue in summary.integrity_issues}
    different = result(assessments=[assessment("contradicted")])
    summary = consolidate_claim_assessments([r, different], plan(), evidence())
    assert len(summary.claims["c1"].assessments) == 2
    assert "multiple_assessments_in_investigation" in {issue.code for issue in summary.integrity_issues}
    assert not summary.coverage.evaluated_claim_ids


def test_new_delivery_receipts_and_legacy_unknown_are_not_confused():
    legacy = result(document_claim_delivery={})
    summary = consolidate_claim_assessments([legacy], plan(), evidence())
    assert summary.coverage.evaluated_claim_ids == ["c1"]
    assert not summary.coverage.delivered_claim_ids and summary.coverage.delivery_unknown_claim_ids == ["c1"]
    assert summary.claims["c1"].assessments[0].delivery_status == "unknown"


def test_deterministic_under_result_order_changes_and_no_input_mutation():
    results = [result("i1"), result("i2", [assessment("contradicted", refs=("e2",), paths=("b.py",))]),
        result("i3", [assessment("not_applicable")])]
    expected = consolidate_claim_assessments(results, plan(), evidence()).model_dump_json()
    for permutation in itertools.permutations(results):
        assert consolidate_claim_assessments(permutation, plan(), list(reversed(evidence()))).model_dump_json() == expected


def test_no_documentation_has_no_claims_and_no_global_compliance():
    summary = consolidate_claim_assessments([result(assessments=[])], plan(keys=(), count=0), evidence())
    assert not summary.claims and not summary.integrity_issues and not summary.coverage.evaluated_claim_ids
    assert not summary.global_compliance_established


def test_round_trip_keeps_documentary_catalog_and_original_conclusions():
    p, r = plan(), result()
    summary = consolidate_claim_assessments([r], p, evidence())
    output = BoundaryResult(repository_id="repo", commit="commit", snapshot_hash="snapshot", objective="Investigate.",
        plan=p, findings=[], hypotheses=[], missing_information=[], limitations=[], termination_reason="investigations_completed",
        model_calls=0, tool_calls=0, iterations=1, accounted_tokens=0, estimated_tokens=0, evidence=evidence(),
        investigation_results=[r], documentary_synthesis=summary)
    assert BoundaryResult.model_validate_json(output.model_dump_json()) == output
    assert DocumentarySynthesis.model_validate_json(summary.model_dump_json()) == summary
    invalid = output.model_dump(mode="json")
    invalid["plan"]["document_claims"].clear()
    with pytest.raises(ValidationError, match="absent from plan catalog"):
        BoundaryResult.model_validate(invalid)


def candidate(**changes):
    return BoundaryCandidate.model_validate(original_candidate().model_dump() | changes)


def test_candidate_documentary_ids_are_identity_sets_without_changing_original_fields():
    first = candidate(document_claim_ids=["c1", "c2"], confidence=1.0)
    second = first.model_copy(update={"id": "second", "document_claim_ids": ["c2", "c1"], "evidence_ids": ["e2"]})
    inputs = [result("i1", [], candidates=[first]), result("i2", [], candidates=[second])]
    candidates, origins = consolidate_candidates(inputs)
    assert len(candidates) == 1 and candidates[0].confidence == 1.0
    assert candidates[0].severity == first.severity and candidates[0].evidence_ids == ["e1", "e2"]
    assert [origin.investigation_id for origin in origins[first.id]] == ["i1", "i2"]
    assert first.document_claim_ids == ["c1", "c2"] and second.document_claim_ids == ["c2", "c1"]


@pytest.mark.parametrize("changes", [{"confidence": .8}, {"severity": "high"}, {"document_claim_ids": ["c2"]}])
def test_candidate_collisions_preserve_differences_and_stable_ids(changes):
    inputs = [result("i1", [], candidates=[candidate(document_claim_ids=["c1"])]),
        result("i2", [], candidates=[candidate(document_claim_ids=["c1"], **changes)] if "document_claim_ids" not in changes else [candidate(**changes)])]
    candidates, origins = consolidate_candidates(inputs)
    assert len(candidates) == len(origins) == len({item.id for item in candidates}) == 2
    assert consolidate_candidates(inputs) == (candidates, origins)
    colliding = candidate(id=candidates[1].id, title="A distinct concern.")
    combined, origins = consolidate_candidates([*inputs, result("i3", [], candidates=[colliding])])
    assert len({item.id for item in combined}) == len(origins) == 3
    assert combined[2].id == colliding.id


def test_runner_default_reaches_synthesis_and_finalize_without_extra_model_calls(tmp_path, capsys):
    tools = verified_tools(tmp_path, {"app/__init__.py": "", "app/api.py": "from .store import Store\ndef use(): return Store()\n",
        "app/store.py": "class Store: pass\n"})
    path = Path(__file__).parents[1] / "src/test-agents/run_architecture_boundary_doc_driven.py"
    spec = importlib.util.spec_from_file_location("synthesis_runner", path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    destination = tmp_path / "output.json"
    destination.write_text("previous output", encoding="utf-8")
    model = Model(lambda p: assess_all(p, "contradicted", status="finding_candidate", candidate=True))

    class Tracing:
        async def wrap_stage(self, operation, **kwargs):
            return await operation

    asyncio.run(runner.run_audit(SimpleNamespace(max_files=2000, output="readable", output_file=str(destination)),
        Path(tools.accessible_snapshot.repository.root_path), runner.AuditRequest(documented_architecture=context(tools, [claim()])),
        runner.BoundaryConfig(provider_request_interval_seconds=0, max_planned_investigations=1), model,
        SimpleNamespace(max_tokens=1800, provider="test", name="offline"), tracing_backend=Tracing()))
    output = BoundaryResult.model_validate_json(destination.read_text(encoding="utf-8"))
    assert output.documentary_synthesis.coverage.evaluated_claim_ids
    assert len(output.candidates) == len(output.findings) == 1 and output.candidate_origins
    assert not {"validation_status", "review_rationale"} & output.findings[0].model_dump().keys()
    assert output.next_phase is None and output.model_calls == len(model.contexts) == 2
    assert all(value == "delivered" for item in output.investigation_results for value in item.document_claim_delivery.values())
    assert all(a.assessment_origin == "investigator" for item in output.investigation_results for a in item.claim_assessments)
    assert output.consumption_by_phase["synthesis"]["model_calls"] == output.consumption_by_phase["finalize"]["model_calls"] == 0
    assert "SÍNTESIS DOCUMENTAL" in capsys.readouterr().out


def test_actual_host_fallback_is_not_misreported_as_evaluated(tmp_path):
    tools = verified_tools(tmp_path, {"app/__init__.py": "", "app/api.py": "from .store import Store\ndef use(): return Store()\n",
        "app/store.py": "class Store: pass\n"})
    state, _, _ = run(tools, context(tools, [claim()]), assess_all,
        max_total_tokens=1000)
    local = state["result"].investigation_results[0]
    assert local.claim_assessments[0].assessment_origin == "host_pending"
    assert set(local.document_claim_delivery.values()) == {"not_delivered"}
    summary = consolidate_claim_assessments([local], state["plan"], state["result"].evidence)
    assert not summary.coverage.evaluated_claim_ids and summary.coverage.selected_not_evaluated_claim_ids
