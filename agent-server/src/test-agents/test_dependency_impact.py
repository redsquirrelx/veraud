r"""Ejecutar desde agent-server (PowerShell):

    uv run pytest src/test-agents/test_dependency_impact.py -q

Todas las pruebas: uv run pytest src/test-agents -q
Offline: LLM simulado, grafo LangGraph y herramientas reales sobre fixtures pequeñas.
No requiere claves ni consume API. Ejecución real (puede generar costes):
uv run python src/test-agents/run_dependency_impact.py C:\repos\proyecto
"""

import asyncio
import importlib.util
import json
import subprocess
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from test_architecture_boundary import (
    NativeStructuredModel,
    ScriptedModel,
    fingerprints,
    toolset,
)

from server.agents.maintainability.modularity.architecture_boundary import (
    ArchitectureBoundaryAgent,
)
from server.agents.maintainability.modularity.dependency_impact import (
    DependencyImpactAgent,
    DependencyImpactConfig,
    DependencyImpactRequest,
    DependencyImpactResult,
)
from server.agents.maintainability.modularity.responsibility import ResponsibilityAgent
from server.config.schemas import ModelSettings
from server.contracts.legacy_schemes.base import Hypothesis
from server.infrastructure.tracing import NoOpTracingBackend
from server.runtimes.investigation.agent import InvestigationExecution

PLAN = {"objectives": ["Assess provider replacement costs"], "components": ["OrderService", "PaymentGateway"],
        "hypotheses": [{"id": "h1", "question": "Does provider-specific response handling couple order processing to a gateway?",
                        "criterion_id": "concrete-coupling", "priority": "high",
                        "evidence_needed": ["Dependency declaration", "Consumer usage", "Gateway contract and counterevidence"]}]}


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "orders.py").write_text(
        "from gateway import PaymentGateway\n\n"
        "class OrderService:\n"
        "    def __init__(self):\n"
        "        self.gateway = PaymentGateway()\n"
        "    def pay(self, amount):\n"
        "        response = self.gateway.charge(amount)\n"
        "        return response['provider_token']\n", encoding="utf-8",
    )
    (root / "gateway.py").write_text(
        "class PaymentGateway:\n"
        "    def charge(self, amount):\n"
        "        return {'provider_token': str(amount)}\n", encoding="utf-8",
    )
    (root / "client.py").write_text(
        "from orders import OrderService\n"
        "def checkout(amount):\n"
        "    return OrderService().pay(amount)\n", encoding="utf-8",
    )
    return root


def tool_call(name, arguments, identifier):
    return AIMessage(content="", tool_calls=[{"name": name, "args": arguments, "id": identifier}])


def queries(tools, paths=("orders.py", "gateway.py"), graph_all=False):
    files = {f.path: f for f in tools.accessible_snapshot.files}
    arguments = {"resolution": "internal", "limit": 20}
    if not graph_all:
        arguments["source_id"] = files["orders.py"].id
    return [tool_call("list_relationships", arguments, "graph"), *[
        tool_call("get_source_excerpt", {"path": path, "start_line": 1, "end_line": files[path].line_count}, f"source-{i}")
        for i, path in enumerate(paths)
    ]]


