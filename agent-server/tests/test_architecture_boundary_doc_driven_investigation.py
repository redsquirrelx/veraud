"""Offline documentary investigation: provenance and code citations are independent."""

import asyncio
import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from test_architecture_boundary_doc_driven_planning import claim, context, prepare

from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven import (
    AuditRequest,
    BoundaryConfig,
)
from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.document_investigation import (
    documentary_context,
)
from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.execution import (
    BoundaryExecution,
)
from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.investigation import (
    initial_queries,
)
from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.schemas import (
    BoundaryResult,
)
from server.runtimes.repository.context import RepositoryContext
from server.runtimes.repository.schemas import ExecutionBudget, RepositoryInput
from server.runtimes.repository.tools import RepositoryToolset
from server.services.repository_analysis import RepositoryAnalysisService


@pytest.fixture
def tools(tmp_path):
    return verified_tools(tmp_path, {
        "app/__init__.py": "",
        "app/api.py": "from .store import Store\ndef use(): return Store()\n",
        "app/store.py": "class Store:\n    pass\n",
    })


def verified_tools(tmp_path, contents):
    root = tmp_path / "repo"
    root.mkdir()
    for path, text in contents.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    for args in (["init", "-q"], ["add", "."], ["-c", "user.name=Tests", "-c", "user.email=tests@example.invalid",
        "commit", "-qm", "fixture"]):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    snapshot = RepositoryAnalysisService().analyze_sync(root)
    return RepositoryToolset(RepositoryContext(snapshot, RepositoryInput(snapshot_hash=snapshot.repository.snapshot_hash,
        budget=ExecutionBudget(max_input_tokens_per_call=50_000))), workspace_root=tmp_path)


class Model:
    def __init__(self, decide):
        self.decide, self.contexts = decide, []

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages, **kwargs):
        payload = json.loads(messages[1].content)
        self.contexts.append(payload)
        value = ({"opportunity_ids": [payload["opportunities"][0]["id"]]}
            if "opportunities" in payload else self.decide(payload))
        return AIMessage(content=json.dumps(value),
            usage_metadata={"input_tokens": 100, "output_tokens": 100, "total_tokens": 200})


def close(payload, statuses=None, *, status="no_finding", candidate=False):
    source = [ref for ref in payload["evidence"] if ref["kind"] == "source"]
    ids, paths = [ref["id"] for ref in source], list(dict.fromkeys(ref["path"] for ref in source))
    assessments = [{"claim_id": key, "status": outcome,
        "rationale": "The architectural dependency clause applies only to this interaction; inspected construction and use establish the local mechanism, not business correctness.",
        "code_evidence_ids": ids, "scope_paths": paths,
        "exceptions_examined": ["Observed construction, not a type-only annotation."],
        "limitations": ["Only this local portion was inspected; other owners remain unexamined."]}
        for key, outcome in (statuses or {}).items()]
    result = {"investigation_id": payload["investigation"]["id"], "status": status,
        "summary": "Local architectural investigation.", "justification": "The source shows an actual constructor dependency, not merely an absent edge.",
        "components": paths, "evidence_ids": ids, "claim_assessments": assessments,
        "limitations": ["This is a bounded local inspection."]}
    if candidate:
        contradicted = [key for key, outcome in statuses.items() if outcome == "contradicted"]
        result["candidates"] = [{"id": "local-candidate", "criterion_id": payload["criteria"][0]["id"],
            "title": "Potential forbidden concrete dependency", "description": "The consumer constructs the concrete provider.",
            "kind": "design_observation", "components": paths, "evidence_ids": ids,
            "justification": "Applicable documented prohibition contrasted with source implementation and use.",
            "modularity_impact": "Potential boundary contradiction only.", "severity": "low", "confidence": .7,
            "recommendation": "Review the intended contract and any exception.",
            "inferred_boundary": "The supplied rule prohibits this directed concrete dependency.",
            "contradictory_dependency": "use constructs Store directly.", "technical_basis": "Both source files inspected; no type-only exception in this local use.",
            "document_claim_ids": contradicted}]
    return {"action": "close", "conclusion": result}


