"""Real native graph/indexes/read-only tools; only model responses are simulated.

Optional paid evaluation: COMPONENT_ADAPTABILITY_LIVE=1 and pytest -k live -s.
"""

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import ValidationError
from test_architecture_boundary import NativeStructuredModel, fingerprints, toolset

from server.agents.maintainability.reusability.component_adaptability import (
    ComponentAdaptabilityAgent,
    ComponentAdaptabilityConfig,
    ComponentAdaptabilityRequest,
    ComponentAdaptabilityResult,
)
from server.agents.maintainability.reusability.component_adaptability.discovery import discover
from server.agents.maintainability.reusability.component_adaptability.schemas import (
    InspectionDecision,
    InspectRoute,
    ValidationRoute,
)
from server.runtimes.investigation.schemas import AuditResult

SEED = Path(__file__).parent / "fixtures" / "component_adaptability"
TARGET = "Reuse with a supplied offline backend and no fixed production endpoint."
READY = {"action": "validate", "tool_requests": []}


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "checkout"
    shutil.copytree(SEED, root)
    return root


def request(**updates):
    return ComponentAdaptabilityRequest(**({"targets": ["service.py"], "target_context": TARGET} | updates))


def limits(**updates):
    return ComponentAdaptabilityConfig(**({"max_iterations": 1, "max_total_tokens": 300_000,
        "provider_rate_limits": {"requests_per_minute": None, "tokens_per_minute": None}} | updates))


def plan():
    return {"objectives": ["Check fixed backend and injection seams against target context"], "components": [],
        "hypotheses": [{"id": "h1", "question": "Is backend substitution blocked by the public construction path?", "criterion_id": "component-adaptability"}]}


def read(root, paths=None, relationships=True):
    paths = paths if paths is not None else ["service.py", "consumer.py", "backend.py"]
    tools = [{"name": "get_source_excerpt", "arguments_json": json.dumps({"path": p, "start_line": 1,
        "end_line": len((root / p).read_text(encoding="utf-8").splitlines())})} for p in paths]
    if relationships:
        tools.insert(0, {"name": "list_relationships", "arguments_json": json.dumps({"resolution": "internal", "limit": 50})})
    return {"action": "use_tools", "tool_requests": tools}