def evaluate(messages, *, sufficient=True, candidate=True, legitimate=False, impact="plausible_risk",
             basis="consequence_evidence", path_names=None, demonstrate=False):
    envelopes = [json.loads(m.content) for m in messages if isinstance(m, ToolMessage)]
    evidence = [r for e in envelopes for r in e.get("evidence", [])]
    ids = list(dict.fromkeys(r["id"] for r in evidence))
    source_ids = [r["id"] for r in evidence if r["kind"] == "source"]
    edges = [r for e in envelopes if e.get("tool_name") == "list_relationships"
             for r in e.get("data", {}).get("items", []) if r["kind"] != "contains" and r["target_id"]]
    paths = {e["data"]["path"]: e["data"]["file_id"] for e in envelopes
             if e.get("tool_name") == "get_source_excerpt" and e.get("status") == "ok"}
    if path_names:
        ordered = [paths[name] for name in path_names]
        pairs = set(pairwise(ordered))
        edges = [e for e in edges if (e["source_id"], e["target_id"]) in pairs]
    else:
        edges = edges[:1]
        ordered = [edges[0]["source_id"], edges[0]["target_id"]]
    links = [{"id": f"d{i}", "source_id": edge["source_id"], "target_id": edge["target_id"],
              "relationship_id": edge["id"], "dependency_type": edge["kind"], "evidence_ids": ids}
             for i, edge in enumerate(edges)]
    assessment = {
        "id": "a1", "hypothesis_id": "h1", "dependencies": links, "dependency_path": ordered,
        "contract_analysis": "The consumer constructs the concrete gateway and reads its provider_token return field.",
        "architectural_justification": "Considered whether gateway encapsulation and intended co-evolution justify this contract.",
        "impact_kind": "none" if legitimate else impact if sufficient else "inconclusive",
        "consequence": "Replacing the provider response format can require edits to order processing.",
        "change_scenario": "Replace the gateway with a provider returning a transaction object rather than provider_token.",
        "propagation_explanation": "The consumer indexes a provider-specific key; contract replacement requires adapting that code.",
        "supporting_evidence_ids": source_ids, "contradicting_evidence_ids": [],
        "demonstration_evidence_ids": source_ids if demonstrate else [],
        "demonstration_rationale": "The current concrete constructor and direct field access structurally prevent substituting a differently shaped contract without consumer adaptation." if demonstrate else "",
        "uncertainty": "medium", "limitations": ["No historical changes or runtime modifications were simulated."],
    }
    finding = {
        "id": "f1", "title": "Provider-specific contract leaks into order handling",
        "description": "Order processing depends on the concrete gateway return shape.",
        "criterion_id": "concrete-coupling", "kind": "design_observation", "components": ["OrderService", "PaymentGateway"],
        "evidence_ids": ids, "justification": assessment["propagation_explanation"],
        "modularity_impact": assessment["consequence"], "severity": "medium", "confidence": 0.85,
        "recommendation": "Normalize provider results at the gateway boundary if independent provider replacement is required.",
        "assessment_ids": ["a1"], "basis": basis,
    }
    return {"sufficient": sufficient, "hypotheses": [dict(PLAN["hypotheses"][0],
                 status="discarded" if legitimate else "confirmed" if sufficient else "inconclusive", evidence_ids=source_ids)],
            "candidates": [finding] if candidate else [], "dependency_assessments": [assessment],
            "missing_information": [] if sufficient else ["Inspect the gateway contract and its consumers"]}


def review(status="accepted", candidate=True):
    def respond(messages):
        context = json.loads(messages[1].content)
        return {"findings": [{"finding_id": "f1", "status": status,
                          "rationale": "Compared declaration, endpoint contracts, scenario and architectural alternatives.",
                          "severity": "medium", "confidence": 0.8}] if candidate else [], "limitations": [],
                "hypotheses": [{"hypothesis_id": h["id"], "status": "supported", "rationale": "Checked local endpoint usage and contract.",
                    "assessment_ids": ["a1"], "checked_evidence_ids": h["evidence_ids"], "scope_supported": True}
                    for h in context["hypotheses"] if h["status"] in {"confirmed", "discarded"}]}
    return respond


def run_audit(repo, *, evaluator=evaluate, reviewer=None, model_type=ScriptedModel, config=None,
              paths=("orders.py", "gateway.py"), graph_all=False):
    tools = toolset(repo)
    model = model_type([PLAN, *queries(tools, paths, graph_all), AIMessage(content="Ready"), evaluator, reviewer or review()])
    result = asyncio.run(DependencyImpactAgent(model, config or DependencyImpactConfig(max_total_tokens=300_000, max_iterations=1)).run(tools))
    return result, model, tools