def run(tools, source, decide, *, transform=None, **overrides):
    model = Model(decide)
    config = BoundaryConfig(**({"provider_request_interval_seconds": 0, "max_schema_retries": 0,
        "max_context_characters": 100_000, "max_total_tokens": 200_000,
        "max_tokens_per_investigation": 100_000, "max_output_tokens": 1800,
        "max_planned_investigations": 1} | overrides))
    execution = BoundaryExecution(model, config, tools, AuditRequest(documented_architecture=source))

    async def invoke():
        with execution.timing.stage("investigation"):
            state = execution.initial_state()
            state.update(await execution.plan_investigation(state))
            menu, inventory, _ = prepare(tools, source)
            task = next((item for item in menu if item.structural_signal.kind == "documented_boundary"), menu[0])
            plan = state["plan"].model_copy(update={"investigations": [task], "document_claims": inventory["_document_claims"]})
            state.update(plan=plan, result=state["result"].model_copy(update={"plan": plan}))
            if transform:
                transform(state)
            for _ in range(30):
                state.update(await execution.investigate(state))
                route = execution.route_investigation(state)
                if route == "synthesis":
                    break
                if route == "tools":
                    state.update(await execution.execute_investigation_tools(state))
            else:
                pytest.fail("Investigation failed to terminate within existing limits")
            assert BoundaryResult.model_validate_json(state["result"].model_dump_json()) == state["result"]
            return state
    return asyncio.run(invoke()), model, execution


def assess_all(payload, outcome="supported", **kwargs):
    return close(payload, {key: outcome for key in payload["documentary_context"]["claims"]}, **kwargs)


def test_code_first_without_documentation_is_unchanged(tmp_path):
    tools = verified_tools(tmp_path, {"app/a.py": "from .b import run\ndef use(): return run()\n",
        "app/b.py": "from .a import use\ndef run(): pass\n"})
    state, model, _ = run(tools, None, close)
    result = state["result"].investigation_results[0]
    assert result.status == "no_finding" and result.evidence_ids and not result.claim_assessments
    assert all("documentary_context" not in payload for payload in model.contexts if "investigation" in payload)


def test_enriched_structural_cycle_uses_the_same_claim_assessment_path(tmp_path):
    tools = verified_tools(tmp_path, {"app/a.py": "from .b import run\ndef use(): return run()\n",
        "app/b.py": "from .a import use\ndef run(): return use()\n"})
    source = context(tools, [claim("app.a and app.b must not form cycles.", subject="Feature packages", related_subjects=["app.a", "app.b"])])
    state, _, _ = run(tools, source, lambda p: assess_all(p, "contradicted", status="finding_candidate", candidate=True))
    assert state["plan"].investigations[0].structural_signal.kind == "cycle"
    assert state["result"].investigation_results[0].claim_assessments[0].status == "contradicted"


def test_normal_synthesis_and_finalize_still_accept_extended_candidates(tools):
    state, _, execution = run(tools, context(tools, [claim()]), lambda p: assess_all(p, "contradicted",
        status="finding_candidate", candidate=True))
    state.update(execution.synthesis(state))
    state.update(execution.finalize(state))
    result = state["result"]
    assert BoundaryResult.model_validate_json(result.model_dump_json()) == result
    assert result.candidates[0].document_claim_ids
    assert not {"validation_status", "review_rationale"} & result.findings[0].model_dump().keys()


