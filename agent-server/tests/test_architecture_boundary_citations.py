"""Full graph checks with automatic initial evidence and citation-only repairs."""

import asyncio
import json

import pytest
from langchain_core.messages import AIMessage
from test_architecture_boundary_planning import cycles, tools_for

from server.agents.maintainability.v1.modularity.architecture_boundary import (
    ArchitectureBoundaryAgent,
    AuditRequest,
    BoundaryConfig,
)
from server.agents.maintainability.v1.modularity.architecture_boundary.execution import (
    BoundaryExecution,
)


class Model:
    def __init__(self, decide):
        self.decide, self.contexts, self.schemas = decide, [], []

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages, **kwargs):
        assert not any(isinstance(message, AIMessage) for message in messages)
        context = json.loads(messages[1].content)
        self.contexts.append(context)
        value = ({"opportunity_ids": [item["id"] for item in context["opportunities"]]}
            if "opportunities" in context else self.decide(context))
        return AIMessage(content=json.dumps(value), usage_metadata={"input_tokens": 100, "output_tokens": 100, "total_tokens": 200})

    def with_structured_output(self, schema, **kwargs):
        self.schemas.append(schema.__name__)
        parent = self
        class Structured:
            async def ainvoke(self, messages, **options):
                raw = await parent.ainvoke(messages, **options)
                return {"raw": raw, "parsed": schema.model_validate_json(raw.content)}
        return Structured()


def conclusion(context, status="no_finding", **changes):
    catalog = context["reference_catalog"]
    return {"action": "close", "conclusion": {
        "investigation_id": context["investigation"]["id"], "status": status,
        "summary": "No forbidden access established in the inspected scope.",
        "justification": "The inspected import/use and endpoint declarations do not establish an architectural prohibition.",
        "components": list(catalog["source_evidence_by_component"]),
        "evidence_ids": [identifier for ids in catalog["source_evidence_by_component"].values() for identifier in ids],
        "relationship_ids": [edge["id"] for edge in catalog["examined_relationships"]], **changes}}


def audit(tmp_path, contents, decide, *, model_type=Model, **settings):
    tools = tools_for(tmp_path, contents)
    model = model_type(decide)
    config = BoundaryConfig(provider_request_interval_seconds=0, max_output_tokens=1200,
        provider_rate_limits={"requests_per_minute": None, "tokens_per_minute": None}, **settings)
    result = asyncio.run(ArchitectureBoundaryAgent(model, config).run(tools, AuditRequest()))
    return result, model, tools


def test_single_investigation_receives_verified_edge_and_both_sources_before_first_decision(tmp_path):
    def decide(context):
        catalog = context["reference_catalog"]
        assert set(catalog["source_evidence_by_component"]) == set(context["investigation"]["scope"])
        assert len(catalog["examined_relationships"]) == 1
        assert len(catalog["planned_only_relationship_ids"]) == 1  # The reverse cycle edge is still navigation.
        assert not catalog["examined_relationships"][0]["missing_source_paths"]
        return conclusion(context)
    result, model, tools = audit(tmp_path, cycles(), decide)
    assert [item.status for item in result.investigation_results] == ["no_finding"]
    assert result.model_calls == 2 and result.tool_calls == 3
    assert model.schemas == ["BoundaryPlanSelection", "BoundaryInvestigationTurn"]
    context = model.contexts[1]
    assert len(json.dumps(context)) < 9000
    assert all("content_hash" not in ref and "commit" not in ref for ref in context["evidence"])
    assert all("evidence" not in view and "snapshot_hash" not in view for view in context["tool_results"])
    assert {ref.snapshot_hash for ref in result.evidence} == {tools.context.input.snapshot_hash}
    assert all(ref.content_hash for ref in result.evidence)