def evaluate(messages, *, conclusion=None, finding=True, mutate=None, caller_path="consumer.py"):
    context = json.loads(messages[1].content)
    component = context["selected_components"][0]
    target = context["target_context"]
    conclusion = conclusion or ("verified_obstacle" if target else "context_dependent_risk")
    refs = [r for r in context["evidence"] if r["kind"] == "source"]
    own = [r["id"] for r in refs if r["file_id"] == component["file_id"]]
    consumer = [r for r in refs if r["path"] == caller_path]
    envelopes = [json.loads(m.content) for m in messages if isinstance(m, ToolMessage) and m.content.startswith("{")]
    edges = [e for response in envelopes if response.get("tool_name") == "list_relationships" and response.get("data")
             for e in response["data"].get("items", [])]
    edge = next((e for e in edges if consumer and e["source_id"] == consumer[0]["file_id"]
                 and e["target_id"] == component["file_id"] and e["kind"] != "contains"), None)
    usage = [{"caller_id": consumer[0]["file_id"], "relationship_id": edge["id"],
        "evidence_ids": [r["id"] for r in consumer],
        "instantiation_configuration": "The inspected consumer constructs ReportService without backend or endpoint arguments."}] if edge else []
    assessment = {"id": "a1", "component_id": component["component_id"], "hypothesis_id": "h1",
        "constraint_type": "dependency_injection", "constraint_key": "database:fixed-production-endpoint",
        "conclusion": conclusion, "assessed_context": target or "Plausible offline reuse with a substituted backend.",
        "context_basis": "explicit" if target else "plausible",
        "observed_facts": ["The constructor creates ProductionClient with a literal endpoint; publish delegates to that member."],
        "adaptation_impact": "The current public construction path offers no supplied-backend parameter for the stated context; callers would need an override or other adaptation.",
        "adaptation_effort": "Qualitative: review construction/configuration and dependent callers; no measured effort estimate.",
        "assumptions": [] if target else ["Offline backend substitution is a plausible scenario, not a declared user requirement."],
        "supporting_evidence_ids": [r["id"] for r in refs], "counterevidence_ids": [], "usage": usage,
        "seam_analysis": "Inspected constructor and public methods; no injection parameter is present. Attribute reassignment remains possible and wider factories are not globally excluded.",
        "seam_evidence_ids": own, "counterevidence_analysis": "An external override or mutation could mitigate the default path; the conclusion is scoped to the inspected public construction path.",
        "unknowns": [] if conclusion != "unknown" else ["Configuration/factory reachability remains unverified."],
        "mitigation_options": ["Consider a caller-supplied backend if offline use is a real requirement; do not refactor automatically."],
        "limitations": ["The seeded backend stores a dictionary; no real database connection or runtime effect is claimed."]}
    candidate = {"id": "ADAPT-001", "title": "Fixed backend construction constrains supplied-backend reuse",
        "description": assessment["observed_facts"][0], "criterion_id": "component-adaptability", "kind": "design_observation",
        "components": [component["component_id"]], "evidence_ids": [r["id"] for r in refs] or ["missing-evidence"],
        "justification": assessment["counterevidence_analysis"], "modularity_impact": assessment["adaptation_impact"],
        "severity": "low", "confidence": 0.8, "recommendation": assessment["mitigation_options"][0],
        "assessment_ids": ["a1"], "constraint_type": "dependency_injection",
        "classification": conclusion if conclusion in {"verified_obstacle", "context_dependent_risk"} else "context_dependent_risk"}
    value = {"sufficient": True, "hypotheses": [{**plan()["hypotheses"][0],
        "status": "discarded" if conclusion == "mitigated" else "inconclusive" if conclusion == "unknown" else "confirmed", "rationale": "Compared inspected body and construction context."}],
        "candidates": [candidate] if finding else [], "missing_information": [],
        "constraint_assessments": [assessment], "cleared_components": [],
        "coverage_rationale": "Selected component body and representative construction context inspected; no global portability claim."}
    if mutate:
        mutate(value)
    return value


def review(*ids, status="accepted"):
    return {"findings": [{"finding_id": identifier, "status": status,
        "rationale": "Inspected source, scoped target and counterevidence support this qualified observation.",
        "severity": "low", "confidence": 0.8} for identifier in ids], "limitations": []}


def run(root, responses, *, config=None, audit_request=None, tools=None):
    tools = tools or toolset(root)
    model = NativeStructuredModel(responses)
    result = asyncio.run(ComponentAdaptabilityAgent(model, config or limits()).run(tools, audit_request or request()))
    return result, model, tools


def normal(root, *, audit_request=None, **evaluation_options):
    return run(root, [plan(), read(root), READY, lambda m: evaluate(m, **evaluation_options),
        review("ADAPT-001") if evaluation_options.get("finding", True) else review()], audit_request=audit_request)