@pytest.mark.parametrize("outcome", ["supported", "contradicted", "not_applicable", "inconclusive"])
def test_individual_outcome_and_provisional_candidate(tools, outcome):
    source = context(tools, [claim()])
    state, model, _ = run(tools, source, lambda p: assess_all(p, outcome,
        status="finding_candidate" if outcome == "contradicted" else "inconclusive" if outcome == "inconclusive" else "no_finding",
        candidate=outcome == "contradicted"))
    result = state["result"].investigation_results[0]
    assert result.claim_assessments[0].status == outcome, result.limitations
    assert not state["result"].findings  # Runner stopping point precedes finalization.
    if outcome == "contradicted":
        assert result.candidates[0].document_claim_ids == [result.claim_assessments[0].claim_id]
    payload = next(p for p in model.contexts if "investigation" in p)
    assert payload["documentary_context"]["claims"]
    assert set(result.claim_assessments[0].code_evidence_ids) <= set(result.evidence_ids)
    assert not set(source.section_paths) & set(result.evidence_ids)
    coverage = state["result"].investigation_coverage
    assert coverage["documentation"]["investigated"] == 0
    assert coverage["documentary_investigation"]["investigated"] == 1
    assert not coverage["documentary_investigation"]["whole_claim_compliance_established"]


def test_multiple_claims_are_independent_and_no_catalog_leak(tools):
    source = context(tools, [claim(), claim("app.api may depend on app.store implementations.", constraint="allowed"),
        claim("app.api must not depend on app.store implementations and order totals must equal 42."),
        claim("An unrelated widget must display correctly.", subject="Widget", related_subjects=[], constraint="unspecified")])
    def decide(p):
        claims = p["documentary_context"]["claims"]
        outcomes = {key: "supported" if item["constraint"] == "allowed" else
            "not_applicable" if "42" in item["statement"] else "contradicted" for key, item in claims.items()}
        return close(p, outcomes, status="finding_candidate", candidate=True)
    state, model, _ = run(tools, source, decide)
    result = state["result"].investigation_results[0]
    assert {a.status for a in result.claim_assessments} == {"supported", "not_applicable", "contradicted"}
    projection = next(p["documentary_context"] for p in model.contexts if "investigation" in p)
    assert len(projection["claims"]) == 3 and len(state["plan"].document_claims) == 4
    assert all("widget" not in item["statement"] for item in projection["claims"].values())


def test_documented_boundary_without_planned_relationships_loads_source(tools):
    state, _, execution = run(tools, context(tools, [claim()]), assess_all)
    task = state["plan"].investigations[0]
    assert task.structural_signal.kind == "documented_boundary" and task.structural_signal.relationships
    queries = initial_queries(tools.accessible_snapshot, task, execution.config.tools)
    assert queries[0].tool == "list_relationships"
    assert all(q.tool == "get_source_excerpt" for q in queries[1:])
    assert state["result"].investigation_results[0].status == "no_finding"


def test_global_claim_remains_local_even_when_a_portion_is_supported(tmp_path):
    contents = {"app/__init__.py": "", "app/api/__init__.py": "", "app/store/__init__.py": ""}
    for index in range(7):
        contents[f"app/api/a{index}.py"] = f"from app.store.s{index} import Store\ndef use(): return Store()\n"
        contents[f"app/store/s{index}.py"] = "class Store: pass\n"
    tools = verified_tools(tmp_path, contents)
    source = context(tools, [claim("app.api may depend on app.store implementations.", constraint="allowed")])
    state, _, _ = run(tools, source, assess_all)
    record = next(iter(state["plan"].document_claims.values()))
    result = state["result"].investigation_results[0]
    assert len(record.portions) > 1 and len(record.scope_paths) > 12
    assert result.claim_assessments[0].status == "supported"
    assert set(result.claim_assessments[0].scope_paths) < set(record.scope_paths)
    coverage = state["result"].investigation_coverage["documentary_investigation"]
    assert coverage["investigated"] == 1 and not coverage["whole_claim_compliance_established"]
    assert all(row["local_only"] for row in coverage["assessments"])