@pytest.mark.parametrize("native", [False, True], ids=["json", "structured"])
@pytest.mark.parametrize("explore", [False, True], ids=["direct-close", "tools-then-close"])
def test_real_graph_routes_structured_decisions_and_retains_initial_evidence(tmp_path, native, explore, caplog):
    caplog.set_level("INFO", logger="server.architecture-boundary")
    initial_ids = set()
    new_source_ids = set()
    decisions = []

    def decide(context):
        catalog = context["reference_catalog"]
        delivered = {ref["id"] for ref in context["evidence"]}
        if not decisions:
            initial_ids.update(delivered)
            assert initial_ids and context["tool_results"]
            if explore:
                assert not any("def public_label" in view.get("data", {}).get("content", "") for view in context["tool_results"])
                decisions.append("tools")
                return {"action": "tools", "queries": [{"tool": "get_source_excerpt", "arguments": {
                    "path": "alpha/service.py", "start_line": 66, "end_line": 70},
                    "reason": "Inspect the called query and export surface outside the initial source window."}]}
        assert initial_ids <= delivered
        if explore:
            assert any("def public_label(): return 'Ready'" in view.get("data", {}).get("content", "")
                for view in context["tool_results"])
            new_source_ids.update(set(catalog["source_evidence_by_component"]["alpha/service.py"]) - initial_ids)
            assert new_source_ids
            assert delivered > initial_ids
        decisions.append("close")
        return conclusion(context, justification=(
            "The inspected functions use the peer's callable interface without reading peer-owned backing state. "
            "This supports no contradiction in the examined access paths, not universal compliance."))

    class InstructionAwareModel(Model):
        async def ainvoke(self, messages, **kwargs):
            if "investigation" in json.loads(messages[1].content):
                # Inspect the actual provider request, not just the prompt file.
                assert not any("JSON, no tools" in str(message.content) for message in messages)
                assert "action=tools" in messages[-1].content
            return await super().ainvoke(messages, **kwargs)

    if not native:
        InstructionAwareModel.with_structured_output = None
    contents = ({"alpha/service.py": "from beta.worker import render\n" + "\n" * 65
        + "__all__ = ['public_label', 'start']\ndef public_label(): return 'Ready'\ndef start(): return render()\n",
        "beta/worker.py": "from alpha import service\ndef render(): return service.public_label()\n"} if explore else cycles())
    tools = tools_for(tmp_path, contents)
    model = InstructionAwareModel(decide)
    execution = BoundaryExecution(model, BoundaryConfig(provider_request_interval_seconds=0, max_output_tokens=1200,
        provider_rate_limits={"requests_per_minute": None, "tokens_per_minute": None}), tools, AuditRequest())

    async def trace_graph():
        updates = []
        with execution.timing.stage("investigation"):
            async for update in execution.graph.astream(execution.initial_state(), stream_mode="updates"):
                updates.extend(update.items())
        return updates

    updates = asyncio.run(trace_graph())
    nodes = [node for node, _ in updates]
    # Initial evidence is loaded through the real graph too, before any LLM decision.
    bootstrap = ["plan_investigation", "investigate", "tools"]
    expected = ["investigate", "tools", "investigate"] if explore else ["investigate"]
    assert nodes == bootstrap + expected + ["synthesis", "finalize"]
    assert decisions == (["tools", "close"] if explore else ["close"])
    result = updates[-1][1]["result"]
    assert result.investigation_results[0].status == "no_finding"
    assert result.model_calls == (3 if explore else 2)
    assert result.tool_calls == (4 if explore else 3)
    assert new_source_ids <= set(result.investigation_results[0].evidence_ids)
    assert initial_ids <= {ref.id for ref in result.evidence}
    assert all(ref.content_hash and ref.tool_call_id and ref.snapshot_hash == result.snapshot_hash for ref in result.evidence)
    assert not any(measurement.repeated for measurement in tools.tool_measurements)
    events = [json.loads(record.getMessage().removeprefix("investigation_trace ")) for record in caplog.records
        if record.getMessage().startswith("investigation_trace ")]
    assert {event["investigation_id"] for event in events} == {result.investigation_results[0].investigation_id}
    transitions = [event["transition"] for event in events if event["transition"] != "tool_result"]
    assert transitions == ["investigate->tools", "tools->investigate", "llm->decision"] + (
        ["investigate->tools", "tools->investigate", "llm->decision"] if explore else []) + ["investigate->close"]
    llm_events = [event for event in events if event["transition"] == "llm->decision"]
    assert all(event["llm_calls"] == 1 and event["llm_tokens"] == 200 for event in llm_events)
    assert new_source_ids <= set(llm_events[-1]["delivered_evidence_ids"])
    assert len([event for event in events if event["transition"] == "tool_result" and not event["cached"]]) == result.tool_calls
    for field in ("model_calls", "tool_calls", "accounted_tokens"):
        assert events[-1][field] == result.investigation_progress[0][field]
    print(f"\nTRACE {'structured' if native else 'json'}: " + " -> ".join(nodes)
        + f" -> close; decisions={decisions}; model_calls={result.model_calls}; tool_calls={result.tool_calls}; "
        + f"initial_evidence_retained={len(initial_ids)}; status={result.investigation_results[0].status}")


