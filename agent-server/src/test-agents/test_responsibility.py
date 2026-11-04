r"""Ejecutar desde agent-server (PowerShell):

    uv run pytest src/test-agents/test_responsibility.py -q

Todas las pruebas: uv run pytest src/test-agents -q
Pruebas offline con el grafo/herramientas reales y LLM simulado. Sin claves ni API.
Ejecución real: uv run python src/test-agents/run_responsibility.py C:\repos\proyecto
"""

import asyncio
import importlib.util
import json
import subprocess
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
from server.agents.maintainability.modularity.responsibility import (
    ResponsibilityAgent,
    ResponsibilityConfig,
    ResponsibilityRequest,
)
from server.agents.maintainability.modularity.responsibility.schemas import (
    ResponsibilityResult,
)
from server.config.schemas import ModelSettings
from server.infrastructure.tracing import NoOpTracingBackend
from server.runtimes.investigation.agent import (
    InvestigationAgent,
    InvestigationExecution,
)

PLAN = {"objectives": ["Investigate independent change reasons"], "components": ["OrderService"],
        "hypotheses": [{"id": "h1", "question": "Does OrderService mix ordering and reporting?",
                        "criterion_id": "responsibility-separation", "priority": "high",
                        "evidence_needed": ["Observed order and report behavior", "Callers and counterevidence"]}]}


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "orders.py").write_text(
        "class OrderService:\n"
        "    def create_order(self, items):\n"
        "        total = sum(item['price'] for item in items)\n"
        "        return {'items': items, 'total': total}\n"
        "\n"
        "    def render_monthly_report(self, sales):\n"
        "        rows = [str(sale['total']) for sale in sales]\n"
        "        return ','.join(rows)\n", encoding="utf-8",
    )
    (root / "controller.py").write_text(
        "from orders import OrderService\nservice = OrderService()\n"
        "def checkout(items):\n    return service.create_order(items)\n", encoding="utf-8",
    )
    return root


def source(start, end, identifier):
    return AIMessage(content="", tool_calls=[{"name": "get_source_excerpt", "id": identifier,
        "args": {"path": "orders.py", "start_line": start, "end_line": end}}])


def evaluate(messages, *, sufficient=True, coherent=False, candidate=True, basis="behavioral"):
    envelopes = [json.loads(m.content) for m in messages if isinstance(m, ToolMessage)]
    evidence = [r for envelope in envelopes for r in envelope.get("evidence", [])]
    identifiers = [r["id"] for r in evidence]
    first, last = identifiers[0], identifiers[-1]
    responsibilities = [
        {"id": "orders", "description": "Create orders and calculate their totals",
         "behaviors": ["create_order computes item totals and constructs order data"],
         "possible_change_reasons": ["Order pricing and checkout invariants change"],
         "supporting_evidence_ids": [first], "contradicting_evidence_ids": []},
        {"id": "reports", "description": "Render sales reports",
         "behaviors": ["render_monthly_report formats sales totals as comma-separated text"],
         "possible_change_reasons": ["Report export format changes independently of checkout"],
         "supporting_evidence_ids": [last], "contradicting_evidence_ids": []},
    ]
    assessment = {"id": "a1", "component_id": evidence[0]["file_id"], "responsibilities": responsibilities,
                  "potentially_incompatible": [] if coherent else [{
                      "responsibility_ids": ["orders", "reports"],
                      "independent_change_rationale": "Checkout pricing and report formats evolve independently.",
                      "maintenance_risk": "Report changes require changing the checkout implementation module.",
                  }], "cohesion": "coherent" if coherent else "mixed" if sufficient else "inconclusive",
                  "architectural_justification": "Compared observed behavior with shared-purpose orchestration.",
                  "evidence_ids": identifiers}
    finding = {"id": "f1", "title": "Unrelated reporting and order construction",
               "description": "The implementation mixes checkout data construction and report formatting.",
               "criterion_id": "responsibility-separation", "kind": "design_observation",
               "components": ["OrderService"], "evidence_ids": identifiers,
               "justification": "Observed behaviors have distinct outputs and change reasons.",
               "modularity_impact": "Report-format changes affect the module used for order creation.",
               "severity": "medium", "confidence": 0.85,
               "recommendation": "Separate report formatting if the independent change paths justify its cost.",
               "assessment_ids": ["a1"], "basis": basis}
    return {"sufficient": sufficient, "hypotheses": [dict(PLAN["hypotheses"][0],
             status="discarded" if coherent else "confirmed" if sufficient else "inconclusive",
             evidence_ids=identifiers)],
            "candidates": [finding] if candidate else [], "component_assessments": [assessment],
            "missing_information": [] if sufficient else ["Inspect report implementation and callers"]}


