r"""From agent-server: uv run pytest src/test-agents/test_abstraction.py -q.

Offline: real LangGraph, ToolNode, indexes and read-only tools; simulated model.
Live (paid): uv run python src/test-agents/run_abstraction.py C:\repos\project
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

from server.agents.maintainability.reusability.abstraction import (
    AbstractionAgent,
    AbstractionConfig,
    AbstractionRequest,
    AbstractionResult,
)
from server.agents.maintainability.reusability.abstraction.discovery import discover
from server.config.schemas import ModelSettings
from server.infrastructure.tracing import NoOpTracingBackend
from server.runtimes.investigation.agent import InvestigationExecution


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    sources = {
        "policy.py": "class PricePolicy:\n    def total(self, amounts):\n        return sum(amounts)\n",
        "orders.py": "from policy import PricePolicy\ndef order_total(amounts):\n    return PricePolicy().total(amounts)\n",
        "reports.py": "from policy import PricePolicy\ndef report_total(amounts):\n    return PricePolicy().total(amounts)\n",
        "helpers.py": "def normalize(value):\n    return value.strip()\n",
        "wrapper.py": "from helpers import normalize\ndef normalize_value(value):\n    return normalize(value)\n",
        "client.py": "from wrapper import normalize_value\ndef label(value):\n    return normalize_value(value)\n",
        "port.py": "from typing import Protocol\nclass StoragePort(Protocol):\n    def save(self, value): ...\n",
        "adapter.py": "from port import StoragePort\nclass MemoryStorage(StoragePort):\n    def save(self, value):\n        return {'stored': value}\n",
        "checkout.py": "from port import StoragePort\ndef persist(store: StoragePort, value):\n    return store.save(value)\n",
        "duplicate_a.py": "def format_price(amount):\n    return f'{amount:.2f}'\n",
        "duplicate_b.py": "def display_price(amount):\n    return f'{amount:.2f}'\n",
    }
    for path, content in sources.items():
        (root / path).write_text(content, encoding="utf-8")
    return root


def plan(primary="policy.py"):
    return {"objectives": ["Assess reuse tradeoffs"], "components": [], "hypotheses": [{
        "id": "h1", "question": "Does this abstraction justify its indirection?", "criterion_id": "abstraction-reuse",
        "declaration_ids": [primary]}]}


def reads(root, paths, *, graph=True):
    calls = [{"name": "get_source_excerpt", "args": {"path": path, "start_line": 1,
        "end_line": len((root / path).read_text(encoding="utf-8").splitlines())}, "id": f"source-{i}"}
        for i, path in enumerate(paths)]
    if graph:
        calls.insert(0, {"name": "list_relationships", "args": {"resolution": "internal", "limit": 50}, "id": "relationships"})
    return AIMessage(content="", tool_calls=calls)


def evaluate(messages, *, primary="policy.py", category="useful_abstraction", participants=None,
             finding=True, mutate=None):
    context = json.loads(messages[1].content)
    target = next(c for c in context["abstraction_candidates"] if c["path"] == primary)
    envelopes = [json.loads(m.content) for m in messages if isinstance(m, ToolMessage)]
    references = context["evidence"]
    by_path = {r["path"]: r for r in references if r["kind"] == "source"}
    source_ids = [r["id"] for r in references if r["kind"] == "source"]
    edges = [r for e in envelopes if e.get("tool_name") == "list_relationships" and e.get("data")
             for r in e["data"].get("items", []) if r["kind"] != "contains" and r["target_id"]]
    roles = participants if participants is not None else [("orders.py", "consumer"), ("reports.py", "consumer")]
    related = []
    files = {r["path"]: r["file_id"] for r in references}
    # Missing reads remain missing evidence: no synthetic source IDs are manufactured.
    for path, role in roles:
        if path not in files:
            continue
        primary_file = files.get(primary)
        pair = (primary_file, files[path]) if role in {"delegate", "contract"} else (files[path], primary_file)
        edge = next((r for r in edges if (r["source_id"], r["target_id"]) == pair), None)
        related.append({"component_id": files[path], "role": role, "relationship_id": edge["id"] if edge else None,
            "evidence_ids": [by_path[path]["id"]] if path in by_path else [],
            "usage_explanation": "The inspected source uses the declaration through the cited static dependency."})
    assessment = {
        "id": "a1", "hypothesis_id": "h1", "declaration_id": target["component_id"], "conclusion": category,
        "participants": related, "observed_facts": ["The declaration and use sites are present in the inspected source."],
        "supporting_evidence_ids": source_ids, "counterevidence_ids": [],
        "variation_points": "Amount collections vary while the aggregation rule is shared.",
        "reuse_benefit": "Orders and reports reuse the aggregation behavior rather than copying its implementation.",
        "indirection_cost": "The caller crosses a forwarding function with no transformation in the inspected body.",
        "coupling_consequence": "Consumers construct the concrete policy; replacing that construction requires adapting them.",
        "duplication_comparison": "Both inspected formatting functions implement the same numeric formatting behavior.",
        "boundary_justification": "The consumer accepts a StoragePort parameter instead of constructing the one observed implementation.",
        "counterevidence_analysis": "Considered translation, test substitution and intentional contracts; no runtime/history claims are made.",
        "proportional_alternative": "Consider direct use of the helper if no independent contract is intended.",
        "uncertainty": "medium", "limitations": ["Static fixture evidence only; runtime substitution was not exercised."],
    }
    candidate = {
        "id": "ABS-001", "title": "Observed abstraction tradeoff", "description": "Source-backed scoped reuse observation.",
        "criterion_id": "abstraction-reuse", "kind": "design_observation", "components": [target["component_id"]],
        "evidence_ids": source_ids, "justification": "Inspected declaration and actual consumers.",
        "modularity_impact": "Relevant to independent reuse of the observed behavior.",
        "severity": "info" if category == "useful_abstraction" else "medium", "confidence": 0.8,
        "recommendation": "Review the documented tradeoff before changing the design.",
        "category": category if category != "justified_boundary" else "unnecessary_abstraction",
        "assessment_ids": ["a1"], "basis": "usage_evidence",
    }
    value = {"sufficient": True, "hypotheses": [{**{k: v for k, v in plan()["hypotheses"][0].items() if k != "declaration_ids"},
        "status": "discarded" if category == "justified_boundary" else "confirmed", "rationale": "Evaluated against source.",
        "evidence_ids": source_ids}],
        "candidates": [candidate] if finding else [], "missing_information": [], "abstraction_assessments": [assessment]}
    if mutate:
        mutate(value)
    return value


def review(*identifiers, status="accepted"):
    def respond(messages):
        context = json.loads(messages[1].content)
        assessments = context["evaluation"]["abstraction_assessments"]
        return {"findings": [{"finding_id": i, "status": status, "rationale": "Inspected source and tradeoffs support this scoped conclusion.",
                              "severity": "medium", "confidence": 0.8} for i in identifiers], "limitations": [],
            "hypotheses": [{"hypothesis_id": h["id"], "status": "supported", "scope_supported": True,
                "resolution": "discarded" if any(a["conclusion"] == "justified_boundary" for a in assessments
                    if a["hypothesis_id"] == h["id"]) else "confirmed",
                "rationale": "Reviewed the original question against declaration and consumer bodies.",
                "assessment_ids": [a["id"] for a in assessments if a["hypothesis_id"] == h["id"]],
                "checked_evidence_ids": h["evidence_ids"], "unverified_claims": []} for h in context["hypotheses"]]}
    return respond


def run(root, responses, *, target="policy.py", native=True, **updates):
    tools = toolset(root)
    config = AbstractionConfig(**({"max_iterations": 1, "max_total_tokens": 300_000,
        "provider_rate_limits": {"requests_per_minute": None, "tokens_per_minute": None}} | updates))
    model = (NativeStructuredModel if native else ScriptedModel)(responses)
    result = asyncio.run(AbstractionAgent(model, config).run(tools, AbstractionRequest(targets=[target] if target else [])))
    return result, model, tools


def normal(root, *, primary="policy.py", category="useful_abstraction", roles=None, finding=True, mutate=None, **config):
    roles = roles if roles is not None else [("orders.py", "consumer"), ("reports.py", "consumer")]
    return run(root, [plan(primary), reads(root, [primary, *[p for p, _ in roles]]), AIMessage(content="Ready to validate"),
        lambda m: evaluate(m, primary=primary, category=category, participants=roles, finding=finding, mutate=mutate),
        review("ABS-001") if finding else review()], target=primary, **config)


def test_shared_abstraction_graph_and_provenance(repo):
    before = fingerprints(repo)
    result, model, tools = normal(repo)
    assert result.status == "completed" and result.quality_attribute == "reusability"
    assert result.findings[0].validation_status == "accepted" and result.findings[0].category == "useful_abstraction"
    assert result.findings[0].severity == "info"
    assert len(model.history) == result.model_calls == 5
    assert result.tool_calls == 4
    assert len(model.bound_tools) == 7
    assert AbstractionAgent.execution_type._build_graph is InvestigationExecution._build_graph
    assert any(isinstance(m, ToolMessage) for m in model.history[2])
    assert {r.path for r in result.findings[0].evidence if r.kind == "source"} == {"policy.py", "orders.py", "reports.py"}
    assert all(e.snapshot_hash == tools.context.input.snapshot_hash for e in result.findings[0].evidence)
    assert all(e.start_line >= 1 and e.end_line <= next(f.line_count for f in tools.accessible_snapshot.files if f.id == e.file_id)
               for e in result.findings[0].evidence if e.kind == "source")
    assert result.coverage.assessed_declarations and not result.coverage.exhaustive
    assert fingerprints(repo) == before
    assert AbstractionResult.model_validate_json(result.model_dump_json()) == result


def test_pass_through_requires_actual_consumer_and_delegate(repo):
    result, _, _ = normal(repo, primary="wrapper.py", category="unnecessary_abstraction",
        roles=[("client.py", "consumer"), ("helpers.py", "delegate")])
    assert result.status == "completed"
    assert result.findings[0].validation_status == "accepted"


def test_model_justified_boundary_preserves_discarded_hypothesis_without_findings(repo):
    result, _, _ = normal(repo, primary="port.py", category="justified_boundary",
        roles=[("checkout.py", "consumer"), ("adapter.py", "implementation")], finding=False)
    assert result.status == "completed" and not result.findings
    assert result.hypotheses[0].status == "discarded"
    assert result.abstractions_investigated[0].conclusion == "justified_boundary"


def test_missed_reuse_requires_comparison_of_distinct_sources(repo):
    result, _, _ = normal(repo, primary="duplicate_a.py", category="missed_reuse", roles=[("duplicate_b.py", "duplicate")])
    assert result.findings[0].validation_status == "accepted"


def test_coupling_requires_concrete_usage_consequence(repo):
    result, _, _ = normal(repo, category="coupling")
    assert result.findings[0].validation_status == "accepted"


@pytest.mark.parametrize("basis", ["metrics_only", "names_only", "structure_only"])
def test_structural_indicators_are_not_proof(repo, basis):
    result, _, _ = normal(repo, mutate=lambda v: v["candidates"][0].update(basis=basis))
    assert result.status == "partial" and result.findings[0].validation_status == "insufficient_evidence"


@pytest.mark.parametrize("fault", ["declaration", "consumer", "relationship", "anchor", "cost", "unknown_citation", "self_duplicate"])
def test_host_rejects_unverified_abstraction_claims(repo, fault):
    def corrupt(value):
        assessment = value["abstraction_assessments"][0]
        if fault == "declaration":
            assessment["declaration_id"] = "invented-component"
        elif fault == "consumer":
            assessment["participants"] = []
        elif fault == "relationship":
            assessment["participants"][0]["relationship_id"] = "invented-edge"
        elif fault == "anchor":
            assessment["participants"][0]["evidence_ids"] = []
        elif fault == "cost":
            assessment["reuse_benefit"] = ""
        elif fault == "unknown_citation":
            assessment["supporting_evidence_ids"].append("invented-evidence")
        else:
            assessment["participants"][0].update(role="duplicate", component_id=assessment["declaration_id"])
    result, _, _ = normal(repo, mutate=corrupt)
    assert result.status == "partial"
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert result.abstractions_investigated[0].validation_issues
    assert result.inconclusive_investigations
    assert result.hypotheses[0].status == "inconclusive"


@pytest.mark.parametrize("fault", ["missing", "scope", "unrelated", "unchecked", "duplicate"])
def test_hypothesis_requires_bound_independent_review_even_without_findings(repo, fault):
    def reviewer(messages):
        value = review()(messages)
        judgment = value["hypotheses"][0]
        if fault == "missing":
            value["hypotheses"] = []
        elif fault == "scope":
            judgment["scope_supported"] = False
        elif fault == "unrelated":
            judgment["assessment_ids"] = ["another-assessment"]
        elif fault == "unchecked":
            judgment["checked_evidence_ids"] = []
        else:
            value["hypotheses"].append(judgment.copy())
        return value
    result, _, _ = run(repo, [plan(), reads(repo, ["policy.py", "orders.py", "reports.py"]),
        AIMessage(content="Validate"), lambda m: evaluate(m, finding=False), reviewer])
    assert result.abstractions_investigated[0].validation_status == "source_backed"
    assert result.hypotheses[0].status == "inconclusive"
    assert result.status == "partial" and result.critical_review
    assert result.termination_reason == "evidence_validation_failed"


def test_import_hits_do_not_establish_consumer_behavior(repo):
    message = reads(repo, ["policy.py", "orders.py", "reports.py"])
    for call in message.tool_calls:
        if call["name"] == "get_source_excerpt" and call["args"]["path"] != "policy.py":
            call["args"]["end_line"] = 1
    result, _, _ = run(repo, [plan(), message, AIMessage(content="Validate"), evaluate, review("ABS-001")])
    assert result.hypotheses[0].status == "inconclusive"
    assert all("participant_body_not_inspected" in p.validation_issues
               for p in result.abstractions_investigated[0].participants)
    assert result.findings[0].validation_status == "insufficient_evidence"


def test_incomplete_declaration_body_is_not_verified(repo):
    message = reads(repo, ["policy.py", "orders.py", "reports.py"])
    for call in message.tool_calls:
        if call["name"] == "get_source_excerpt" and call["args"]["path"] == "policy.py":
            call["args"]["end_line"] = 2
    result, _, _ = run(repo, [plan(), message, AIMessage(content="Validate"), evaluate, review("ABS-001")])
    assert "abstraction_body_not_inspected" in result.abstractions_investigated[0].validation_issues
    assert result.hypotheses[0].status == "inconclusive"


def test_repeated_invalid_usage_closes_without_more_exploration(repo):
    def invalid(messages):
        return evaluate(messages, mutate=lambda v: v["abstraction_assessments"][0]["participants"][0].update(
            relationship_id="relationship:invented-from-retrieval"))
    result, _, _ = run(repo, [plan(), reads(repo, ["policy.py", "orders.py", "reports.py"]),
        AIMessage(content="Validate"), invalid, AIMessage(content="No more source"), invalid,
        review("ABS-001")], max_iterations=5)
    assert result.termination_reason == "no_investigation_progress"
    assert result.iterations == 2 and result.critical_review is not None
    assert result.hypotheses[0].status == "inconclusive"


def test_token_reservation_preserves_evaluation_and_review(repo, monkeypatch):
    execution = AbstractionAgent.execution_type
    original = execution.closing_token_reserve
    def consumed(self, node, reserve):
        if node == "investigate" and self.calls == 2:
            self.tokens = self.token_limit - int(2.9 * reserve)
        return original(self, node, reserve)
    monkeypatch.setattr(execution, "closing_token_reserve", consumed)
    result, _, _ = run(repo, [plan(), reads(repo, ["policy.py", "orders.py", "reports.py"]),
        evaluate, review("ABS-001")])
    assert result.termination_reason == "token_limit"
    assert result.abstractions_investigated and result.critical_review
    assert result.accounted_tokens <= 300_000
    assert result.findings[0].validation_status == "accepted"


def test_navigation_supplies_real_edges_and_unread_consumers(repo):
    tools = toolset(repo)
    execution = AbstractionAgent.execution_type(ScriptedModel([]), AbstractionConfig(), tools,
        AbstractionRequest(targets=["policy.py"]))
    context = execution.model_context("investigate", execution.initial_state())
    edge = next(r for r in context["abstraction_navigation"] if r["source_path"] == "orders.py")
    assert edge["target_path"] == "policy.py" and edge["navigation_only"]
    assert edge["relationship_id"] in execution.relationships
    assert any(r["arguments"]["path"] == "orders.py" for r in context["next_source_reads"])
    assert not execution.references()


def test_missing_critical_review_cannot_leave_confirmed_hypothesis(repo):
    result, _, _ = run(repo, [plan(), reads(repo, ["policy.py", "orders.py", "reports.py"]),
        AIMessage(content="Validate"), evaluate, RuntimeError("Review unavailable")])
    assert result.abstractions_investigated[0].validation_status == "source_backed"
    assert result.critical_review is None
    assert result.hypotheses[0].status == "inconclusive"
    assert result.findings[0].validation_status == "insufficient_evidence"


def test_compaction_preserves_assessment_citations_and_original_history(repo):
    from server.agents.maintainability.reusability.abstraction.schemas import (
        AbstractionEvaluation,
    )

    tools = toolset(repo)
    execution = AbstractionAgent.execution_type(ScriptedModel([]), AbstractionConfig(), tools,
        AbstractionRequest(targets=["policy.py"]))
    state = execution.initial_state()
    payload = lambda identifier: json.dumps({"evidence": [{"id": identifier, "kind": "source"}], "data": "x" * 20_000})
    state["messages"] = [ToolMessage(content=payload(i), tool_call_id=i, name="get_source_excerpt")
                         for i in ("old", "pinned", "recent1", "recent2")]
    declaration = execution.selected[0].component_id
    state["evaluation"] = AbstractionEvaluation(sufficient=False, hypotheses=[], candidates=[], missing_information=[],
        abstraction_assessments=[{"id": "a1", "hypothesis_id": "h1", "declaration_id": declaration,
            "conclusion": "inconclusive", "observed_facts": ["Partial observation"],
            "supporting_evidence_ids": ["pinned"], "counterevidence_analysis": "Not resolved", "uncertainty": "high"}])
    before = [m.model_dump() for m in state["messages"]]
    compacted = execution.provider_history(state, [], overhead_characters=100_000, node="review_findings")
    assert json.loads(compacted[0].content)["history_compacted"]
    assert compacted[1].content == state["messages"][1].content
    assert [m.model_dump() for m in state["messages"]] == before


def test_unrelated_assessment_does_not_contaminate_valid_scoped_conclusion(repo):
    def mixed(messages):
        value = evaluate(messages)
        unrelated = evaluate(messages, primary="wrapper.py",
            participants=[("client.py", "consumer")], finding=False)["abstraction_assessments"][0]
        unrelated["id"] = "unrelated"
        unrelated["participants"][0]["relationship_id"] = "unverified-edge"
        value["abstraction_assessments"].append(unrelated)
        return value
    def scoped_review(messages):
        value = review("ABS-001")(messages)
        value["hypotheses"][0]["assessment_ids"] = ["a1"]
        return value
    result, _, _ = run(repo, [plan(), reads(repo, ["policy.py", "orders.py", "reports.py", "wrapper.py", "client.py"]),
        AIMessage(content="Validate"), mixed, scoped_review], target=None, max_candidates=40)
    assert result.hypotheses[0].status == "confirmed"
    assert result.findings[0].validation_status == "accepted"
    outside = next(a for a in result.abstractions_investigated if a.id == "unrelated")
    assert "declaration_outside_hypothesis_scope" in outside.validation_issues
    assert outside.conclusion == "inconclusive"
    assert result.coverage.planned_declarations == result.coverage.assessed_declarations
    assert result.coverage.unplanned_candidates and not result.coverage.unassessed_candidates
    assert not result.missing_information and result.status == "completed"
    assert result.plan.hypotheses[0].declaration_ids == result.coverage.planned_declarations


def test_review_recomputes_repaired_host_downgrade_and_retains_history(repo):
    def broken(messages):
        return evaluate(messages, mutate=lambda v: v["abstraction_assessments"][0]["participants"][0].update(
            relationship_id="missing-edge"))
    def repaired_but_uncertain(messages):
        return evaluate(messages, mutate=lambda v: v["hypotheses"][0].update(status="inconclusive"))
    result, _, _ = run(repo, [plan(), reads(repo, ["policy.py", "orders.py", "reports.py"]),
        AIMessage(content="Validate"), broken, AIMessage(content="Correct relation using already delivered IDs"),
        repaired_but_uncertain, review("ABS-001")], max_iterations=2)
    assert result.hypotheses[0].status == "confirmed"
    assert result.findings[0].validation_status == "accepted"
    assert not result.missing_information
    assert result.termination_reason == "iteration_limit" and result.status == "partial"
    first, second = result.hypothesis_validation_history
    assert first.proposed.status == "confirmed" and first.validated.status == "inconclusive"
    assert second.proposed.status == second.validated.status == "inconclusive"
    assert result.critical_review.hypotheses[0].resolution == "confirmed"


def test_review_cannot_ignore_an_uninspected_committed_declaration(repo):
    initial = plan()
    initial["hypotheses"][0]["declaration_ids"].append("wrapper.py")
    result, _, _ = run(repo, [initial, reads(repo, ["policy.py", "orders.py", "reports.py"]),
        AIMessage(content="Validate"), evaluate, review("ABS-001")], target=None, max_candidates=40)
    assert result.abstractions_investigated[0].validation_status == "source_backed"
    assert result.hypotheses[0].status == "inconclusive"
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert result.coverage.unassessed_candidates
    assert any("planned abstraction" in gap for gap in result.missing_information)


@pytest.mark.parametrize("declarations", [[], ["invented-id"]])
def test_missing_plan_binding_cannot_be_filled_by_later_assessment_claim(repo, declarations):
    initial = plan()
    initial["hypotheses"][0]["declaration_ids"] = declarations
    result, _, _ = run(repo, [initial, reads(repo, ["policy.py", "orders.py", "reports.py"]),
        AIMessage(content="Validate"), evaluate, review("ABS-001")])
    assert result.hypotheses[0].status == "inconclusive"
    assert result.status == "partial"
    assert any("planned declaration identities" in gap for gap in result.missing_information)


def test_evaluation_cannot_replace_original_question_to_fit_another_scope(repo):
    initial = plan()
    initial["hypotheses"][0]["question"] = "Does PricePolicy justify aggregation reuse?"
    result, _, _ = run(repo, [initial, reads(repo, ["policy.py", "orders.py", "reports.py"]),
        AIMessage(content="Validate"), lambda m: evaluate(m, mutate=lambda v:
            v["hypotheses"][0].update(question="Is a UI Button useful?")), review("ABS-001")])
    assert result.hypotheses[0].question == initial["hypotheses"][0]["question"]
    assert result.hypothesis_validation_history[0].proposed.question == "Is a UI Button useful?"


def test_host_gap_drives_another_inspection(repo):
    roles = [("orders.py", "consumer")]
    result, model, _ = run(repo, [plan(), reads(repo, ["policy.py"]), AIMessage(content="Validate"),
        lambda m: evaluate(m, participants=roles), reads(repo, ["orders.py"], graph=False), AIMessage(content="Revalidate"),
        lambda m: evaluate(m, participants=roles), review("ABS-001")], max_iterations=2)
    assert result.status == "completed" and result.iterations == 2
    assert result.findings[0].validation_status == "accepted"
    assert any("actual_consumer_required" in gap for gap in json.loads(model.history[4][1].content)["missing_information"])


# Zero-tool admission is covered by test_zero_tool_allowance_and_provider_failure
# in test_architecture_boundary.py, using valid evaluation/review responses.
@pytest.mark.parametrize("limit", ["tokens", "context", "models"])
def test_execution_limits_are_explicit(repo, limit):
    config = {"max_total_tokens": 1000} if limit == "tokens" else {
        "max_context_characters": 4000} if limit == "context" else {"max_model_calls": 4}
    result, _, _ = normal(repo, **config)
    assert result.status in {"partial", "failed"}
    assert not any(f.validation_status == "accepted" for f in result.findings)
    assert result.termination_reason == {
        "tokens": "token_limit",
        "context": "context_limit", "models": "model_call_limit",
    }[limit]
    assert result.model_calls <= config.get("max_model_calls", 16)
    assert result.tool_calls <= config.get("max_tool_calls", 24)


def test_tool_failure_does_not_fabricate_source(repo):
    def failed_read(messages):
        message = reads(repo, ["policy.py", "orders.py"])
        message.tool_calls[1]["args"]["path"] = "missing.py"
        return message
    result, model, _ = run(repo, [plan(), failed_read, AIMessage(content="Validate"),
        lambda m: evaluate(m, participants=[("orders.py", "consumer")]), review("ABS-001")])
    assert result.status == "partial"
    assert result.tool_failures
    assert not any(f.validation_status == "accepted" for f in result.findings)
    assert any(json.loads(m.content)["status"] == "error" for messages in model.history for m in messages if isinstance(m, ToolMessage))


def test_review_can_reject_valid_source_supported_conclusion(repo):
    result, _, _ = run(repo, [plan(), reads(repo, ["policy.py", "orders.py", "reports.py"]), AIMessage(content="Validate"),
        evaluate, review("ABS-001", status="rejected")])
    assert result.findings[0].validation_status == "rejected"


def test_no_actionable_gap_finalizes_without_unconditional_loop(repo):
    result, model, _ = normal(repo, mutate=lambda value: value.update(sufficient=False), max_iterations=3)
    assert result.status == "partial" and result.termination_reason == "no_actionable_gap"
    assert result.iterations == 1 and len(model.history) == 5


def test_single_implementation_without_cost_evidence_cannot_establish_harm(repo):
    def counts_only(value):
        assessment = value["abstraction_assessments"][0]
        assessment.update(indirection_cost="", proportional_alternative="")
    result, _, _ = normal(repo, primary="port.py", category="unnecessary_abstraction",
        roles=[("checkout.py", "consumer"), ("adapter.py", "implementation")], mutate=counts_only)
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert "concrete_indirection_cost_and_alternative_required" in result.abstractions_investigated[0].validation_issues


def test_design_principle_cannot_be_reported_as_normative_violation(repo):
    result, _, _ = normal(repo, primary="wrapper.py", category="unnecessary_abstraction",
        roles=[("client.py", "consumer"), ("helpers.py", "delegate")],
        mutate=lambda value: value["candidates"][0].update(kind="violation"))
    assert result.findings[0].validation_status == "insufficient_evidence"


def test_duplicate_concerns_preserve_history_and_single_accepted_finding(repo):
    def duplicate(value):
        value["candidates"].append({**value["candidates"][0], "id": "ABS-002"})
    result, _, _ = run(repo, [plan(), reads(repo, ["policy.py", "orders.py", "reports.py"]), AIMessage(content="Validate"),
        lambda m: evaluate(m, mutate=duplicate), review("ABS-001", "ABS-002")])
    assert len(result.findings) == 2
    assert sum(f.validation_status == "accepted" for f in result.findings) == 1
    assert result.findings[1].duplicate_of == "ABS-001"


def test_discovery_is_deterministic_bounded_and_scope_checked(repo):
    snapshot = toolset(repo).accessible_snapshot
    selected, count = discover(snapshot, AbstractionRequest(), 2)
    assert len(selected) == 2 and count > 2
    assert discover(snapshot, AbstractionRequest(), 2) == (selected, count)
    assert len(discover(snapshot, AbstractionRequest(targets=["port.py"]), 12)[0]) == 1
    with pytest.raises(ValueError):
        discover(snapshot, AbstractionRequest(targets=["../outside"]), 12)
    with pytest.raises(ValueError):
        discover(snapshot, AbstractionRequest(targets=["README.md"]), 12)


@pytest.mark.parametrize("dirty", [False, True])
def test_commit_provenance_is_checked(repo, dirty):
    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    git("init")
    git("-c", "core.autocrlf=false", "add", ".")
    git("-c", "user.name=Offline Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture")
    if dirty:
        with (repo / "policy.py").open("a", encoding="utf-8") as stream:
            stream.write("# uncommitted change\n")
    before = fingerprints(repo)
    result, _, _ = normal(repo)
    assert (result.findings[0].validation_status == "accepted") is (not dirty)
    assert fingerprints(repo) == before


def test_live_harness_reuses_configuration_and_tracing(repo, capsys):
    spec = importlib.util.spec_from_file_location("abstraction_harness", Path(__file__).with_name("run_architecture_boundary.py"))
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    spans = []
    class Trace(NoOpTracingBackend):
        async def wrap_stage(self, coro, *, name, **metadata):
            spans.append((name, metadata))
            return await coro
    model = NativeStructuredModel([plan(), reads(repo, ["policy.py", "orders.py", "reports.py"]),
        AIMessage(content="Validate"), evaluate, review("ABS-001")])
    asyncio.run(harness.run_audit(SimpleNamespace(max_files=100), repo, AbstractionRequest(targets=["policy.py"]),
        AbstractionConfig(max_total_tokens=300_000), model,
        ModelSettings(provider="google", name="offline-model", temperature=0, max_tokens=4000),
        tracing_backend=Trace(), agent_class=AbstractionAgent))
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "completed"
    assert spans[0][0] == "abstraction" and spans[0][1]["agent_type"] == "abstraction"


def test_integration_useful_pass_through_and_justified_interface_in_one_audit(repo):
    before = fingerprints(repo)
    hypotheses = [{**plan(primary)["hypotheses"][0], "id": "h" + str(i)}
                  for i, primary in enumerate(("policy.py", "wrapper.py", "port.py"), 1)]
    def combined(messages):
        cases = [
            ("policy.py", "useful_abstraction", [("orders.py", "consumer"), ("reports.py", "consumer")], True),
            ("wrapper.py", "unnecessary_abstraction", [("client.py", "consumer"), ("helpers.py", "delegate")], True),
            ("port.py", "justified_boundary", [("checkout.py", "consumer"), ("adapter.py", "implementation")], False),
        ]
        value = {"sufficient": True, "hypotheses": [], "candidates": [], "missing_information": [], "abstraction_assessments": []}
        for index, (primary, category, roles, finding) in enumerate(cases, 1):
            part = evaluate(messages, primary=primary, category=category, participants=roles, finding=finding)
            part["hypotheses"][0]["id"] = "h" + str(index)
            assessment = part["abstraction_assessments"][0]
            assessment.update(id="a" + str(index), hypothesis_id="h" + str(index))
            for candidate in part["candidates"]:
                candidate.update(id="ABS-00" + str(index), assessment_ids=["a" + str(index)])
            for key in ("hypotheses", "candidates", "abstraction_assessments"):
                value[key].extend(part[key])
        return value
    paths = ["policy.py", "orders.py", "reports.py", "wrapper.py", "client.py", "helpers.py", "port.py", "checkout.py", "adapter.py"]
    model = NativeStructuredModel([{**plan(), "hypotheses": hypotheses}, reads(repo, paths),
        AIMessage(content="Validate all three selected candidates"), combined, review("ABS-001", "ABS-002")])
    result = asyncio.run(AbstractionAgent(model, AbstractionConfig(max_total_tokens=300_000, max_candidates=3)).run(
        toolset(repo), AbstractionRequest(targets=["policy.py", "wrapper.py", "port.py"])))
    assert result.status == "completed"
    assert {f.category for f in result.findings if f.validation_status == "accepted"} == {"useful_abstraction", "unnecessary_abstraction"}
    assert len(result.abstractions_investigated) == len(result.coverage.assessed_declarations) == 3
    assert result.hypotheses[-1].status == "discarded"
    assert fingerprints(repo) == before


def test_source_ranges_must_cover_usage_declarations(repo):
    message = reads(repo, ["policy.py", "orders.py", "reports.py"])
    for call in message.tool_calls:
        if call["name"] == "get_source_excerpt" and call["args"]["path"] != "policy.py":
            call["args"]["start_line"] = 2  # reads the consumer body but omits the import anchor
    result, _, _ = run(repo, [plan(), message, AIMessage(content="Validate"), evaluate, review("ABS-001")])
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert any("usage_declaration_not_inspected" in p.validation_issues for p in result.abstractions_investigated[0].participants)


def test_metadata_and_counts_without_source_are_insufficient(repo):
    message = AIMessage(content="", tool_calls=[{"name": "list_relationships", "args": {"resolution": "internal", "limit": 50}, "id": "graph"}])
    def metadata_claim(messages):
        value = evaluate(messages)
        ids = [r["id"] for r in json.loads(messages[1].content)["evidence"]][:6]
        value["candidates"][0]["evidence_ids"] = ids
        value["abstraction_assessments"][0]["supporting_evidence_ids"] = ids
        return value
    result, _, _ = run(repo, [plan(), message, AIMessage(content="Validate"), metadata_claim, review("ABS-001")])
    assert result.status == "partial"
    assert result.findings[0].validation_status == "insufficient_evidence"


def test_duplicate_assessment_ids_cannot_support_acceptance(repo):
    def duplicate(value):
        value["abstraction_assessments"].append(value["abstraction_assessments"][0].copy())
    result, _, _ = normal(repo, mutate=duplicate)
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert all("duplicate_assessment_id" in a.validation_issues for a in result.abstractions_investigated)


def test_provider_failure_returns_failed_and_retains_diagnostic(repo):
    result, _, _ = run(repo, [RuntimeError("simulated provider failure")])
    assert result.status == "failed" and result.termination_reason == "model_or_schema_error"
    assert not result.findings
    assert any("provider_request" in s for s in result.limitations)


def test_google_adapter_native_schemas_tools_and_usage_with_mocked_transport(repo, monkeypatch):
    from google.genai import types
    from langchain_core.messages import HumanMessage
    from langchain_google_genai import ChatGoogleGenerativeAI

    tools = toolset(repo)
    request = AbstractionRequest(targets=["policy.py"])
    config = AbstractionConfig(max_output_tokens=512, max_total_tokens=300_000)
    model = ChatGoogleGenerativeAI(model="gemini-3.5-flash-lite", api_key="offline-test-key",
        max_tokens=2048, max_retries=0)
    requests, responses = [], []
    execute = tools.execute
    def observe(*args, **kwargs):
        response = execute(*args, **kwargs)
        responses.append(response)
        return response
    monkeypatch.setattr(tools, "execute", observe)
    async def generate_content(**kwargs):
        requests.append(kwargs)
        turn = len(requests)
        if turn == 2:
            parts = [types.Part.from_function_call(name=c["name"], args=c["args"])
                     for c in reads(repo, ["policy.py", "orders.py", "reports.py"]).tool_calls]
        else:
            if turn == 1:
                value = plan()
            elif turn == 3:
                value = "Ready to validate"
            elif turn == 4:
                schema = kwargs["config"].response_json_schema
                assert schema["title"] == "AbstractionEvaluation" and "maxItems" not in json.dumps(schema)
                selected, _ = discover(tools.accessible_snapshot, request, config.max_candidates)
                context = {"abstraction_candidates": [c.model_dump() for c in selected],
                    "evidence": [r.model_dump() for r in InvestigationExecution.references(SimpleNamespace(tools=tools))]}
                value = evaluate([HumanMessage(content=""), HumanMessage(content=json.dumps(context)),
                    *[ToolMessage(content=r.model_dump_json(), tool_call_id=r.tool_call_id) for r in responses]])
            elif turn == 5:
                source_ids = [r.id for r in InvestigationExecution.references(SimpleNamespace(tools=tools)) if r.kind == "source"]
                value = {"findings": [{"finding_id": "ABS-001", "status": "accepted", "rationale": "Reviewed scoped source.",
                    "severity": "info", "confidence": 0.8}], "limitations": [], "hypotheses": [{
                    "hypothesis_id": "h1", "status": "supported", "scope_supported": True, "resolution": "confirmed",
                    "rationale": "Reviewed declaration and actual consumers.", "assessment_ids": ["a1"],
                    "checked_evidence_ids": source_ids, "unverified_claims": []}]}
            else:
                raise AssertionError("Unexpected provider call")
            parts = [types.Part(text=json.dumps(value) if isinstance(value, dict) else value)]
        return types.GenerateContentResponse(candidates=[types.Candidate(
            content=types.Content(role="model", parts=parts), finish_reason="STOP")],
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=100, candidates_token_count=30, total_token_count=130))
    monkeypatch.setattr(model.async_client.models, "generate_content", generate_content)
    result = asyncio.run(AbstractionAgent(model, config).run(tools, request))
    assert result.status == "completed" and result.findings[0].validation_status == "accepted"
    assert result.model_calls == len(requests) == 5
    assert result.accounted_tokens == 650 and result.estimated_tokens == 0
    assert model.max_output_tokens == 2048
    assert all(r["config"].max_output_tokens == 512 for r in requests)