def test_graph_dependency_tools_impact_review_results_and_read_only(repo):
    before = fingerprints(repo)
    result, model, tools = run_audit(repo)
    assert isinstance(result, DependencyImpactResult)
    assert issubclass(DependencyImpactAgent.execution_type, InvestigationExecution)
    assert result.plan.hypotheses[0].id == "h1"
    assert isinstance(model.history[2][-1], ToolMessage)
    assert result.tool_calls == 3
    assert result.termination_reason == "sufficient_evidence"
    assert result.findings[0].validation_status == "accepted"
    assert result.findings[0].confidence == 0.8
    assessment = result.dependency_assessments[0]
    assert assessment.impact_kind == "plausible_risk"
    assert assessment.dependencies[0].validation_status == "source_backed"
    assert assessment.dependencies[0].source.path == "orders.py"
    assert assessment.dependencies[0].target.path == "gateway.py"
    assert not assessment.is_cycle
    assert all(e.snapshot_hash == tools.context.input.snapshot_hash for e in assessment.evidence)
    assert fingerprints(repo) == before
    assert DependencyImpactResult.model_validate_json(result.model_dump_json()) == result


def test_all_auditors_share_the_same_graph(repo):
    assert (DependencyImpactAgent.execution_type._build_graph is ResponsibilityAgent.execution_type._build_graph
            is ArchitectureBoundaryAgent.execution_type._build_graph)
    result, model, _ = run_audit(repo, model_type=NativeStructuredModel)
    assert [name for name, _, _ in model.schemas] == ["InvestigationPlan", "DependencyImpactEvaluation", "DependencyImpactReview"]
    assert result.findings[0].validation_status == "accepted"


def test_transient_evaluation_failure_retries_the_same_stage_without_repeating_investigation(repo):
    class Unavailable(Exception):
        status_code = 503

    tools = toolset(repo)
    model = ScriptedModel([PLAN, *queries(tools), AIMessage(content="Ready"),
        Unavailable(), Unavailable(), evaluate, review()])
    config = DependencyImpactConfig(max_total_tokens=300_000, provider_retry_backoff_seconds=0)
    result = asyncio.run(DependencyImpactAgent(model, config).run(tools))
    assert result.termination_reason == "sufficient_evidence"
    assert result.findings[0].validation_status == "accepted"
    assert result.tool_calls == 3  # graph and source reads were not restarted
    assert result.plan.hypotheses[0].id == "h1"
    assert not result.deferred_stages
    assert model.history[5] == model.history[6] == model.history[7]


@pytest.mark.parametrize("long_quota_wait", [False, True])
def test_unavailable_evaluation_preserves_source_and_hypotheses_as_explicitly_pending(repo, long_quota_wait):
    class Unavailable(Exception):
        status_code = 429 if long_quota_wait else 503
        response = SimpleNamespace(headers={"retry-after": "44378"} if long_quota_wait else {})

    tools = toolset(repo)
    model = ScriptedModel([PLAN, *queries(tools), AIMessage(content="Ready"), *[Unavailable() for _ in range(3)]])
    config = DependencyImpactConfig(max_total_tokens=300_000, max_provider_retries=2, provider_retry_backoff_seconds=0)
    result = asyncio.run(DependencyImpactAgent(model, config).run(tools))
    assert result.termination_reason == ("provider_retry_wait_limit" if long_quota_wait else "provider_recovery_exhausted")
    assert result.tool_calls == 3
    assert {item.path for item in result.evidence if item.kind == "source"} == {"orders.py", "gateway.py"}
    assert result.plan.hypotheses[0].id == result.hypotheses[0].id == "h1"
    assert result.deferred_stages[0].node == "evaluate_evidence"
    assert result.deferred_stages[0].http_status == (429 if long_quota_wait else 503)
    assert not result.findings  # No accepted result without evaluation/review.
    assert DependencyImpactResult.model_validate_json(result.model_dump_json()) == result