def test_bounded_projection_omits_whole_claim_not_literal_quotes(tools):
    rule = claim(evidence=[{"section_id": "s1", "start_line": 1, "end_line": 1, "quote": "literal " * 10_000}])
    source = context(tools, [rule])
    menu, inventory, _ = prepare(tools, source)
    task = next(item for item in menu if item.document_claim_ids)
    plan = SimpleNamespace(document_claims=inventory["_document_claims"])
    payload = documentary_context(task, plan, tools.accessible_snapshot, source, 4000)
    assert not payload["claims"] and payload["unavailable_claims"]
    assert next(iter(plan.document_claims.values())).claim.evidence[0].quote == rule.evidence[0].quote


def test_prompt_distinguishes_permissions_mixed_claims_and_global_coverage():
    prompt = (Path(__file__).parents[1] / "src/server/agents/maintainability/v2/modularity/architecture_boundary_doc_driven/prompts/investigate.md").read_text(encoding="utf-8")
    assert "allowed never prohibits unmentioned interactions" in prompt
    assert "assess ONLY its\n   architectural clause" in prompt
    assert "unspecified\n   requires interpreting the statement" in prompt
    assert "Never generalize local compatibility to a global rule" in prompt


@pytest.mark.parametrize("attack", ["unknown_claim", "duplicate", "claim_as_evidence", "invented_evidence", "unexamined_relationship", "invented_symbol", "no_source", "missing_candidate_claim"])
def test_invalid_assessments_and_technical_references_fail_closed(tools, attack):
    def decide(p):
        answer = assess_all(p, "contradicted", status="finding_candidate", candidate=True)
        result = answer["conclusion"]
        assessment = result["claim_assessments"][0]
        if attack == "unknown_claim":
            assessment["claim_id"] = "unknown"
        elif attack == "duplicate":
            result["claim_assessments"].append(dict(assessment))
        elif attack in {"claim_as_evidence", "invented_evidence"}:
            assessment["code_evidence_ids"] = [assessment["claim_id"] if attack == "claim_as_evidence" else "invented"]
        elif attack == "unexamined_relationship":
            result["relationship_ids"] = [tools.accessible_snapshot.relationships[0].id]
        elif attack == "invented_symbol":
            result["symbol_ids"] = ["invented"]
        elif attack == "no_source":
            assessment["code_evidence_ids"] = []
        elif attack == "missing_candidate_claim":
            result["candidates"][0]["document_claim_ids"] = []
        return answer
    state, _, _ = run(tools, context(tools, [claim()]), decide)
    result = state["result"].investigation_results[0]
    assert result.status == "inconclusive" and not result.candidates
    assert all(a.status == "inconclusive" for a in result.claim_assessments)


@pytest.mark.parametrize("damage", ["missing", "bad_section", "bad_identity"])
def test_catalog_integrity_failure_is_explicit(tools, damage):
    def transform(state):
        plan = state["plan"]
        key = plan.investigations[0].document_claim_ids[0]
        if damage == "missing":
            plan.document_claims.pop(key)
        elif damage == "bad_section":
            plan.document_claims[key] = plan.document_claims[key].model_copy(update={"section_paths": {}})
        else:
            record = plan.document_claims[key]
            plan.document_claims[key] = record.model_copy(update={"claim": record.claim.model_copy(update={"statement": "tampered"})})
    state, model, _ = run(tools, context(tools, [claim()]), lambda p: close(p, status="inconclusive"), transform=transform)
    result = state["result"].investigation_results[0]
    assert result.claim_assessments[0].status == "inconclusive"
    assert any("Document claim" in item for item in result.limitations)
    assert next(p["documentary_context"]["unavailable_claims"] for p in model.contexts if "investigation" in p)


def test_missing_assessment_is_pending_not_implicit_no_finding(tools):
    state, _, _ = run(tools, context(tools, [claim()]), close)
    result = state["result"].investigation_results[0]
    assert result.status == "inconclusive" and result.claim_assessments[0].status == "inconclusive"
    assert state["result"].investigation_coverage["documentary_investigation"]["pending_claim_ids"]