def test_real_e2e_direct_source_provenance_routes_and_read_only(repo):
    before = fingerprints(repo)
    result, model, tools = normal(repo)
    assert result.status == "completed", result.model_dump_json(indent=2)
    assert isinstance(result, AuditResult) and result.quality_attribute == "reusability"
    f = result.findings[0]
    assert f.validation_status == "accepted" and f.classification == "verified_obstacle"
    assert f.stable_id.startswith("ADAPT-") and f.assessed_context == result.target_context == TARGET
    assert f.adaptation_impact and f.adaptation_effort
    assert result.model_calls == len(model.history) == 5 and result.tool_calls == 4
    assert len(result.tool_activity) == 4 and all(m.seconds >= 0 for m in result.tool_activity)
    assert result.execution_trace == ["plan_investigation", "investigate", "route:use_tools", "tools", "investigate",
        "route:validate", "evaluate_evidence", "route:finalize", "review_findings", "finalize"]
    assert all(v >= 0 for v in result.node_durations_seconds.values()) and "finalize" in result.node_durations_seconds
    assert all(r.snapshot_hash == tools.context.input.snapshot_hash for r in f.evidence)
    assert all(1 <= r.start_line <= r.end_line <= next(s.line_count for s in tools.accessible_snapshot.files if s.id == r.file_id) for r in f.evidence)
    assert fingerprints(repo) == before
    assert ComponentAdaptabilityResult.model_validate_json(result.model_dump_json()) == result
    assert "InspectionDecision" in [s[0] for s in model.schemas]


def test_validation_gap_returns_to_inspection_and_completes(repo):
    result, model, _ = run(repo, [plan(), read(repo, ["service.py"]), READY, evaluate,
        read(repo, ["consumer.py", "backend.py"]), READY, evaluate, review("ADAPT-001")], config=limits(max_iterations=2))
    assert result.status == "completed" and result.iterations == 2
    assert "route:inspect" in result.execution_trace
    assert "verified_obstacle_requires_usage_inspection" in model.history[4][1].content


def test_unspecified_target_is_qualified_not_invented(repo):
    result, _, _ = normal(repo, audit_request=request(target_context=None))
    assert result.status == "completed" and result.target_context is None
    assert result.findings[0].classification == "context_dependent_risk"
    assert result.findings[0].assumptions and result.examined_constraints[0].context_basis == "plausible"


def test_existing_injection_seam_disproves_suspected_rigidity(repo):
    def seam(value):
        a = value["constraint_assessments"][0]
        a.update(observed_facts=["Constructor accepts client and selects it when not None."],
            seam_analysis="The explicit client parameter permits backend substitution without changing the component.",
            adaptation_impact="No demonstrated obstacle for supplying an offline backend through the constructor.",
            counterevidence_analysis="Default concrete construction does not make that dependency mandatory.")
    result, _, _ = run(repo, [plan(), read(repo, ["flexible.py", "backend.py"]), READY,
        lambda m: evaluate(m, conclusion="mitigated", finding=False, mutate=seam), review()],
        audit_request=request(targets=["flexible.py"]))
    assert result.status == "completed" and not result.findings
    assert result.hypotheses[0].status == "discarded"
    assert result.examined_constraints[0].conclusion == "mitigated"


@pytest.mark.parametrize("fault", ["body", "citation", "seam", "target", "unknowns", "component", "caller", "blank_analysis", "components", "type"])
def test_host_prevents_unsupported_acceptance(repo, fault):
    def corrupt(value):
        a, c = value["constraint_assessments"][0], value["candidates"][0]
        if fault == "body":
            a["supporting_evidence_ids"] = []
        elif fault == "citation":
            a["supporting_evidence_ids"].append("invented-citation")
        elif fault == "seam":
            a["seam_evidence_ids"] = []
        elif fault == "target":
            a["assessed_context"] = "Invented target requirement"
        elif fault == "unknowns":
            a["unknowns"] = ["Factory substitution remains unverified"]
        elif fault == "component":
            a["component_id"] = "out-of-scope-component"
        elif fault == "caller":
            a["usage"][0]["relationship_id"] = "invented-edge"
        elif fault == "blank_analysis":
            a["seam_analysis"] = " "
        elif fault == "components":
            c["components"] = ["invented-component"]
        else:
            c["constraint_type"] = "platform"
    result, _, _ = normal(repo, mutate=corrupt)
    assert result.status == "partial" and result.findings[0].validation_status == "insufficient_evidence"
    assert result.execution_trace[-1] == "limited_finalize"