def test_multiple_investigations_close_with_one_decision_each(tmp_path, caplog):
    caplog.set_level("INFO", logger="server.architecture-boundary")
    result, model, _ = audit(tmp_path, cycles(count=3), conclusion)
    assert [item.status for item in result.investigation_results] == ["no_finding"] * 3
    assert result.model_calls == 4 and result.tool_calls == 9
    assert result.next_phase is None and not result.findings
    ids = [ctx["investigation"]["id"] for ctx in model.contexts if "investigation" in ctx]
    assert ids == [item.investigation_id for item in result.investigation_results]
    assert all(ctx["reusable_queries"] == [] for ctx in model.contexts[1:])  # Unrelated prior tasks are not context.
    closures = [json.loads(record.getMessage().removeprefix("investigation_trace ")) for record in caplog.records
        if record.getMessage().startswith("investigation_trace ") and '"transition": "investigate->close"' in record.getMessage()]
    assert [event["investigation_id"] for event in closures] == ids
    for event, progress in zip(closures, result.investigation_progress, strict=True):
        assert all(event[field] == progress[field] for field in ("model_calls", "tool_calls", "accounted_tokens"))
        assert event["model_calls"] == 1 and event["tool_calls"] == 3 and event["accounted_tokens"] == 200


def test_shared_endpoint_source_is_reused_across_real_planned_boundaries(tmp_path):
    contents = {"a/impl.py": "from b.impl import f\ndef use(): return f()\n",
        "b/impl.py": "from c.impl import f as g\ndef f(): return g()\n", "c/impl.py": "def f(): return 1\n"}
    result, _, tools = audit(tmp_path, contents, conclusion)
    assert len(result.investigation_results) == 2
    assert all(item.status == "no_finding" for item in result.investigation_results)
    assert result.tool_calls == 5  # Two indexed edges, three sources (not four).
    refs = [{ref.id for ref in result.evidence if ref.id in item.evidence_ids and ref.path == "b/impl.py"}
        for item in result.investigation_results]
    assert refs[0] == refs[1] and len(refs[0]) == 1
    assert not any(item.repeated for item in tools.tool_measurements)


@pytest.mark.parametrize("field,bad,code", [
    ("components", "parts0", "uninspected_component"),
    ("relationship_ids", "relationship:invented", "unexamined_relationship"),
    ("evidence_ids", "retrieval:invented", "unknown_or_undelivered_evidence"),
    ("symbol_ids", "symbol:invented", "uninspected_symbol"),
])
def test_reference_errors_return_specific_small_patches_not_full_narratives(tmp_path, field, bad, code):
    original = None
    def decide(context):
        nonlocal original
        if "validation_error" not in context:
            original = conclusion(context)
            original["conclusion"][field] = [bad]
            return original
        assert context["validation_error"] == code
        assert "tool_results" not in context and "investigation" not in context
        assert bad in json.dumps(context["errors"])
        catalog = context["reference_catalog"]
        value = {"components": list(catalog["source_evidence_by_component"]),
            "relationship_ids": [edge["id"] for edge in catalog["examined_relationships"]],
            "evidence_ids": [ref["id"] for ref in catalog["evidence"] if ref["kind"] == "source"],
            "symbol_ids": []}[field]
        return {"action": "patch", "corrections": [{"subject_id": "conclusion", "field": field, "values": value}]}
    result, model, _ = audit(tmp_path, cycles(), decide)
    assert result.investigation_results[0].status == "no_finding"
    assert result.investigation_results[0].justification == original["conclusion"]["justification"]
    assert result.model_calls == 3 and result.tool_calls == 3
    assert model.schemas[-1] == "BoundaryCitationRepair"
    assert len(json.dumps(model.contexts[-1])) < len(json.dumps(model.contexts[-2]))