def test_legitimate_dependency_is_not_reported_as_harm(repo):
    result, _, _ = run_audit(repo, evaluator=lambda m: evaluate(m, legitimate=True, candidate=False),
                             reviewer=review(candidate=False))
    assert result.dependency_assessments[0].validation_status == "source_backed"
    assert result.dependency_assessments[0].impact_kind == "none"
    assert result.discarded_hypotheses[0].id == "h1"
    assert not result.findings


@pytest.mark.parametrize("problem", ["directory_ids", "missing_assessment", "unrelated_source", "no_endpoint_support"])
def test_discarded_hypotheses_cannot_outlive_invalid_or_unrelated_assessments(repo, problem):
    def invalid(messages):
        value = evaluate(messages, legitimate=True, candidate=False)
        assessment = value["dependency_assessments"][0]
        if problem == "directory_ids":
            assessment["dependencies"][0]["source_id"] = "app/accounting"
        elif problem == "missing_assessment":
            value["dependency_assessments"] = []
        elif problem == "unrelated_source":
            envelopes = [json.loads(m.content) for m in messages if isinstance(m, ToolMessage)]
            unrelated = next(r["id"] for e in envelopes for r in e.get("evidence", [])
                             if r["kind"] == "source" and r["path"] == "client.py")
            value["hypotheses"][0]["evidence_ids"] = [unrelated]
            for link in assessment["dependencies"]:
                link["evidence_ids"] = [i for i in link["evidence_ids"] if i != unrelated]
            assessment["supporting_evidence_ids"] = [i for i in assessment["supporting_evidence_ids"] if i != unrelated]
        else:
            assessment["supporting_evidence_ids"] = []
        return value

    result, _, _ = run_audit(repo, evaluator=invalid, reviewer=review(candidate=False),
                             paths=("orders.py", "gateway.py", "client.py"))
    assert result.hypotheses[0].status == "inconclusive"
    assert not result.discarded_hypotheses
    assert "h1" in result.inconclusive_investigations
    assert result.missing_information
    assert result.termination_reason != "sufficient_evidence"
    if problem in {"directory_ids", "no_endpoint_support"}:
        assessment = result.dependency_assessments[0]
        assert assessment.impact_kind == "inconclusive"
        assert assessment.consequence.startswith("Unverified model interpretation:")


@pytest.mark.parametrize("problem", ["absent", "scope", "invented_citation", "duplicate", "wrong_hypothesis"])
def test_hypothesis_review_requires_exact_scope_and_binding(repo, problem):
    def reviewer(messages):
        value = review(candidate=False)(messages)
        judgment = value["hypotheses"][0]
        if problem == "absent":
            value["hypotheses"] = []
        elif problem == "scope":
            judgment["scope_supported"] = False
        elif problem == "invented_citation":
            judgment["checked_evidence_ids"].append("not-delivered")
        elif problem == "duplicate":
            value["hypotheses"].append(dict(judgment))
        else:
            judgment["hypothesis_id"] = "other-question"
        return value

    result, _, _ = run_audit(repo, evaluator=lambda m: evaluate(m, legitimate=True, candidate=False), reviewer=reviewer)
    assert result.hypotheses[0].status == "inconclusive"
    assert result.termination_reason == "evidence_validation_failed"
    assert result.critical_review is not None


def test_host_feedback_repairs_component_identity_with_delivered_evidence(repo):
    tools = toolset(repo)

    def wrong_identity(messages):
        value = evaluate(messages, legitimate=True, candidate=False)
        value["dependency_assessments"][0]["dependencies"][0]["source_id"] = "app/accounting"
        return value

    model = ScriptedModel([PLAN, *queries(tools), AIMessage(content="Ready"), wrong_identity,
        AIMessage(content="Correct IDs from delivered source; no new tool needed"),
        lambda m: evaluate(m, legitimate=True, candidate=False), review(candidate=False)])
    result = asyncio.run(DependencyImpactAgent(model, DependencyImpactConfig(max_total_tokens=300_000)).run(tools))
    assert result.iterations == 2
    assert "unknown_component_id" in model.history[6][1].content
    assert result.tool_calls == 3
    assert result.dependency_assessments[0].validation_status == "source_backed"
    assert result.hypotheses[0].status == "discarded"
    assert result.termination_reason == "sufficient_evidence"
    assert not result.missing_information