def test_unqualified_claim_without_explicit_target_is_blocked(repo):
    result, _, _ = normal(repo, audit_request=request(target_context=None), conclusion="verified_obstacle")
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert "verified_obstacle_requires_explicit_target" in result.examined_constraints[0].validation_issues


def test_unknown_is_preserved_not_reported_as_defect(repo):
    result, _, _ = normal(repo, conclusion="unknown", finding=False)
    assert result.status == "partial" and not result.findings
    assert result.examined_constraints[0].conclusion == "unknown" and result.missing_information


def test_tool_missing_file_preserves_partial_evidence(repo):
    decision = read(repo)
    decision["tool_requests"][1]["arguments_json"] = json.dumps({"path": "missing.py"})
    result, _, _ = run(repo, [plan(), decision, READY, evaluate, review("ADAPT-001")])
    assert result.status == "partial" and result.tool_failures
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert result.examined_constraints[0].evidence


@pytest.mark.parametrize("config", [{"max_total_tokens": 1000}, {"max_tool_calls": 0}, {"max_model_calls": 4}, {"max_context_characters": 4000}])
def test_resource_limits_terminate_without_invented_success(repo, config):
    result, _, _ = run(repo, [plan(), read(repo), READY, evaluate, review("ADAPT-001")], config=limits(**config))
    assert result.status in {"partial", "failed"} and result.execution_trace[-1] == "limited_finalize"
    assert not any(f.validation_status == "accepted" for f in result.findings)


def test_repeated_queries_reuse_cache_without_bypassing_admission(repo, monkeypatch):
    tools = toolset(repo)
    query = tools._query
    queries = []
    def counted(*args, **kwargs):
        queries.append(args[0])
        return query(*args, **kwargs)
    monkeypatch.setattr(tools, "_query", counted)
    result, _, _ = run(repo, [plan(), read(repo), read(repo), READY, evaluate, review("ADAPT-001")], tools=tools)
    assert result.status == "completed" and result.tool_calls == 8 and len(queries) == 4
    assert sum(m.cache_hit for m in tools.tool_measurements) == 4


def test_structured_inspection_routes_are_closed_and_validated():
    assert InspectionDecision.model_validate(READY).action == InspectRoute.VALIDATE
    assert ValidationRoute("limited_finalize") == ValidationRoute.LIMITED_FINALIZE
    for value in [{"action": "guess", "tool_requests": []}, {"action": "use_tools", "tool_requests": []},
                  {"action": "validate", "tool_requests": [{"name": "list_files", "arguments_json": "{}"}]}]:
        with pytest.raises(ValidationError):
            InspectionDecision.model_validate(value)
    with pytest.raises(ValidationError):
        request(target_context=" ")


@pytest.mark.parametrize("decision", [
    {"action": "use_tools", "tool_requests": [{"name": "get_source_excerpt", "arguments_json": "not json"}]},
    {"action": "use_tools", "tool_requests": [{"name": "get_source_excerpt", "arguments_json": '{"path":"service.py","start_line":-1}'}]},
])
def test_invalid_tool_arguments_stop_safely_before_execution(repo, decision):
    result, _, _ = run(repo, [plan(), decision])
    assert result.status == "partial" and result.termination_reason == "invalid_inspection_decision"
    assert result.tool_calls == 0


def test_invalid_route_exhausts_bounded_schema_corrections(repo):
    bad = {"action": "retry_forever", "tool_requests": []}
    result, model, _ = run(repo, [plan(), bad, bad])
    assert result.status == "partial" and result.termination_reason == "model_or_schema_error"
    assert len(model.history) == 3 and result.tool_calls == 0


def test_freeform_readiness_is_not_a_valid_route(repo):
    prose = AIMessage(content="Ready to validate without a structured decision")
    result, model, _ = run(repo, [plan(), prose, prose])
    assert result.termination_reason == "model_or_schema_error" and result.tool_calls == 0
    assert len(model.history) == 3


