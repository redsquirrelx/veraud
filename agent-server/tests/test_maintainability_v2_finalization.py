"""Deterministic collection/synthesis/finalization and the real linear graph."""

import asyncio
import json
from copy import deepcopy

import pytest
from pydantic import ValidationError
from test_architecture_boundary_planning import tools_for
from test_maintainability_v2_delegation import (
    Tracing,
    assignment,
    execution,
    output,
    spec,
)
from test_maintainability_v2_plan_audit import Model

from server.agents.maintainability.v2.manager import (
    AuditResult,
    MaintainabilityManager,
    MaintainabilityRequest,
    collection,
    delegation,
    registry,
)
from server.agents.maintainability.v2.manager.config import MaintainabilityConfig
from server.agents.maintainability.v2.modularity.coordinator.config import (
    ModularityConfig,
)
from server.contracts.audit import Consumption, EvidenceReference
from server.runtimes.repository.context import RepositoryContext


@pytest.fixture
def tools(tmp_path):
    tools = tools_for(tmp_path, {"Checkout/api.py": "class API:\n    pass\n", "Checkout/store.py": "class Store:\n    pass\n"})
    tools.context = RepositoryContext(tools.context.snapshot, tools.context.input.model_copy(update={
        "budget": tools.context.input.budget.model_copy(update={"max_model_calls": 32})}))
    return tools


def evidence(tools, identifier="e1", path="Checkout/api.py", **changes):
    file = next(file for file in tools.accessible_snapshot.files if file.path == path)
    return EvidenceReference(**({"id": identifier, "snapshot_hash": tools.context.input.snapshot_hash,
        "commit": tools.accessible_snapshot.repository.commit, "path": file.path, "file_id": file.id,
        "content_hash": file.content_hash, "kind": "source", "start_line": 1, "end_line": 2,
        "tool_call_id": "read-" + identifier} | changes)).model_dump(mode="json")


def finding(tools, identifier="f1", **changes):
    return {"id": identifier, "title": "Scoped observation", "description": "Observed behavior in one interaction.",
        "components": ["Checkout/api.py"], "severity": "high", "confidence": 0.9,
        "validation_status": "accepted", "limitations": ["Only this interaction."],
        "evidence_ids": ["e1"], "evidence": [evidence(tools)]} | changes


def child(findings=None, **changes):
    async def run(instance, tools, request):
        return output(tools, request, findings=findings or [], coverage={"evaluated_targets": request.targets}, **changes)
    return run


def finish(tools, monkeypatch, specs, assignments, *, receipts=None):
    monkeypatch.setattr(collection, "registered_coordinators", lambda: specs)
    runtime, state, model = execution(tools, monkeypatch, specs, assignments)
    if receipts is None:
        state.update(asyncio.run(runtime.delegate_coordinators(state)))
    else:
        state.update(receipts)
    raw, charged = deepcopy(state.get("coordinator_results", [])), state["consumption"]
    for node in (runtime.collect_assessments, runtime.synthesize_assessments, runtime.finalize_audit):
        state.update(node(state))
    result = state["result"]
    assert result.coordinator_results == raw and result.consumption == charged
    assert not model.contexts and tools.budget_usage.tool_calls == 0
    assert AuditResult.model_validate_json(result.model_dump_json()) == result
    return runtime, state, result


def test_one_coordinator_retains_original_finding_and_all_provenance(tools, monkeypatch):
    original = finding(tools)
    _, _, result = finish(tools, monkeypatch, {"one": spec(run=child([original]))}, [assignment()])
    value = next(iter(result.findings.values()))
    assert result.status == "completed" and value.payload == original
    assert value.origins[0].finding_id == "f1" and value.origins[0].coordinator_id == "one"
    assert value.origins[0].assignment_id == result.coordinator_results[0].assignment_id
    assert value.evidence_refs and not value.integrity_issues
    assert result.assessments[0].reported_coverage == {"evaluated_targets": ["Checkout"]}
    assert result.coverage.observed_source_paths == ["Checkout/api.py"]
    assert not result.coverage.global_compliance_established and not result.links


def test_multiple_different_findings_are_independent_when_no_shared_anchors(tools, monkeypatch):
    first = finding(tools)
    second = finding(tools, "f2", title="Different concern", components=["Checkout/store.py"],
        evidence_ids=["e2"], evidence=[evidence(tools, "e2", "Checkout/store.py")])
    _, _, result = finish(tools, monkeypatch, {"one": spec(run=child([first])), "two": spec("two", child([second]))},
        [assignment(), assignment("two")])
    assert len(result.findings) == 2 and not result.links and result.status == "completed"
    assert result.consumption.model_calls == 2