def test_repeated_invalid_relation_stops_for_review_without_spending_more_iterations(repo):
    tools = toolset(repo)

    def unresolved(messages):
        value = evaluate(messages, legitimate=True, candidate=False)
        link = value["dependency_assessments"][0]["dependencies"][0]
        link.update(relationship_id=None, dependency_type="none")
        return value

    model = ScriptedModel([PLAN, *queries(tools), AIMessage(content="Ready"), unresolved,
        AIMessage(content="Still unresolved"), unresolved, review(candidate=False)])
    result = asyncio.run(DependencyImpactAgent(model, DependencyImpactConfig(
        max_total_tokens=300_000, max_iterations=5)).run(tools))
    assert result.termination_reason == "no_investigation_progress"
    assert result.iterations == 2
    assert result.critical_review is not None
    assert result.hypotheses[0].status == "inconclusive"
    assert result.tool_calls == 3


def test_closing_reservation_allows_evaluation_and_review_under_hard_budget(repo, monkeypatch):
    tools = toolset(repo)
    execution = DependencyImpactAgent.execution_type
    original = execution.closing_token_reserve

    def simulate_prior_consumption(self, node, reserve):
        if node == "investigate" and self.calls == 4:
            self.tokens = self.token_limit - int(2.9 * reserve)
        return original(self, node, reserve)

    monkeypatch.setattr(execution, "closing_token_reserve", simulate_prior_consumption)
    # The next exploration request is withheld, so evaluation is the next response.
    model = ScriptedModel([PLAN, *queries(tools), evaluate, review()])
    result = asyncio.run(DependencyImpactAgent(model, DependencyImpactConfig(max_total_tokens=300_000)).run(tools))
    assert result.termination_reason == "token_limit"
    assert result.dependency_assessments
    assert result.critical_review is not None
    assert result.findings[0].validation_status == "accepted"
    assert result.accounted_tokens <= 300_000
    assert any("token_budget_reserved_for_closing" in item for item in result.limitations)


def test_navigation_and_targeted_endpoint_reads_do_not_claim_inspection(repo):
    tools = toolset(repo)
    execution = DependencyImpactAgent.execution_type(ScriptedModel([]), DependencyImpactConfig(), tools,
                                                    DependencyImpactRequest())
    state = execution.initial_state()
    context = execution.model_context("investigate", state)
    edge = next(r for r in context["dependency_navigation"] if r["source_path"] == "orders.py")
    assert edge["navigation_only"]
    assert edge["target_path"] == "gateway.py"
    assert not execution.references()
    assert "dependency_navigation" not in execution.model_context("evaluate_evidence", state)


def test_provider_compaction_preserves_cited_source_and_authoritative_history(repo):
    tools = toolset(repo)
    execution = DependencyImpactAgent.execution_type(ScriptedModel([]), DependencyImpactConfig(), tools,
                                                    DependencyImpactRequest())
    state = execution.initial_state()
    # Compact an old, uncited search payload, retaining a cited excerpt and recent turns.
    payload = lambda identifier: json.dumps({"evidence": [{"id": identifier, "kind": "source"}], "data": "x" * 20_000})
    messages = [ToolMessage(content=payload(identifier), tool_call_id=identifier, name="get_source_excerpt")
                for identifier in ("old", "pinned", "recent1", "recent2")]
    state["messages"] = messages
    state["hypotheses"] = [Hypothesis(id="h", question="Local contract?", evidence_ids=["pinned"])]
    before = [m.model_dump() for m in messages]
    compacted = execution.provider_history(state, [], overhead_characters=100_000, node="review_findings")
    assert json.loads(compacted[0].content)["history_compacted"]
    assert compacted[1].content == messages[1].content
    assert [m.model_dump() for m in messages] == before