def review(status="accepted", candidate=True):
    def respond(messages):
        context = json.loads(messages[1].content)
        return {"findings": [{"finding_id": "f1", "status": status,
                          "rationale": "Compared concrete behavior, independent change reasons and grouping alternatives.",
                          "severity": "medium", "confidence": 0.8}] if candidate else [], "limitations": [],
                "hypotheses": [{"hypothesis_id": h["id"], "status": "supported",
                    "rationale": "The local question is supported by both observed behaviors.",
                    "assessment_ids": ["a1"], "checked_evidence_ids": h["evidence_ids"],
                    "scope_supported": True} for h in context["hypotheses"]
                    if h["status"] in {"confirmed", "discarded"}]}
    return respond


def run_audit(repo, *, evaluator=evaluate, reviewer=None, model_type=ScriptedModel, config=None):
    model = model_type([PLAN, source(2, 4, "order"), source(6, 8, "report"),
                       AIMessage(content="Ready to evaluate"), evaluator, reviewer or review()])
    tools = toolset(repo)
    agent = ResponsibilityAgent(model, config or ResponsibilityConfig(max_total_tokens=300_000))
    return asyncio.run(agent.run(tools)), model, tools


def test_graph_plan_tools_review_finalization_and_read_only(repo):
    before = fingerprints(repo)
    result, model, tools = run_audit(repo)
    assert isinstance(result, ResponsibilityResult)
    assert isinstance(ResponsibilityAgent(model), InvestigationAgent)
    assert issubclass(ResponsibilityAgent.execution_type, InvestigationExecution)
    assert ArchitectureBoundaryAgent.execution_type._build_graph is ResponsibilityAgent.execution_type._build_graph
    assert result.plan.hypotheses[0].question.startswith("Does OrderService")
    assert isinstance(model.history[2][-1], ToolMessage)  # native tools -> investigate
    assert result.tool_calls == 2
    assert result.termination_reason == "sufficient_evidence"
    assert result.findings[0].validation_status == "accepted"
    assert result.findings[0].confidence == 0.8
    component = result.components_investigated[0]
    assert component.path == "orders.py"
    assert component.validation_status == "source_backed"
    assert len(component.responsibilities) == 2
    assert all(r.snapshot_hash == tools.context.input.snapshot_hash for r in component.evidence)
    assert fingerprints(repo) == before
    assert ResponsibilityResult.model_validate_json(result.model_dump_json()) == result


def test_native_structured_output_and_specialized_evaluation_schema(repo):
    result, model, _ = run_audit(repo, model_type=NativeStructuredModel)
    assert [name for name, _, _ in model.schemas] == ["InvestigationPlan", "ResponsibilityEvaluation", "ResponsibilityReview"]
    assert result.components_investigated[0].responsibilities[0].behaviors
    assert result.findings[0].validation_status == "accepted"


def test_coherent_component_discards_hypothesis_without_findings(repo):
    result, _, _ = run_audit(repo, evaluator=lambda m: evaluate(m, coherent=True, candidate=False),
                             reviewer=review(candidate=False))
    assert not result.findings
    assert result.components_investigated[0].cohesion == "coherent"
    assert result.discarded_hypotheses[0].id == "h1"


@pytest.mark.parametrize("basis", ["metrics_only", "names_only"])
def test_metrics_or_names_alone_never_establish_a_finding(repo, basis):
    result, _, _ = run_audit(repo, evaluator=lambda m: evaluate(m, basis=basis))
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert result.findings[0].confidence == 0


def test_review_can_reject_false_positive_despite_valid_citations(repo):
    result, _, _ = run_audit(repo, reviewer=review("rejected"))
    assert result.findings[0].validation_status == "rejected"