def test_only_exact_payloads_merge_preserving_original_ids_and_origins(tools, monkeypatch):
    first, second = finding(tools), finding(tools, "other-local-id")
    _, _, result = finish(tools, monkeypatch, {"one": spec(run=child([first])), "two": spec("two", child([second]))},
        [assignment(), assignment("two")])
    assert len(result.findings) == 1
    merged = next(iter(result.findings.values()))
    assert {origin.finding_id for origin in merged.origins} == {"f1", "other-local-id"}
    assert {origin.coordinator_id for origin in merged.origins} == {"one", "two"}
    assert merged.payload["confidence"] == .9 and merged.payload["severity"] == "high"
    assert len(result.coordinator_results) == 2 and not result.links


@pytest.mark.parametrize("change", [{"confidence": 1.0}, {"severity": "critical"}, {"description": "Other meaning."},
    {"validation_status": "rejected"}, {"limitations": ["Different scope uncertainty."]}])
def test_relevant_differences_are_not_erased_by_deduplication(tools, monkeypatch, change):
    values = [finding(tools), finding(tools, "f2", **change)]
    _, _, result = finish(tools, monkeypatch, {"one": spec(run=child(values))}, [assignment()])
    assert len(result.findings) == 2
    assert {json.dumps(value.payload, sort_keys=True) for value in result.findings.values()} == {
        json.dumps(value, sort_keys=True) for value in values}
    assert result.links[0].interpretation == "shared_anchors_only"
    assert result.links[0].shared_components == ["Checkout/api.py"]
    assert result.links[0].shared_evidence


def test_shared_file_links_do_not_require_the_same_evidence_window_or_merge(tools, monkeypatch):
    first, second = finding(tools), finding(tools, "f2", title="Independent responsibility", evidence_ids=["e2"],
        evidence=[evidence(tools, "e2", start_line=2, end_line=2)])
    _, _, result = finish(tools, monkeypatch, {"one": spec(run=child([first, second]))}, [assignment()])
    assert len(result.findings) == 2 and len(result.links) == 1
    assert result.links[0].shared_components and not result.links[0].shared_evidence


def test_completed_coordinator_without_findings_does_not_establish_compliance(tools, monkeypatch):
    _, _, result = finish(tools, monkeypatch, {"one": spec(run=child())}, [assignment()])
    assert result.status == "completed" and not result.findings
    assert not result.coverage.global_compliance_established
    assert "No se infiere conformidad global" in result.summary
    assert not result.coverage.observed_source_paths


def test_no_assignments_is_distinct_from_a_failed_or_completed_audit(tools, monkeypatch):
    _, _, result = finish(tools, monkeypatch, {}, [])
    assert result.status == "not_applicable" and not result.assessments and not result.findings
    assert result.consumption.model_calls == 0


@pytest.mark.parametrize("all_fail", [False, True])
def test_partial_and_total_failures_remain_explicit(tools, monkeypatch, all_fail):
    async def fail(instance, tools, request):
        raise RuntimeError("secret child payload")

    specs = {"one": spec(run=fail if all_fail else child([finding(tools)])), "two": spec("two", fail)}
    _, _, result = finish(tools, monkeypatch, specs, [assignment(), assignment("two")])
    assert result.status == ("failed" if all_fail else "partial")
    assert len(result.findings) == (0 if all_fail else 1)
    assert result.issues and result.coverage.failed_assignment_ids
    assert "secret child payload" not in result.model_dump_json()


@pytest.mark.parametrize("damage", ["unknown_evidence", "stale_evidence", "duplicate_id", "key_mismatch", "missing_id"])
def test_integrity_errors_preserve_raw_findings_without_global_success(tools, monkeypatch, damage):
    values = [finding(tools)]
    if damage == "unknown_evidence":
        values[0]["evidence_ids"] = ["not-retrieved"]
    elif damage == "stale_evidence":
        values[0]["evidence"][0]["snapshot_hash"] = "stale"
    elif damage == "duplicate_id":
        values.append(finding(tools, title="Different observation with reused ID"))
    elif damage == "key_mismatch":
        values = {"wrong-key": values[0]}
    else:
        del values[0]["id"]
    _, _, result = finish(tools, monkeypatch, {"one": spec(run=child(values))}, [assignment()])
    assert result.status == "partial" and result.issues
    assert result.coordinator_results[0].result["findings"] == values
    assert any(value.integrity_issues for value in result.findings.values())
    assert len(result.findings) == (2 if damage == "duplicate_id" else 1)