@pytest.mark.parametrize("basis", ["metrics_only", "cycle_only", "transitivity_only", "interface_shape_only", "dependency_existence_only"])
def test_structural_indicators_alone_cannot_establish_harm(repo, basis):
    result, _, _ = run_audit(repo, evaluator=lambda m: evaluate(m, basis=basis))
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert result.findings[0].confidence == 0


@pytest.mark.parametrize("demonstrate", [False, True])
def test_demonstrated_impact_requires_additional_grounding(repo, demonstrate):
    result, _, _ = run_audit(repo, evaluator=lambda m: evaluate(m, impact="demonstrated", demonstrate=demonstrate))
    assert result.findings[0].validation_status == ("accepted" if demonstrate else "insufficient_evidence")
    assert result.dependency_assessments[0].impact_kind == ("demonstrated" if demonstrate else "inconclusive")


def test_critical_review_can_reject_a_structurally_valid_candidate(repo):
    result, _, _ = run_audit(repo, reviewer=review("rejected"))
    assert result.findings[0].validation_status == "rejected"


def test_no_harm_assessment_cannot_support_a_harm_finding(repo):
    result, _, _ = run_audit(repo, evaluator=lambda m: evaluate(m, legitimate=True))
    assert result.dependency_assessments[0].impact_kind == "none"
    assert result.findings[0].validation_status == "insufficient_evidence"


def test_graph_metadata_alone_cannot_establish_impact(repo):
    result, _, _ = run_audit(repo, paths=())
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert result.dependency_assessments[0].impact_kind == "inconclusive"
    assert not any(e.kind == "source" for e in result.dependency_assessments[0].evidence)


def test_unrelated_source_cannot_replace_the_actual_dependency_declaration(repo):
    tools = toolset(repo)
    requests = queries(tools)
    requests[1] = tool_call("get_source_excerpt", {"path": "orders.py", "start_line": 3, "end_line": 8}, "consumer-body-only")
    model = ScriptedModel([PLAN, *requests, AIMessage(content="Ready"), evaluate, review()])
    result = asyncio.run(DependencyImpactAgent(model).run(tools))
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert "dependency_declaration_not_inspected" in result.dependency_assessments[0].dependencies[0].validation_issues


def test_unresolved_relationship_retains_limitation_and_cannot_be_accepted(repo):
    def unresolved(messages):
        value = evaluate(messages)
        value["dependency_assessments"][0]["dependencies"][0]["relationship_id"] = None
        value["dependency_assessments"][0]["limitations"].append("Static relationship could not be resolved reliably.")
        return value
    result, _, _ = run_audit(repo, evaluator=unresolved)
    assessment = result.dependency_assessments[0]
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert assessment.impact_kind == "inconclusive"
    assert "Static relationship could not be resolved reliably." in assessment.limitations