def test_disabled_tool_cannot_be_executed(repo):
    result, _, _ = run(repo, [plan(), read(repo)], config=limits(tools=["get_source_excerpt"]))
    assert result.termination_reason == "invalid_inspection_decision" and result.tool_calls == 0


def test_discovery_index_selection_signal_bounds_and_scope(repo):
    snapshot = toolset(repo).accessible_snapshot
    coverage = discover(snapshot, request(), limits())
    assert coverage == discover(snapshot, request(), limits())
    c = coverage.selected_components[0]
    assert c.symbol == "ReportService" and c.path == "service.py"
    assert any(s.constraint_type == "dependency_injection" for s in c.signals)
    selected = discover(snapshot, request(component_ids=[c.component_id]), limits())
    assert selected.selected_components == coverage.selected_components
    for target in ["../outside", "missing.py", "README.md"]:
        with pytest.raises(ValueError):
            discover(snapshot, request(targets=[target]), limits())
    with pytest.raises(ValueError):
        discover(snapshot, request(component_ids=["invented-symbol"]), limits())
    broad = discover(snapshot, request(targets=[]), limits(max_components=1, max_scan_files=1))
    assert broad.omitted_components > 0 and broad.omitted_scan_files > 0


@pytest.mark.parametrize("dirty", [False, True])
def test_git_revision_provenance_is_checked(repo, dirty):
    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    git("init")
    git("-c", "core.autocrlf=false", "add", ".")
    git("-c", "user.name=Offline Test", "-c", "user.email=test@example.invalid", "commit", "-m", "seed")
    if dirty:
        with (repo / "service.py").open("a", encoding="utf-8") as stream:
            stream.write("# uncommitted change\n")
    before = fingerprints(repo)
    result, _, _ = normal(repo)
    assert (result.findings[0].validation_status == "accepted") is (not dirty)
    assert fingerprints(repo) == before


def test_same_root_constraint_across_files_consolidates_evidence(repo):
    (repo / "service2.py").write_text((repo / "service.py").read_text(encoding="utf-8"), encoding="utf-8")
    (repo / "consumer2.py").write_text((repo / "consumer.py").read_text(encoding="utf-8").replace("from service ", "from service2 "), encoding="utf-8")
    def combined(messages):
        context = json.loads(messages[1].content)
        values = []
        for index, component in enumerate(context["selected_components"], 1):
            scoped = {**context, "selected_components": [component]}
            altered = [messages[0], HumanMessage(content=json.dumps(scoped)), *messages[2:]]
            value = evaluate(altered, caller_path="consumer.py" if component["path"] == "service.py" else "consumer2.py")
            value["constraint_assessments"][0]["id"] = "a" + str(index)
            value["candidates"][0].update(id="ADAPT-00" + str(index), assessment_ids=["a" + str(index)])
            values.append(value)
        first = values[0]
        first["constraint_assessments"] = [a for v in values for a in v["constraint_assessments"]]
        first["candidates"] = [c for v in values for c in v["candidates"]]
        return first
    paths = ["service.py", "service2.py", "consumer.py", "consumer2.py", "backend.py"]
    result, _, _ = run(repo, [plan(), read(repo, paths), READY, combined, review("ADAPT-001", "ADAPT-002")],
        audit_request=request(targets=["service.py", "service2.py"]))
    assert result.status == "completed"
    accepted = [f for f in result.findings if f.validation_status == "accepted"]
    assert len(accepted) == 1 and len(accepted[0].components) == len(accepted[0].assessment_ids) == 2
    assert len(accepted[0].evidence_ids) == len(set(accepted[0].evidence_ids))
    assert result.findings[1].duplicate_of == accepted[0].id
    assert {e.path for e in accepted[0].evidence} == set(paths)


def test_duplicate_assessment_ids_are_not_support(repo):
    def duplicate(value):
        value["constraint_assessments"].append(value["constraint_assessments"][0].copy())
    result, _, _ = normal(repo, mutate=duplicate)
    assert result.status == "partial" and result.findings[0].validation_status == "insufficient_evidence"