def test_missing_or_unassigned_receipts_cannot_establish_completion(tools, monkeypatch):
    _, _, result = finish(tools, monkeypatch, {"one": spec()}, [assignment()], receipts={"coordinator_results": []})
    assert result.status == "failed" and result.issues[0].code == "missing_receipt"
    assert result.coverage.not_executed_assignment_ids


def test_duplicate_receipts_and_repeated_nodes_do_not_double_charge(tools, monkeypatch):
    specs = {"one": spec(run=child([finding(tools)]))}
    runtime, state, _ = execution(tools, monkeypatch, specs, [assignment()])
    monkeypatch.setattr(collection, "registered_coordinators", lambda: specs)
    state["consumption"] = Consumption(model_calls=1, accounted_tokens=12)
    state.update(asyncio.run(runtime.delegate_coordinators(state)))
    charged = state["consumption"]
    state["coordinator_results"] *= 2
    for _ in range(2):
        for node in (runtime.collect_assessments, runtime.synthesize_assessments, runtime.finalize_audit):
            state.update(node(state))
    result = state["result"]
    assert len(result.assessments) == len(result.findings) == 1
    assert len(result.coordinator_results) == 2 and result.consumption == charged
    assert result.consumption.model_calls == 2 and result.consumption.accounted_tokens == 42
    assert result.status == "partial" and any(issue.code == "duplicate_receipt" for issue in result.issues)


def test_canonical_consolidated_findings_keep_nested_contributions(tools, monkeypatch):
    original = finding(tools)
    group = {"id": "g1", "concern": "Original coordinated observation.", "affected_components": ["Checkout/api.py"],
        "status": "disputed", "evidence": [evidence(tools)], "severity": "high", "confidence": .9, "limitations": [],
        "contributions": [{"reference": "nested/f1", "invocation_id": "nested", "investigator_id": "actual-specialist", "finding": original}]}

    async def run(instance, child_tools, request):
        child_result = {key: value for key, value in output(child_tools, request).items() if key in {"repository_id", "commit", "snapshot_hash"}}
        child_result["findings"] = [original]
        return output(child_tools, request, consolidated_findings=[group], material_gaps=[{"kind": "contradiction", "id": "gap1"}],
            invocations=[{"assignment": {"invocation_id": "nested", "investigator_id": "actual-specialist"},
                "result": child_result, "evidence": [evidence(tools)]}])

    _, _, result = finish(tools, monkeypatch, {"one": spec(run=run)}, [assignment()])
    assert result.status == "partial"
    assert next(iter(result.findings.values())).payload == group
    assert result.assessments[0].inconclusive[0] == {"kind": "contradiction", "id": "gap1"}
    assert result.assessments[0].inconclusive[1]["status"] == "disputed"
    assert not result.issues


def test_serialized_audit_rejects_unknown_relation_references(tools, monkeypatch):
    _, _, result = finish(tools, monkeypatch, {"one": spec(run=child([finding(tools)]))}, [assignment()])
    invalid = result.model_dump(mode="json")
    invalid["links"] = [{"finding_refs": [next(iter(result.findings)), "invented"]}]
    with pytest.raises(ValidationError, match="relation reference"):
        AuditResult.model_validate(invalid)


def test_full_graph_ends_after_finalization_with_only_one_manager_model_call(tools, monkeypatch):
    specs = {"one": spec(run=child([finding(tools)]))}
    for module in (registry, delegation, collection):
        monkeypatch.setattr(module, "registered_coordinators", lambda: specs)
    model = Model({"objective": "Audit Checkout", "assignments": [assignment().model_dump()], "uncovered_requirements": [], "limitations": []})
    manager = MaintainabilityManager(model, MaintainabilityConfig(provider_request_interval_seconds=0), tracing_backend=Tracing())
    result = asyncio.run(manager.run(tools, MaintainabilityRequest(objective="Audit Checkout", targets=["Checkout"])))
    assert isinstance(result, AuditResult) and result.status == "completed"
    assert result.node_transitions == ["plan_audit", "delegate_coordinators", "collect_assessments", "synthesize_assessments", "finalize_audit"]
    assert len(model.contexts) == 1 and result.consumption.model_calls == 2  # Parent plus simulated child's recorded usage.
    assert tools.budget_usage.tool_calls == 0


@pytest.mark.parametrize("invalid", [False, True])
def test_graph_closes_on_empty_plan_or_planning_error(tools, invalid):
    model = Model("invalid JSON" if invalid else {"objective": "Unsupported audit", "assignments": [],
        "uncovered_requirements": ["No applicable coordinator."], "limitations": []})
    manager = MaintainabilityManager(model, MaintainabilityConfig(provider_request_interval_seconds=0), tracing_backend=Tracing())
    result = asyncio.run(manager.run(tools, MaintainabilityRequest(objective="Unsupported audit"), capabilities=[]))
    assert result.status == ("failed" if invalid else "not_applicable")
    assert result.node_transitions[-1] == "finalize_audit" and result.consumption.model_calls == 1