@pytest.mark.parametrize("problem", ["edge", "kind", "target", "citations", "scenario", "propagation", "support", "path", "hypothesis", "criterion", "declaration"])
def test_host_validation_rejects_unverifiable_dependency_or_impact(repo, problem):
    def invalid(messages):
        value = evaluate(messages)
        assessment = value["dependency_assessments"][0]
        edge = assessment["dependencies"][0]
        if problem == "edge":
            edge["relationship_id"] = "invented-edge"
        elif problem == "kind":
            edge["dependency_type"] = "runtime_call"  # An import cannot be relabeled as a call.
        elif problem == "target":
            edge["target_id"] = "invented-component"
        elif problem == "citations":
            edge["evidence_ids"].append("invented-citation")
        elif problem == "scenario":
            assessment["change_scenario"] = ""
        elif problem == "propagation":
            assessment["propagation_explanation"] = ""
        elif problem == "support":
            assessment["supporting_evidence_ids"] = []
        elif problem == "path":
            assessment["dependency_path"].reverse()
        elif problem == "hypothesis":
            assessment["hypothesis_id"] = "unknown-hypothesis"
        elif problem == "criterion":
            value["candidates"][0]["kind"] = "violation"
        else:
            # Delete consumer source citations, leaving only graph metadata and target code.
            envelopes = [json.loads(m.content) for m in messages if isinstance(m, ToolMessage)]
            source = next(e for e in envelopes if e.get("tool_name") == "get_source_excerpt" and e["data"]["path"] == "orders.py")
            omitted = {r["id"] for r in source["evidence"]}
            edge["evidence_ids"] = [i for i in edge["evidence_ids"] if i not in omitted]
        return value
    result, _, _ = run_audit(repo, evaluator=invalid)
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert "invented-citation" not in result.model_dump_json()
    assert "invented-edge" not in result.model_dump_json()
    if problem == "path":
        assert result.dependency_assessments[0].dependency_path == []


def test_bounded_transitive_path_and_reverse_relationship_queries(repo):
    evaluator = lambda m: evaluate(m, path_names=["client.py", "orders.py", "gateway.py"])
    result, _, _ = run_audit(repo, evaluator=evaluator, paths=("client.py", "orders.py", "gateway.py"), graph_all=True)
    assert len(result.dependency_assessments[0].dependency_path) == 3
    assert result.findings[0].validation_status == "accepted"
    shallow, _, _ = run_audit(repo, evaluator=evaluator, paths=("client.py", "orders.py", "gateway.py"), graph_all=True,
                              config=DependencyImpactConfig(max_dependency_depth=1, max_total_tokens=300_000))
    assert shallow.findings[0].validation_status == "insufficient_evidence"
    assert "dependency_depth_limit_or_invalid_path" in shallow.dependency_assessments[0].validation_issues
    tools = toolset(repo)
    gateway = next(f for f in tools.accessible_snapshot.files if f.path == "gateway.py")
    response = tools.execute("list_relationships", {"target_id": gateway.id, "resolution": "internal", "limit": 5}, tool_call_id="inverse")
    assert response.status == "ok"
    assert len(response.data["items"]) == 1
    assert response.data["items"][0]["target_id"] == gateway.id


def test_verified_cycle_does_not_automatically_become_a_finding(repo):
    original = (repo / "gateway.py").read_text(encoding="utf-8")
    (repo / "gateway.py").write_text("from orders import OrderService\n" + original, encoding="utf-8")
    result, _, _ = run_audit(repo, evaluator=lambda m: evaluate(m, path_names=["orders.py", "gateway.py", "orders.py"],
        legitimate=True, candidate=False), reviewer=review(candidate=False), graph_all=True)
    assert result.dependency_assessments[0].is_cycle
    assert result.dependency_assessments[0].validation_status == "source_backed"
    assert result.dependency_assessments[0].impact_kind == "none"
    assert not result.findings


def test_reinvestigation_recovers_missing_endpoint_evidence(repo):
    tools = toolset(repo)
    requests = queries(tools)
    model = ScriptedModel([PLAN, requests[0], requests[1], AIMessage(content="Partial"),
        lambda m: evaluate(m, sufficient=False, candidate=False), requests[2], AIMessage(content="Ready"), evaluate, review()])
    result = asyncio.run(DependencyImpactAgent(model, DependencyImpactConfig(max_total_tokens=300_000)).run(tools))
    assert result.iterations == 2
    assert "Inspect the gateway contract" in model.history[5][1].content
    assert result.findings[0].validation_status == "accepted"