def test_constraint_limit_is_host_enforced(repo):
    def many(value):
        value["constraint_assessments"].append({**value["constraint_assessments"][0], "id": "a2"})
    result, _, _ = run(repo, [plan(), read(repo), READY, lambda m: evaluate(m, mutate=many)], config=limits(max_constraints=1))
    assert result.status == "partial" and result.termination_reason == "constraint_limit"
    assert result.execution_trace[-1] == "limited_finalize"


def test_unverifiable_blocker_finalizes_without_wasting_iterations(repo):
    def blocked(value):
        value.update(sufficient=False, can_investigate_further=False,
            continuation_reason="External deployment override contract is unavailable in the accessible snapshot.")
    result, model, _ = run(repo, [plan(), read(repo), READY,
        lambda m: evaluate(m, conclusion="unknown", finding=False, mutate=blocked), review()], config=limits(max_iterations=3))
    assert result.status == "partial" and result.termination_reason == "unverifiable"
    assert result.iterations == 1 and len(model.history) == 5
    assert any("External deployment override" in s for s in result.limitations)


def test_no_actionable_gap_does_not_cause_an_unconditional_loop(repo):
    result, model, _ = run(repo, [plan(), read(repo), READY,
        lambda m: evaluate(m, mutate=lambda value: value.update(sufficient=False)), review("ADAPT-001")], config=limits(max_iterations=3))
    assert result.status == "partial" and result.termination_reason == "no_actionable_gap"
    assert result.iterations == 1 and len(model.history) == 5


def test_unspecified_context_without_assumptions_is_not_source_backed(repo):
    def unqualified(value):
        value["constraint_assessments"][0]["assumptions"] = []
    result, _, _ = normal(repo, audit_request=request(target_context=None), mutate=unqualified)
    assert result.findings[0].validation_status == "insufficient_evidence"


def test_declaration_only_source_is_not_body_evidence(repo):
    decision = read(repo)
    for item in decision["tool_requests"]:
        if item["name"] == "get_source_excerpt":
            args = json.loads(item["arguments_json"])
            if args["path"] == "service.py":
                args["end_line"] = 4
                item["arguments_json"] = json.dumps(args)
    result, _, _ = run(repo, [plan(), decision, READY, evaluate, review("ADAPT-001")])
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert "component_body_not_inspected" in result.examined_constraints[0].validation_issues


def test_adjacent_bounded_reads_can_cover_a_complete_component(repo):
    decision = read(repo)
    for item in decision["tool_requests"]:
        if item["name"] == "get_source_excerpt":
            args = json.loads(item["arguments_json"])
            if args["path"] == "service.py":
                args["end_line"] = 6
                item["arguments_json"] = json.dumps(args)
                break
    decision["tool_requests"].append({"name": "get_source_excerpt",
        "arguments_json": json.dumps({"path": "service.py", "start_line": 7, "end_line": 9})})
    result, _, _ = run(repo, [plan(), decision, READY, evaluate, review("ADAPT-001")])
    assert result.status == "completed" and result.findings[0].validation_status == "accepted"


def test_clearance_requires_source_and_preserves_empty_findings(repo):
    def clear(messages):
        context = json.loads(messages[1].content)
        return {"sufficient": True, "hypotheses": [{**plan()["hypotheses"][0], "status": "discarded", "rationale": "No demonstrated obstacle in the inspected scope."}],
            "candidates": [], "constraint_assessments": [], "missing_information": [],
            "cleared_components": [c["component_id"] for c in context["selected_components"]],
            "coverage_rationale": "Scoped body inspection did not establish a target-incompatible dependency; not a global guarantee."}
    result, _, _ = run(repo, [plan(), read(repo), READY, clear, review()])
    assert result.status == "completed" and not result.findings
    unverified, _, _ = run(repo, [plan(), READY, clear, review()])
    assert unverified.status == "partial" and unverified.coverage.unassessed_components