def test_missing_code_never_supports_documentary_compatibility(tools):
    state, _, _ = run(tools, context(tools, [claim()]), assess_all, max_tools_per_investigation=0,
        max_calls_per_investigation=1)
    assert state["result"].tool_calls == 0
    assert state["result"].investigation_results[0].status == "inconclusive"


def test_contradicted_directed_edge_requires_both_source_endpoints(tools):
    def decide(p):
        edges = p["reference_catalog"]["examined_relationships"]
        if not edges:
            source = next(ref for ref in p["evidence"] if ref["path"] == "app/api.py")
            return {"action": "tools", "queries": [{"tool": "list_relationships", "arguments": {"source_id": source["file_id"]},
                "reason": "Verify the observed import direction."}]}
        answer = assess_all(p, "contradicted", status="inconclusive")
        edge = next(item for item in edges if item["source_path"] == "app/api.py" and item["target_path"] == "app/store.py")
        answer["conclusion"]["relationship_ids"] = [edge["id"]]
        assessment = answer["conclusion"]["claim_assessments"][0]
        assessment["code_evidence_ids"] = [ref["id"] for ref in p["evidence"] if ref["kind"] == "source" and ref["path"] == "app/api.py"]
        assessment["scope_paths"] = ["app/api.py"]
        return answer
    state, _, _ = run(tools, context(tools, [claim()]), decide)
    result = state["result"].investigation_results[0]
    assert result.status == "inconclusive" and result.claim_assessments[0].status == "inconclusive"


def test_documentary_uncertainty_cannot_become_supported_by_source_alone(tools):
    source = context(tools, [claim()])
    def transform(state):
        for key, record in state["plan"].document_claims.items():
            state["plan"].document_claims[key] = record.model_copy(update={"status": "uncertain"})
    state, _, _ = run(tools, source, assess_all, transform=transform)
    assert state["result"].investigation_results[0].claim_assessments[0].status == "inconclusive"


def test_existing_repair_can_patch_assessment_citations_without_rewriting_status(tools):
    def decide(p):
        if "validation_error" in p:
            item = p["claim_assessments"][0]
            ids = [ref["id"] for ref in p["reference_catalog"]["evidence"] if ref["kind"] == "source"]
            return {"action": "patch", "corrections": [{"subject_id": "claim:" + item["claim_id"],
                "field": "code_evidence_ids", "values": ids}]}
        answer = assess_all(p)
        answer["conclusion"]["claim_assessments"][0]["code_evidence_ids"] = ["wrong"]
        return answer
    state, model, _ = run(tools, context(tools, [claim()]), decide, max_schema_retries=1)
    result = state["result"].investigation_results[0]
    assert result.status == "no_finding" and result.claim_assessments[0].status == "supported"
    assert sum("validation_error" in p for p in model.contexts) == 1


def test_runner_reaches_investigate_but_not_synthesis_and_retains_claims(tools):
    path = Path(__file__).parents[1] / "src/test-agents/run_architecture_boundary_doc_driven.py"
    spec = importlib.util.spec_from_file_location("doc_runner_investigation", path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    model = Model(lambda p: assess_all(p) if "documentary_context" in p else close(p))
    config = BoundaryConfig(provider_request_interval_seconds=0, max_total_tokens=200_000,
        max_tokens_per_investigation=100_000, max_context_characters=100_000, max_planned_investigations=1)
    result = asyncio.run(runner.InvestigationOnlyBoundaryAgent(model, config).run(tools,
        AuditRequest(documented_architecture=context(tools, [claim()]))))
    assert result.investigation_results and not result.findings
    assert result.next_phase == "synthesis" and result.termination_reason == "investigations_completed"
    assert set(result.consumption_by_phase) == {"plan_investigation", "investigate"}
    assert all("synthesis" not in node for node in runner.InvestigationOnlyExecution(model, config, tools,
        AuditRequest()).graph.get_graph().nodes)