@pytest.mark.parametrize("identity", ["orders.py", "app/accounting"])
def test_component_paths_resolve_exactly_and_unresolved_assessments_are_retained(repo, identity):
    def assess(messages):
        value = evaluate(messages, candidate=False)
        value["component_assessments"][0]["component_id"] = identity
        return value

    result, _, _ = run_audit(repo, evaluator=assess, reviewer=review(candidate=False))
    if identity == "orders.py":
        assert result.components_investigated[0].component_id.startswith("file:")
        assert result.hypotheses[0].status == "confirmed"
        assert not result.unresolved_component_assessments
    else:
        assert not result.components_investigated
        retained = result.unresolved_component_assessments[0]
        assert retained.id == "a1" and retained.cohesion == "inconclusive"
        assert retained.responsibilities and retained.evidence_ids
        assert result.hypotheses[0].status == "inconclusive"
        assert "a1" in result.inconclusive_investigations
        assert any("unknown component ID" in item for item in result.missing_information)
        assert result.termination_reason == "evidence_validation_failed"


@pytest.mark.parametrize("problem", ["absent", "scope", "citation", "assessment", "duplicate"])
def test_candidate_free_hypotheses_require_independent_scope_review(repo, problem):
    def reviewer(messages):
        value = review(candidate=False)(messages)
        judgment = value["hypotheses"][0]
        if problem == "absent":
            value["hypotheses"] = []
        elif problem == "scope":
            judgment["scope_supported"] = False
        elif problem == "citation":
            judgment["checked_evidence_ids"] = ["invented"]
        elif problem == "assessment":
            judgment["assessment_ids"] = ["unknown"]
        else:
            value["hypotheses"].append(dict(judgment))
        return value

    result, _, _ = run_audit(repo, evaluator=lambda m: evaluate(m, coherent=True, candidate=False),
                             reviewer=reviewer)
    assert result.hypotheses[0].status == "inconclusive"
    assert not result.discarded_hypotheses
    assert "Unverified model interpretation" in result.hypotheses[0].rationale
    assert result.missing_information


def test_unavailable_review_retains_assessments_and_records_pending_work(repo, monkeypatch):
    execution = ResponsibilityAgent.execution_type
    original = execution.call

    async def bounded_call(self, node, state, schema=None, guidance=""):
        if node == "review_findings":
            self.stop = "token_limit"
            return None
        return await original(self, node, state, schema, guidance)

    monkeypatch.setattr(execution, "call", bounded_call)
    result, _, _ = run_audit(repo)
    assert result.critical_review is None
    assert result.components_investigated
    assert result.hypotheses[0].status == "inconclusive"
    assert any("Complete critical review" in item for item in result.missing_information)
    assert not any(f.validation_status == "accepted" for f in result.findings)


def test_reinvestigation_when_behavior_evidence_is_missing(repo):
    tools = toolset(repo)
    model = ScriptedModel([PLAN, source(2, 4, "order"), AIMessage(content="Evaluate partial"),
        lambda m: evaluate(m, sufficient=False, candidate=False), source(6, 8, "report"),
        AIMessage(content="Ready"), evaluate, review()])
    result = asyncio.run(ResponsibilityAgent(model, ResponsibilityConfig(max_total_tokens=300_000)).run(tools))
    assert result.iterations == 2
    assert "Inspect report implementation" in model.history[4][1].content
    assert result.findings[0].validation_status == "accepted"


@pytest.mark.parametrize("limit", ["iterations", "tools", "models", "tokens", "context"])
def test_execution_limits_preserve_uncertainty(repo, limit):
    options = {"max_total_tokens": 300_000}
    responses = [PLAN, source(2, 4, "order"), AIMessage(content="Evaluate partial"),
                 lambda m: evaluate(m, sufficient=False, candidate=False), review(candidate=False)]
    if limit == "iterations":
        options["max_iterations"] = 1
    elif limit == "tools":
        options["max_tool_calls"] = 1
        responses.pop(2)
    elif limit == "models":
        options["max_model_calls"] = 4
        responses.pop(2)
    elif limit == "tokens":
        options["max_total_tokens"] = 1000
    else:
        options["max_context_characters"] = 4000
    model = ScriptedModel(responses)
    result = asyncio.run(ResponsibilityAgent(model, ResponsibilityConfig(**options)).run(toolset(repo)))
    expected = {"iterations": "iteration_limit", "tools": "tool_call_limit", "models": "model_call_limit",
                "tokens": "token_limit", "context": "context_limit"}[limit]
    assert result.termination_reason == expected
    assert not any(f.validation_status == "accepted" for f in result.findings)
    if result.hypotheses:
        assert result.inconclusive_investigations