def test_real_modularity_remains_partial_and_does_not_manufacture_findings(tools):
    class TwoPlanners(Model):
        async def ainvoke(self, messages, **kwargs):
            self.response = ({"objective": "Architecture in Checkout", "assignments": [assignment("modularity").model_dump()],
                "uncovered_requirements": [], "limitations": []} if not self.contexts else
                {"objective": "Architecture in Checkout", "assignments": [], "uncovered_requirements": ["Planner only."], "limitations": []})
            return await super().ainvoke(messages, **kwargs)

    model = TwoPlanners(None)
    manager = MaintainabilityManager(model, MaintainabilityConfig(provider_request_interval_seconds=0,
        invocation_limits=ModularityConfig(provider_request_interval_seconds=0, max_schema_retries=0)), tracing_backend=Tracing())
    result = asyncio.run(manager.run(tools, MaintainabilityRequest(objective="Architecture in Checkout", targets=["Checkout"])))
    assert result.status == "partial" and not result.findings
    assert result.assessments[0].result_kind == "assessment" and not result.coverage.evaluated_assignment_ids
    assert result.coverage.partial_assignment_ids and len(model.contexts) == 2
    assert result.coordinator_results[0].result["plan"]["uncovered_requirements"] == ["Planner only."]


def test_same_text_and_evidence_id_do_not_merge_different_source_receipts(tools, monkeypatch):
    original = finding(tools, evidence=[])

    async def first(instance, child_tools, request):
        return output(child_tools, request, findings=[original], evidence=[evidence(tools)])

    async def second(instance, child_tools, request):
        return output(child_tools, request, findings=[original], evidence=[evidence(tools, path="Checkout/store.py")])

    _, _, result = finish(tools, monkeypatch, {"one": spec(run=first), "two": spec("two", second)}, [assignment(), assignment("two")])
    assert len(result.findings) == 2
    assert all(not finding.integrity_issues for finding in result.findings.values())


def test_explicit_inconclusive_finding_remains_inconclusive_without_confidence_adjustment(tools, monkeypatch):
    original = finding(tools, status="inconclusive", confidence=1.0)
    _, _, result = finish(tools, monkeypatch, {"one": spec(run=child([original]))}, [assignment()])
    assert result.status == "partial"
    assert next(iter(result.findings.values())).payload == original
    assert result.assessments[0].inconclusive[0]["status"] == "inconclusive"


def test_legacy_validation_fields_are_opaque_not_a_manager_verdict(tools, monkeypatch):
    original = finding(tools, validation_status="insufficient_evidence", review_rationale="Legacy compatibility text.")
    _, _, result = finish(tools, monkeypatch, {"one": spec(run=child([original]))}, [assignment()])
    assert result.status == "completed" and not result.assessments[0].inconclusive
    assert next(iter(result.findings.values())).payload == original


def test_synthesis_is_stable_under_receipt_order_changes(tools, monkeypatch):
    specs = {"one": spec(run=child([finding(tools)])), "two": spec("two", child([finding(tools, "f2", title="Other observation")]))}
    runtime, state, _ = execution(tools, monkeypatch, specs, [assignment(), assignment("two")])
    monkeypatch.setattr(collection, "registered_coordinators", lambda: specs)
    state.update(asyncio.run(runtime.delegate_coordinators(state)))
    state.update(runtime.collect_assessments(state))
    first = runtime.synthesize_assessments(state)["synthesis"]
    state["coordinator_results"].reverse()
    state.update(runtime.collect_assessments(state))
    assert runtime.synthesize_assessments(state)["synthesis"] == first


def test_historical_native_request_evidence_is_not_current_audit_coverage(tools, monkeypatch):
    prior = evidence(tools, "old", "Checkout/store.py", snapshot_hash="prior-snapshot")

    async def archived_request(instance, child_tools, request):
        return output(child_tools, request, findings=[finding(tools)],
            initial_plan=[{"request": {"continuation": {"evidence": [prior]}}}])

    _, _, result = finish(tools, monkeypatch, {"one": spec(run=archived_request)}, [assignment()])
    assert result.status == "completed" and not result.issues
    assert result.coverage.observed_source_paths == ["Checkout/api.py"]
    assert result.coordinator_results[0].result["initial_plan"][0]["request"]["continuation"]["evidence"] == [prior]