@pytest.mark.parametrize("limit", ["tools", "models", "iterations", "tokens", "context", "relationships"])
def test_limits_and_partial_results(repo, limit):
    tools = toolset(repo)
    requests = queries(tools)
    options = {"max_total_tokens": 300_000}
    responses = [PLAN, *requests, AIMessage(content="Partial"),
                 lambda m: evaluate(m, sufficient=False, candidate=False), review(candidate=False)]
    expected = "iteration_limit"
    if limit == "tools":
        options["max_tool_calls"] = 1
        responses = [PLAN, requests[0], lambda m: evaluate(m, sufficient=False, candidate=False), review(candidate=False)]
        expected = "tool_call_limit"
    elif limit == "models":
        options["max_model_calls"] = 4
        responses = [PLAN, requests[0], lambda m: evaluate(m, sufficient=False, candidate=False), review(candidate=False)]
        expected = "model_call_limit"
    elif limit == "tokens":
        options["max_total_tokens"] = 1000
        expected = "token_limit"
    elif limit == "context":
        options["max_context_characters"] = 4000
        expected = "context_limit"
    elif limit == "relationships":
        result, _, _ = run_audit(repo, evaluator=lambda m: evaluate(m, path_names=["client.py", "orders.py", "gateway.py"]),
            paths=("client.py", "orders.py", "gateway.py"), graph_all=True,
            config=DependencyImpactConfig(max_relationships_per_assessment=1, max_total_tokens=300_000))
        assert result.findings[0].validation_status == "insufficient_evidence"
        assert "relationship_count_limit" in result.dependency_assessments[0].validation_issues
        return
    else:
        options["max_iterations"] = 1
    result = asyncio.run(DependencyImpactAgent(ScriptedModel(responses), DependencyImpactConfig(**options)).run(tools))
    assert result.termination_reason == expected
    assert not any(f.validation_status == "accepted" for f in result.findings)
    if result.hypotheses:
        assert result.inconclusive_investigations


@pytest.mark.parametrize("dirty", [False, True])
def test_dependency_and_impact_citations_match_the_commit(repo, dirty):
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    git("init")
    git("-c", "core.autocrlf=false", "add", ".")
    git("-c", "user.name=Offline Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture")
    if dirty:
        with (repo / "gateway.py").open("a") as stream:
            stream.write("# local change\n")
    before = fingerprints(repo)
    result, _, _ = run_audit(repo)
    assert result.findings[0].validation_status == ("insufficient_evidence" if dirty else "accepted")
    gateway_citations = [e for e in result.dependency_assessments[0].evidence if e.path == "gateway.py"]
    assert all(e.commit == (None if dirty else result.commit) for e in gateway_citations)
    assert fingerprints(repo) == before


def test_shared_live_runner_selects_correct_agent_and_tracing_span(repo, monkeypatch, capsys):
    path = Path(__file__).with_name("run_architecture_boundary.py")
    spec = importlib.util.spec_from_file_location("shared_dependency_harness", path)
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    tools = toolset(repo)
    spans = []

    class Tracer(NoOpTracingBackend):
        async def wrap_stage(self, coro, *, name, **metadata):
            spans.append((name, metadata))
            return await coro

    def wrong_agent(*args, **kwargs):
        raise AssertionError("Boundary agent must not be instantiated for dependency impact")

    monkeypatch.setattr(harness, "ArchitectureBoundaryAgent", wrong_agent)
    model = ScriptedModel([PLAN, *queries(tools), AIMessage(content="Ready"), evaluate, review()])
    asyncio.run(harness.run_audit(
        SimpleNamespace(max_files=100), repo, DependencyImpactRequest(), DependencyImpactConfig(), model,
        ModelSettings(provider="google", name="offline-model", temperature=0, max_tokens=4000),
        tracing_backend=Tracer(), agent_class=DependencyImpactAgent,
    ))
    result = json.loads(capsys.readouterr().out)
    assert result["findings"][0]["validation_status"] == "accepted"
    assert spans[0][0] == "dependency-impact"
    assert spans[0][1]["agent_type"] == "dependency_impact"