@pytest.mark.parametrize("problem", ["component", "citations", "own_source", "change_reasons", "conflict", "coherent", "criterion"])
def test_host_rejects_unverifiable_responsibility_conclusions(repo, problem):
    def invalid(messages):
        value = evaluate(messages)
        component = value["component_assessments"][0]
        if problem == "component":
            component["component_id"] = "not-a-real-component"
        elif problem == "citations":
            component["responsibilities"][0]["supporting_evidence_ids"] = ["invented-citation"]
        elif problem == "own_source":
            component["responsibilities"][0]["supporting_evidence_ids"] = []
        elif problem == "change_reasons":
            component["responsibilities"][0]["possible_change_reasons"] = []
        elif problem == "conflict":
            component["potentially_incompatible"] = []
        elif problem == "coherent":
            component["cohesion"] = "coherent"
        else:
            value["candidates"][0]["kind"] = "violation"  # Default principles are not explicit project rules.
        return value
    result, _, _ = run_audit(repo, evaluator=invalid)
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert "invented-citation" not in result.model_dump_json()


@pytest.mark.parametrize("target_name", ["OrderService", "create_order"])
def test_symbol_identity_and_line_provenance(repo, target_name):
    tools = toolset(repo)
    target = next(s for s in tools.accessible_snapshot.symbols if s.name == target_name)

    def class_assessment(messages):
        value = evaluate(messages)
        value["component_assessments"][0]["component_id"] = target.id
        return value

    model = ScriptedModel([PLAN, source(2, 4, "order"), source(6, 8, "report"), AIMessage(content="Ready"),
                           class_assessment, review()])
    result = asyncio.run(ResponsibilityAgent(model).run(tools))
    assert result.findings[0].validation_status == ("accepted" if target_name == "OrderService" else "insufficient_evidence")
    component = result.components_investigated[0]
    assert component.symbol_name.endswith(target_name)
    assert all(r.start_line in (2, 6) for r in component.evidence)


@pytest.mark.parametrize("dirty", [False, True])
def test_assessment_citations_are_checked_against_commit(repo, dirty):
    def git(*arguments):
        return subprocess.run(["git", "-C", str(repo), *arguments], check=True, capture_output=True)
    git("init")
    git("-c", "core.autocrlf=false", "add", ".")
    git("-c", "user.name=Offline Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture")
    if dirty:
        with (repo / "orders.py").open("a") as stream:
            stream.write("# changed working copy\n")
    before = fingerprints(repo)
    result, _, _ = run_audit(repo)
    assert result.findings[0].validation_status == ("insufficient_evidence" if dirty else "accepted")
    assert result.components_investigated[0].evidence[0].commit == (None if dirty else result.commit)
    assert fingerprints(repo) == before


def test_live_harness_selects_responsibility_agent_and_tracing_span(repo, monkeypatch, capsys):
    path = Path(__file__).with_name("run_architecture_boundary.py")
    spec = importlib.util.spec_from_file_location("shared_responsibility_harness", path)
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    captured = []

    class Tracer(NoOpTracingBackend):
        async def wrap_stage(self, coro, *, name, **metadata):
            captured.append((name, metadata))
            return await super().wrap_stage(coro, name=name, **metadata)

    def must_not_run(*args, **kwargs):
        raise AssertionError("The responsibility harness must not instantiate the boundary auditor")

    monkeypatch.setattr(harness, "ArchitectureBoundaryAgent", must_not_run)
    model = ScriptedModel([PLAN, source(2, 4, "order"), source(6, 8, "report"), AIMessage(content="Ready"), evaluate, review()])
    asyncio.run(harness.run_audit(
        SimpleNamespace(max_files=100), repo, ResponsibilityRequest(), ResponsibilityConfig(), model,
        ModelSettings(provider="google", name="offline-model", temperature=0, max_tokens=4000),
        tracing_backend=Tracer(), agent_class=ResponsibilityAgent,
    ))
    assert captured[0][0] == "responsibility"
    assert captured[0][1]["agent_type"] == "responsibility"
    result = json.loads(capsys.readouterr().out)
    assert "components_investigated" in result
    assert result["findings"][0]["validation_status"] == "accepted"