def test_invalid_citation_patch_is_not_accepted(tmp_path):
    def decide(context):
        if "validation_error" in context:
            return {"action": "patch", "corrections": [{"subject_id": "conclusion", "field": "relationship_ids",
                "values": ["relationship:still-invented"]}]}
        return conclusion(context, relationship_ids=["relationship:invented"])
    result, _, _ = audit(tmp_path, cycles(), decide)
    assert result.investigation_results[0].status == "inconclusive"
    assert not result.candidates and not result.findings
    assert result.evidence and result.model_calls == 3


def test_both_reference_errors_can_be_corrected_in_one_patch_turn(tmp_path):
    def decide(context):
        if "validation_error" not in context:
            return conclusion(context, components=["parts0"], relationship_ids=["relationship:invented"])
        catalog = context["reference_catalog"]
        return {"action": "patch", "corrections": [
            {"subject_id": "conclusion", "field": "components", "values": list(catalog["source_evidence_by_component"])},
            {"subject_id": "conclusion", "field": "relationship_ids", "values": [edge["id"] for edge in catalog["examined_relationships"]]}]}
    result, _, _ = audit(tmp_path, cycles(), decide)
    assert result.investigation_results[0].status == "no_finding"
    assert result.model_calls == 3 and result.tool_calls == 3


def test_json_fallback_repairs_citations_with_the_same_strict_checks(tmp_path):
    class JSONModel(Model):
        with_structured_output = None
    def decide(context):
        if "validation_error" not in context:
            return conclusion(context, components=["parts0"])
        return {"action": "patch", "corrections": [{"subject_id": "conclusion", "field": "components",
            "values": list(context["reference_catalog"]["source_evidence_by_component"])}]}
    result, _, _ = audit(tmp_path, cycles(), decide, model_type=JSONModel)
    assert result.investigation_results[0].status == "no_finding"
    assert result.model_calls == 3 and result.tool_calls == 3


def test_real_planned_only_edge_requires_tool_verification_before_citation(tmp_path):
    requested = None
    def decide(context):
        nonlocal requested
        catalog = context["reference_catalog"]
        if "validation_error" in context:
            assert context["errors"][0]["invalid_value"] == requested and context["errors"][0]["planned_only"]
            return {"action": "tools", "queries": [catalog["verification_queries"][requested] | {
                "reason": "Verify the other real cycle edge before citing it."}]}
        if requested is None:
            requested = catalog["planned_only_relationship_ids"][0]
            return conclusion(context, relationship_ids=[requested])
        assert requested in {edge["id"] for edge in catalog["examined_relationships"]}
        return conclusion(context)
    result, _, tools = audit(tmp_path, cycles(), decide)
    assert result.investigation_results[0].status == "no_finding"
    assert len(result.investigation_results[0].relationship_ids) == 2
    assert result.model_calls == 4 and result.tool_calls == 4
    assert sum(item.tool == "get_source_excerpt" for item in tools.tool_measurements) == 2