def test_empty_scope_can_validate_directly_without_unnecessary_tools(repo):
    (repo / "empty.py").write_text("", encoding="utf-8")
    result, _, _ = run(repo, [{"objectives": [], "components": [], "hypotheses": []}, READY,
        {"sufficient": True, "hypotheses": [], "candidates": [], "constraint_assessments": [], "missing_information": [],
         "cleared_components": [], "coverage_rationale": "No accessible nonempty component in the requested file."}, review()],
        audit_request=request(targets=["empty.py"]))
    assert result.status == "completed" and result.tool_calls == 0
    assert "tools" not in result.execution_trace and result.execution_trace[-1] == "finalize"
    assert not result.coverage.exhaustive


def test_supported_evidence_survives_later_provider_failure(repo):
    def gap(value):
        value.update(sufficient=False, missing_information=["Inspect one additional override configuration site"])
    result, _, _ = run(repo, [plan(), read(repo), READY, lambda m: evaluate(m, mutate=gap), RuntimeError("simulated provider failure")],
        config=limits(max_iterations=2))
    assert result.status == "partial" and result.examined_constraints[0].evidence and result.findings
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert result.termination_reason == "model_or_schema_error"


def test_initial_provider_failure_is_failed_not_successful_empty_result(repo):
    result, _, _ = run(repo, [RuntimeError("simulated initial provider failure")])
    assert result.status == "failed" and not result.findings
    assert any("provider_request" in s for s in result.limitations)


def test_deadline_and_cancellation_are_respected(repo):
    class Slow(NativeStructuredModel):
        async def ainvoke(self, messages, **kwargs):
            await asyncio.sleep(1)
            return await super().ainvoke(messages, **kwargs)
    result = asyncio.run(ComponentAdaptabilityAgent(Slow([plan()]), limits(timeout_seconds=0.05)).run(toolset(repo), request()))
    assert result.status == "failed" and result.termination_reason == "time_limit"
    before = fingerprints(repo)
    async def cancel():
        entered = asyncio.Event()
        class Waiting(NativeStructuredModel):
            async def ainvoke(self, messages, **kwargs):
                entered.set()
                await asyncio.Event().wait()
        task = asyncio.create_task(ComponentAdaptabilityAgent(Waiting([]), limits()).run(toolset(repo), request()))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(cancel())
    assert fingerprints(repo) == before


@pytest.mark.parametrize("extension,content", [
    ("js", "export class Service { constructor() { this.path = process.env.HOME; } }\n"),
    ("ts", "export class Service { path: string | undefined = process.env.HOME; }\n"),
])
def test_js_ts_discovery_uses_real_indexed_locations(repo, extension, content):
    path = "component." + extension
    (repo / path).write_text(content, encoding="utf-8")
    coverage = discover(toolset(repo).accessible_snapshot, request(targets=[path]), limits())
    component = coverage.selected_components[0]
    assert component.symbol == "Service" and component.start_line == component.end_line == 1
    assert any(s.constraint_type == "environment" for s in component.signals)


def test_shared_yaml_harness_and_tracing_accept_specialized_result(repo, capsys):
    from run_architecture_boundary import run_audit

    from server.app.tracing_port import NoOpTracingBackend
    from server.config.schemas import ModelSettings

    spans = []
    class Trace(NoOpTracingBackend):
        async def wrap_stage(self, coro, *, name, **metadata):
            spans.append((name, metadata))
            return await coro
    model = NativeStructuredModel([plan(), read(repo), READY, evaluate, review("ADAPT-001")])
    asyncio.run(run_audit(SimpleNamespace(max_files=100), repo, request(), limits(), model,
        ModelSettings(provider="google", name="simulated-provider", temperature=0, max_tokens=4000),
        tracing_backend=Trace(), agent_class=ComponentAdaptabilityAgent))
    result = ComponentAdaptabilityResult.model_validate_json(capsys.readouterr().out)
    assert result.status == "completed" and spans[0][0] == "component-adaptability"
    assert spans[0][1]["agent_type"] == "component-adaptability"