def test_narrower_source_request_reuses_initial_range_and_provenance(tmp_path, caplog):
    caplog.set_level("INFO", logger="server.architecture-boundary")
    first = True
    delivered = None
    def decide(context):
        nonlocal first, delivered
        if first:
            first = False
            delivered = {ref["id"] for ref in context["evidence"]}
            return {"action": "tools", "queries": [{"tool": "get_source_excerpt", "arguments": {
                "path": context["investigation"]["scope"][0], "start_line": 1, "end_line": 1},
                "reason": "Revisit the precise import line."}]}
        assert delivered == {ref["id"] for ref in context["evidence"]}
        return conclusion(context)
    result, _, _ = audit(tmp_path, cycles(), decide)
    assert result.investigation_results[0].status == "no_finding"
    assert result.model_calls == 3 and result.tool_calls == 3
    events = [json.loads(record.getMessage().removeprefix("investigation_trace ")) for record in caplog.records
        if record.getMessage().startswith("investigation_trace ")]
    tool_events = [event for event in events if event["transition"] == "tool_result"]
    assert [event["cached"] for event in tool_events] == [False, False, False, True]
    assert tool_events[-1]["tool_call_id"] in {event["tool_call_id"] for event in tool_events[:-1]}


def test_missing_component_source_cannot_be_repaired_with_metadata_ids(tmp_path):
    def decide(context):
        if "validation_error" in context:
            assert context["errors"][0]["available_source_evidence_ids"]
            ids = [ref["id"] for ref in context["reference_catalog"]["evidence"] if ref["kind"] == "metadata"]
            return {"action": "patch", "corrections": [{"subject_id": "conclusion", "field": "evidence_ids", "values": ids}]}
        response = conclusion(context)
        response["conclusion"]["evidence_ids"] = [next(iter(context["reference_catalog"]["source_evidence_by_component"].values()))[0]]
        return response
    result, _, _ = audit(tmp_path, cycles(), decide)
    assert result.investigation_results[0].status == "inconclusive"


@pytest.mark.parametrize("repair_candidate", [False, True])
def test_correct_candidate_keeps_strict_source_and_dependency_provenance(tmp_path, repair_candidate):
    contents = {"parts0/a.py": "from .b import _f\ndef f(): return _f()\n",
        "parts0/b.py": "from .a import f\n__all__ = ['public']\ndef public(): return 1\ndef _f(): return 2\n"}
    def decide(context):
        if "validation_error" in context:
            assert context["errors"][0]["subject_id"] == "private-access"
            return {"action": "patch", "corrections": [{"subject_id": "private-access", "field": "components",
                "values": list(context["reference_catalog"]["source_evidence_by_component"])}]}
        response = conclusion(context, "finding_candidate", summary="Possible interface bypass found in the inspected source.",
            justification="The export declaration and consuming import support a provisional interface-bypass concern.")
        record = response["conclusion"]
        record["candidates"] = [{"id": "private-access", "title": "Possible public interface bypass",
            "description": "The consumer imports _f directly rather than the declared public export.",
            "criterion_id": context["criteria"][0]["id"], "kind": "design_observation", "severity": "low",
            "confidence": .7, "justification": "Both the explicit export and consuming import were read.",
            "modularity_impact": "The dependency may bypass the declared entrypoint.", "recommendation": "Check the intended access path.",
            "inferred_boundary": "__all__ exposes public, not _f.", "contradictory_dependency": "a imports _f from b.",
            "technical_basis": "Inspected export declaration and direct import/use.",
            **{field: record[field] for field in ("components", "evidence_ids", "relationship_ids")}}]
        if repair_candidate:
            record["candidates"][0]["components"] = ["parts0"]
        return response
    result, _, _ = audit(tmp_path, contents, decide)
    assert result.investigation_results[0].status == "finding_candidate"
    assert len(result.candidates) == len(result.findings) == 1
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert result.candidates[0].relationship_ids and len(result.candidates[0].components) == 2
    assert result.model_calls == (3 if repair_candidate else 2) and result.tool_calls == 3


def test_inconclusive_closes_without_inventing_a_boundary(tmp_path):
    result, _, _ = audit(tmp_path, cycles(), lambda context: conclusion(context, "inconclusive",
        limitations=["The inspected cycle does not establish an intended architectural boundary."]))
    assert result.investigation_results[0].status == "inconclusive"
    assert result.model_calls == 2 and not result.candidates