def test_google_native_adapter_structured_decisions_and_usage_offline(repo, monkeypatch):
    from google.genai import types
    from langchain_google_genai import ChatGoogleGenerativeAI

    from server.runtimes.investigation.agent import InvestigationExecution

    tools, config = toolset(repo), limits(max_output_tokens=512)
    model = ChatGoogleGenerativeAI(model="gemini-3.5-flash-lite", api_key="offline-test-key", max_tokens=2048, max_retries=0)
    requests, responses = [], []
    execute = tools.execute
    def observe(*args, **kwargs):
        result = execute(*args, **kwargs)
        responses.append(result)
        return result
    monkeypatch.setattr(tools, "execute", observe)
    async def generate_content(**kwargs):
        requests.append(kwargs)
        turn = len(requests)
        if turn == 1:
            value = plan()
        elif turn == 2:
            assert kwargs["config"].response_json_schema["title"] == "InspectionDecision"
            value = read(repo)
        elif turn == 3:
            value = READY
        elif turn == 4:
            schema = kwargs["config"].response_json_schema
            assert schema["title"] == "AdaptabilityEvaluation" and "maxItems" not in json.dumps(schema)
            coverage = discover(tools.accessible_snapshot, request(), config)
            context = {"selected_components": [c.model_dump() for c in coverage.selected_components], "target_context": TARGET,
                "evidence": [r.model_dump() for r in InvestigationExecution.references(SimpleNamespace(tools=tools))]}
            value = evaluate([HumanMessage(content=""), HumanMessage(content=json.dumps(context)),
                *[ToolMessage(content=r.model_dump_json(), tool_call_id=r.tool_call_id) for r in responses]])
        elif turn == 5:
            value = review("ADAPT-001")
        else:
            raise AssertionError("Unexpected provider call")
        return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part(text=json.dumps(value))]), finish_reason="STOP")],
            usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=100, candidates_token_count=30, total_token_count=130))
    monkeypatch.setattr(model.async_client.models, "generate_content", generate_content)
    result = asyncio.run(ComponentAdaptabilityAgent(model, config).run(tools, request()))
    assert result.status == "completed" and result.findings[0].validation_status == "accepted"
    assert result.model_calls == len(requests) == 5 and result.accounted_tokens == 650 and result.estimated_tokens == 0
    assert model.max_output_tokens == 2048 and all(r["config"].max_output_tokens == 512 for r in requests)


@pytest.mark.skipif(os.getenv("COMPONENT_ADAPTABILITY_LIVE") != "1", reason="Opt-in paid model evaluation")
def test_live_seeded_model_evaluation(repo, capsys):
    from run_architecture_boundary import load_test_model, run_audit

    from server.runtimes.repository.model_runtime import close_model_clients

    model, settings = load_test_model(os.getenv("COMPONENT_ADAPTABILITY_AGENT_CONFIG", "dummy"))
    async def live():
        try:
            await run_audit(SimpleNamespace(max_files=100), repo, request(),
                ComponentAdaptabilityConfig(max_components=1, max_constraints=4, max_model_calls=12,
                    max_total_tokens=100_000, timeout_seconds=240), model, settings, agent_class=ComponentAdaptabilityAgent)
        finally:
            await close_model_clients(SimpleNamespace(llm=model))
    asyncio.run(live())
    result = ComponentAdaptabilityResult.model_validate_json(capsys.readouterr().out)
    print("LIVE evaluation (not deterministic proof of semantic accuracy):", result.model_dump_json(indent=2))
    assert result.status in {"completed", "partial"} and result.plan is not None
    assert result.examined_constraints and any(a.validation_status == "source_backed" for a in result.examined_constraints)
    assert result.coverage.inspected_paths
