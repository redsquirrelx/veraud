"""Real LangGraph/tools over seeded source; only provider responses are simulated.

Optional paid evaluation: REUSE_OPPORTUNITY_LIVE=1, pytest -k live -s.
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
from test_architecture_boundary import NativeStructuredModel, fingerprints, toolset

from server.agents.maintainability.reusability.reuse_opportunity import (
    ReuseOpportunityAgent,
    ReuseOpportunityConfig,
    ReuseOpportunityRequest,
    ReuseOpportunityResult,
)
from server.agents.maintainability.reusability.reuse_opportunity.discovery import (
    discover,
    features,
    source_characteristics,
)
from server.runtimes.repository.tools import ToolLimits

SEED = Path(__file__).parent / "fixtures" / "reuse_opportunity"


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "checkout"
    shutil.copytree(SEED, root)
    return root


def request():
    return ReuseOpportunityRequest(targets=["sales.py", "billing.py"])


def limits(**changes):
    return ReuseOpportunityConfig(**({"max_groups": 1, "max_iterations": 1, "max_total_tokens": 300_000,
        "provider_rate_limits": {"requests_per_minute": None, "tokens_per_minute": None}} | changes))


def plan(group_ids=None):
    def respond(messages):
        context = json.loads(messages[1].content)
        return {"objectives": ["Compare amount aggregation responsibilities and caller constraints"], "components": [],
            "hypotheses": [{"id": "h1", "question": "Can these implementations share amount aggregation?", "criterion_id": "reuse-opportunity",
                "group_ids": group_ids if group_ids is not None else [g["id"] for g in context["candidate_groups"]]}]}
    return respond


def reads(root, paths=None, relationships=True):
    paths = paths if paths is not None else ["sales.py", "billing.py", "orders.py", "invoices.py"]
    calls = [{"name": "get_source_excerpt", "args": {"path": p, "start_line": 1,
        "end_line": len((root / p).read_text(encoding="utf-8").splitlines())}, "id": "read-" + str(i)} for i, p in enumerate(paths)]
    if relationships:
        calls.insert(0, {"name": "list_relationships", "args": {"resolution": "internal", "limit": 50}, "id": "relationships"})
    return AIMessage(content="", tool_calls=calls)


def evaluation(messages, *, classification="recommended", candidate=True, caller=True, mutate=None):
    context = json.loads(messages[1].content)
    group = context["candidate_groups"][0]
    refs = [r for r in context["evidence"] if r["kind"] == "source"]
    profiles = []
    callers = []
    # The model fixture derives real file/evidence IDs from actual tool results.
    # Static import edges are fetched from the ToolMessage result below.
    envelopes = [json.loads(m.content) for m in messages if isinstance(m, ToolMessage) and m.content.startswith("{")]
    edges = [e for envelope in envelopes if envelope.get("tool_name") == "list_relationships" and envelope.get("data")
             for e in envelope["data"].get("items", [])]
    for member in group["members"]:
        profiles.append({"component_id": member["component_id"],
            "evidence_ids": [r["id"] for r in refs if r["file_id"] == member["file_id"]],
            "purpose": "Aggregate amount values and round the total.",
            "inputs_outputs": "Iterable of mappings with amount values; rounded numeric output.",
            "preconditions_postconditions": "Amount values must support addition; output rounded to two decimal places.",
            "failure_behavior": "Missing amount keys and nonnumeric values are not handled locally.",
            "side_effects": "No explicit external I/O or mutation of input in the inspected bodies; custom numeric behavior unknown.",
            "dependencies": "Python numeric addition and round; one uses sum and an intermediate list.",
            "invariants": "One amount contribution per input member before final rounding."})
        caller_path = "orders.py" if member["path"] == "sales.py" else "invoices.py"
        own = [r for r in refs if r["path"] == caller_path]
        edge = next((e for e in edges if own and e["source_id"] == own[0]["file_id"] and e["target_id"] == member["file_id"]), None)
        if caller and own and edge:
            callers.append({"implementation_id": member["component_id"], "caller_id": own[0]["file_id"],
                "relationship_id": edge["id"], "evidence_ids": [r["id"] for r in own],
                "constraints": "Caller forwards its iterable and returns the computed amount unchanged; static import inspected."})
    assessment = {"group_id": group["id"], "hypothesis_id": "h1", "classification": classification,
        "implementations": profiles, "callers": callers,
        "shared_responsibility": "Sum amount fields and round the aggregate.",
        "meaningful_differences": "A list comprehension with sum versus iterative accumulation; memory and numeric edge behavior warrant review.",
        "variation_points": "Iterable source varies; preserve addition order and supported numeric inputs.",
        "proposed_boundary": "Consider a domain-local amount aggregation function, without general-purpose strategy machinery.",
        "expected_benefit": "Qualitatively centralizes the shared rounding rule; no measured savings claimed.",
        "risks_tradeoffs": "Confirm ownership and numeric contracts before sharing; avoid coupling independent business policies.",
        "migration_complexity": "Qualitatively small for these two forwarding callers; no measured effort estimate.",
        "counterevidence_analysis": "Different business policies would justify independence; inspected fixture callers do not introduce policy variation.",
        "rationale": "The inspected implementations and callers support a bounded proposal, not a mandatory refactor.",
        "unknowns": [] if classification != "conditional" else ["Numeric contract and effect compatibility need confirmation."],
        "conditions": ["Preserve the supported numeric inputs, accumulation order and rounding before extracting the common function."] if classification == "conditional" else [],
        "limitations": ["Static seeded evidence; no execution, history or performance measurement."]}
    ids = [i for p in profiles for i in p["evidence_ids"]] + [i for c in callers for i in c["evidence_ids"]]
    finding = {"id": "REUSE-001", "title": "Consider sharing amount aggregation", "description": assessment["shared_responsibility"],
        "criterion_id": "reuse-opportunity", "kind": "design_observation", "components": [m["component_id"] for m in group["members"]],
        "evidence_ids": ids or ["missing-evidence"], "justification": assessment["rationale"],
        "modularity_impact": assessment["expected_benefit"], "severity": "low", "confidence": 0.8,
        "recommendation": assessment["proposed_boundary"], "group_id": group["id"], "classification": classification}
    value = {"sufficient": True, "hypotheses": [{"id": "h1", "question": "Can these implementations share amount aggregation?",
        "criterion_id": "reuse-opportunity", "evidence_ids": ids,
        "status": "discarded" if classification == "not_recommended" else "confirmed", "rationale": assessment["rationale"]}],
        "candidates": [finding] if candidate else [], "group_assessments": [assessment], "missing_information": []}
    if mutate:
        mutate(value)
    return value


def review(*ids, status="accepted"):
    def respond(messages):
        context = json.loads(messages[1].content)
        assessments = context["evaluation"]["group_assessments"]
        return {"findings": [{"finding_id": i, "status": status,
            "rationale": "Compared implementation/caller source and the stated differences, boundary and risks.",
            "severity": "low", "confidence": 0.8} for i in ids], "limitations": [],
            "hypotheses": [{"hypothesis_id": h["id"], "assessment_group_ids": [a["group_id"] for a in assessments if a["hypothesis_id"] == h["id"]],
                "checked_evidence_ids": [r["id"] for r in context["evidence"] if r["kind"] == "source"],
                "scope_supported": True, "resolution": "discarded" if all(a["classification"] == "not_recommended" for a in assessments) else "confirmed",
                "sharing_supported": not all(a["classification"] == "not_recommended" for a in assessments),
                "supporting_group_ids": [a["group_id"] for a in assessments if a["hypothesis_id"] == h["id"] and a["classification"] != "not_recommended"],
                "supported_boundary": "A domain-local amount aggregation function preserving each caller's contract." if any(a["classification"] != "not_recommended" for a in assessments) else "",
                "rationale": "Checked the original scoped question against the implementation comparison.", "unverified_claims": []}
                for h in context["hypotheses"]]}
    return respond


def run(root, responses, config=None, audit_request=None, tools=None):
    tools = tools or toolset(root)
    model = NativeStructuredModel(responses)
    result = asyncio.run(ReuseOpportunityAgent(model, config or limits()).run(tools, audit_request or request()))
    return result, model, tools


def normal(root, **evaluation_options):
    return run(root, [plan(), reads(root), AIMessage(content="Validate"),
        lambda m: evaluation(m, **evaluation_options), review("REUSE-001") if evaluation_options.get("candidate", True) else review()])


def test_different_identifiers_and_syntax_are_discovered(repo):
    snapshot = toolset(repo).accessible_snapshot
    coverage = discover(snapshot, request(), limits())
    assert len(coverage.selected_groups) == 1
    group = coverage.selected_groups[0]
    assert {m.symbol for m in group.members} == {"order_cost", "invoice_value"}
    assert any(s.startswith("shared_terms:") for s in group.discovery_signals)
    assert "identifier_erased_shape" not in group.discovery_signals
    assert coverage == discover(snapshot, request(), limits())


def test_identifier_erasure_finds_renamed_code():
    a, _ = features("def alpha(value):\n return value + 2", "alpha")
    b, _ = features("def beta(other):\n return other + 2", "beta")
    assert a == b


def test_premature_evaluation_is_blocked_then_recovers_after_source_reads(repo):
    result, model, _ = run(repo, [plan(), AIMessage(content="Already know the answer"), reads(repo),
        AIMessage(content="Validate"), evaluation, review("REUSE-001")], config=limits(max_iterations=2))
    assert result.status == "completed" and result.findings[0].validation_status == "accepted"
    assert result.iterations == 2 and len(model.history) == 6
    repair_context = json.loads(model.history[2][1].content)
    assert not repair_context["evaluation"]["group_assessments"]
    assert repair_context["next_source_reads"] and repair_context["missing_information"]


@pytest.mark.parametrize("wrong", [False, True])
def test_index_citations_resolve_only_to_matching_delivered_source(repo, wrong):
    tools = toolset(repo)
    snapshot = tools.accessible_snapshot
    group = discover(snapshot, request(), limits()).selected_groups[0]
    anchors = {m.component_id: next(e.id for e in snapshot.evidence if e.file_id == m.file_id
        and e.start_line is not None and m.start_line <= e.start_line <= m.end_line) for m in group.members}
    def using_anchors(messages):
        value = evaluation(messages, classification="conditional", caller=False)
        assessment = value["group_assessments"][0]
        for profile in assessment["implementations"]:
            profile["evidence_ids"] = [anchors[group.members[0].component_id] if wrong else anchors[profile["component_id"]]]
        ids = [i for p in assessment["implementations"] for i in p["evidence_ids"]]
        value["candidates"][0]["evidence_ids"] = ids
        value["hypotheses"][0]["evidence_ids"] = ids
        return value
    result, _, _ = run(repo, [plan(), reads(repo), AIMessage(content="Validate"), using_anchors, review("REUSE-001")], tools=tools)
    assessment = result.examined_groups[0]
    delivered = {r.id for r in result.evidence}
    assert all(set(p.evidence_ids) <= delivered for p in assessment.implementations)
    assert {i for values in assessment.proposed_evidence_ids.values() for i in values} <= set(anchors.values())
    assert (result.findings[0].validation_status == "accepted") is (not wrong)
    if wrong:
        assert any("implementation_body_not_inspected" in issue for issue in assessment.validation_issues)


def test_unknown_citations_are_preserved_only_as_proposals(repo):
    def corrupt(value):
        value["group_assessments"][0]["implementations"][0]["evidence_ids"] = ["fabricated"]
    result, _, _ = normal(repo, mutate=corrupt)
    assessment = result.examined_groups[0]
    assert assessment.implementations[0].evidence_ids == []
    assert "fabricated" in assessment.proposed_evidence_ids[assessment.implementations[0].component_id]
    assert "unknown_evidence_ids" in assessment.validation_issues
    assert result.findings[0].validation_status == "insufficient_evidence"


@pytest.mark.parametrize("answer", ["confirmed", "discarded"])
def test_rejected_sharing_proposal_cannot_confirm_similarity_as_feasibility(repo, answer):
    def reviewer(messages):
        value = review("REUSE-001", status="rejected")(messages)
        judgment = value["hypotheses"][0]
        judgment["resolution"] = answer
        if answer == "discarded":
            judgment.update(sharing_supported=False, supporting_group_ids=[], supported_boundary="",
                rationale="The proposed sharing boundary is not justified because the return and failure policies differ.")
        return value
    result, _, _ = run(repo, [plan(), reads(repo), AIMessage(content="Validate"),
        lambda m: evaluation(m, classification="conditional"), reviewer])
    assert result.findings[0].validation_status == "rejected"
    if answer == "confirmed":
        assert result.hypotheses[0].status == "inconclusive" and result.status == "partial"
        assert any("confirmed_requires_supported_reviewed_proposal" in issue
                   for issue in result.hypothesis_validation_issues["h1"])
        assert result.critical_review.hypotheses[0].resolution == "confirmed"
    else:
        assert result.hypotheses[0].status == "discarded" and result.status == "completed"
        assert not result.missing_information


@pytest.mark.parametrize("fault", ["similarity_only", "no_boundary", "unknown_group", "discarded_with_accepted_proposal"])
def test_hypothesis_review_requires_a_coherent_answer_to_sharing_question(repo, fault):
    def reviewer(messages):
        value = review("REUSE-001")(messages)
        judgment = value["hypotheses"][0]
        if fault == "similarity_only":
            judgment["sharing_supported"] = None
        elif fault == "no_boundary":
            judgment["supported_boundary"] = ""
        elif fault == "unknown_group":
            judgment["supporting_group_ids"] = ["invented-group"]
        else:
            judgment.update(resolution="discarded", sharing_supported=False, supporting_group_ids=[], supported_boundary="")
        return value
    result, _, _ = run(repo, [plan(), reads(repo), AIMessage(content="Validate"), evaluation, reviewer])
    assert result.hypotheses[0].status == "inconclusive" and result.status == "partial"
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert result.hypothesis_validation_issues["h1"]


def test_one_rejected_proposal_does_not_invalidate_another_supported_boundary(repo):
    (repo / "wholesale.py").write_text((repo / "sales.py").read_text(encoding="utf-8").replace("order_cost", "batch_total"), encoding="utf-8")
    def combined(messages):
        context = json.loads(messages[1].content)
        values = [evaluation([messages[0], HumanMessage(content=json.dumps(context | {"candidate_groups": [group]})), *messages[2:]],
            classification="conditional", caller=False) for group in context["candidate_groups"]]
        value = values[0]
        value["group_assessments"] = [a for v in values for a in v["group_assessments"]]
        value["candidates"] = [{**v["candidates"][0], "id": f"REUSE-{i}"} for i, v in enumerate(values)]
        return value
    def reviewer(messages):
        value = review("REUSE-0", "REUSE-1")(messages)
        value["findings"][1]["status"] = "rejected"
        value["hypotheses"][0]["supporting_group_ids"] = value["hypotheses"][0]["supporting_group_ids"][:1]
        return value
    result, _, _ = run(repo, [plan(), reads(repo, ["sales.py", "billing.py", "wholesale.py"]), AIMessage(content="Validate"),
        combined, reviewer], config=limits(max_groups=2),
        audit_request=ReuseOpportunityRequest(targets=["sales.py", "billing.py", "wholesale.py"]))
    assert result.status == "completed" and result.hypotheses[0].status == "confirmed"
    assert [f.validation_status for f in result.findings] == ["accepted", "rejected"]


def test_conditional_proposal_retains_explicit_unknowns_and_prerequisites_without_callers(repo):
    def overconfident(value):
        value["group_assessments"][0]["unknowns"] = []
        value["group_assessments"][0]["conditions"] = []
    result, model, _ = normal(repo, classification="conditional", caller=False, mutate=overconfident)
    assessment = result.examined_groups[0]
    assert result.status == "completed" and result.findings[0].validation_status == "accepted"
    assert any("Caller compatibility" in item for item in assessment.unknowns)
    assert assessment.qualification_notes
    finding = result.findings[0]
    assert finding.conditions and "Conditional proposal" in finding.recommendation
    assert any("migration effort remain qualitative" in item for item in finding.conditions)
    assert all(condition in finding.recommendation for condition in finding.conditions)
    context = json.loads(model.history[-1][1].content)
    assert context["qualified_group_assessments"][0]["unknowns"] == assessment.unknowns


def test_representation_coverage_reports_indexed_languages_without_exhaustiveness(repo):
    (repo / "sample.ts").write_text("export function typed(value: number): number { return value + 1; }\n", encoding="utf-8")
    (repo / "sample.js").write_text("export function plain(value) { return value + 2; }\n", encoding="utf-8")
    tools = toolset(repo)
    coverage = discover(tools.accessible_snapshot, ReuseOpportunityRequest(), limits())
    assert set(coverage.indexed_languages) == {"python", "typescript", "javascript"}
    assert not coverage.exhaustive
    result, _, _ = normal(repo)
    assert result.coverage.indexed_languages == ["python"]
    assert any("other languages" in item and "outside structural coverage" in item for item in result.limitations)


def test_initial_plan_defers_whole_hypotheses_over_group_budget(repo):
    (repo / "wholesale.py").write_text((repo / "sales.py").read_text(encoding="utf-8").replace("order_cost", "batch_total"), encoding="utf-8")
    def broad_plan(messages):
        value = plan()(messages)
        template = value["hypotheses"][0]
        value["hypotheses"] = [{**template, "id": f"h{i}", "group_ids": [identifier]}
            for i, identifier in enumerate(template["group_ids"])]
        return value
    result, _, _ = run(repo, [broad_plan, AIMessage(content="Need source"), review()],
        config=limits(max_groups=3), audit_request=ReuseOpportunityRequest(targets=["sales.py", "billing.py", "wholesale.py"]))
    assert len(result.plan.hypotheses) == len(result.coverage.planned_groups) == 2
    assert len(result.coverage.unplanned_groups) == 1
    assert any("Deferred hypothesis" in item for item in result.limitations)


def test_substantive_behavior_outranks_protocols_and_trivial_plumbing(repo):
    (repo / "noise.py").write_text(
        "from typing import Protocol\n"
        "class PortOne(Protocol):\n    def execute(self, request: str) -> str: ...\n"
        "class PortTwo(Protocol):\n    def execute(self, request: str) -> str: ...\n"
        "class First:\n    def __init__(self, gateway):\n        self._gateway = gateway\n"
        "class Second:\n    def __init__(self, gateway):\n        self._gateway = gateway\n",
        encoding="utf-8")
    snapshot = toolset(repo).accessible_snapshot
    coverage = discover(snapshot, ReuseOpportunityRequest(targets=["sales.py", "billing.py", "noise.py"]), limits(max_groups=20))
    assert {m.path for m in coverage.selected_groups[0].members} == {"sales.py", "billing.py"}
    assert any("contract_only_navigation" in group.discovery_signals for group in coverage.selected_groups)
    assert any("trivial_plumbing_navigation" in group.discovery_signals for group in coverage.selected_groups)


def test_contract_signatures_cannot_discard_implementation_reuse_hypothesis(repo):
    for path, name in (("sales.py", "First"), ("billing.py", "Second")):
        (repo / path).write_text(f"from typing import Protocol\nclass {name}(Protocol):\n    def execute(self, value: str) -> str: ...\n", encoding="utf-8")
    result, _, _ = normal(repo, classification="not_recommended", caller=False, candidate=False)
    assessment = result.examined_groups[0]
    assert assessment.validation_status == "insufficient_evidence"
    assert any("contract_declaration" in issue for issue in assessment.validation_issues)
    assert all(profile.behavior_basis == "contract_only" and profile.side_effects.startswith("Unknown from contract")
               and profile.failure_behavior.startswith("Unknown from contract") for profile in assessment.implementations)
    assert assessment.unknowns
    assert result.hypotheses[0].status == "inconclusive" and result.status == "partial"


def test_nontrivial_constructor_calls_are_not_labeled_assignment_plumbing(repo):
    (repo / "constructors.py").write_text(
        "class Plain:\n    def __init__(self, gateway):\n        self._gateway = gateway\n"
        "class Computes:\n    def __init__(self, gateway):\n        self._gateway = connect(gateway)\n", encoding="utf-8")
    snapshot = toolset(repo).accessible_snapshot
    files = {f.id: f for f in snapshot.files}
    symbols = {s.id: s for s in snapshot.symbols}
    labels = {s.qualified_name: source_characteristics(s, files[s.file_id], symbols)
              for s in snapshot.symbols if s.name == "__init__"}
    assert labels["Plain.__init__"] == (False, True)
    assert labels["Computes.__init__"] == (False, False)


def test_repeated_unresolved_behavior_stops_with_review_instead_of_more_requests(repo):
    def no_callers(messages):
        return evaluation(messages, caller=False)
    result, _, _ = run(repo, [plan(), reads(repo, ["sales.py", "billing.py"]), AIMessage(content="Validate"),
        no_callers, AIMessage(content="No additional evidence"), no_callers, review("REUSE-001")],
        config=limits(max_iterations=5))
    assert result.termination_reason == "no_investigation_progress" and result.iterations == 2
    assert result.critical_review is not None
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert result.hypotheses[0].status == "inconclusive"


def test_only_committed_subset_creates_coverage_obligations(repo):
    (repo / "wholesale.py").write_text((repo / "sales.py").read_text(encoding="utf-8").replace("order_cost", "batch_total"), encoding="utf-8")
    def scoped_plan(messages):
        group = json.loads(messages[1].content)["candidate_groups"][0]
        return plan([group["id"]])(messages)
    result, model, _ = run(repo, [scoped_plan, reads(repo, ["sales.py", "billing.py", "wholesale.py"]), AIMessage(content="Validate"),
        lambda m: evaluation(m, classification="conditional", caller=False), review("REUSE-001")],
        config=limits(max_groups=3), audit_request=ReuseOpportunityRequest(targets=["sales.py", "billing.py", "wholesale.py"]))
    assert result.status == "completed" and len(result.coverage.planned_groups) == 1
    assert len(result.coverage.unplanned_groups) == 2 and not result.coverage.unassessed_groups
    assert not result.missing_information
    assert json.loads(model.history[1][1].content)["candidate_queue"] == result.coverage.planned_groups


@pytest.mark.parametrize("fault", ["missing_review", "scope", "unchecked", "missing_plan", "unknown_plan"])
def test_discarded_hypotheses_require_bound_behavior_and_independent_review(repo, fault):
    def reviewer(messages):
        value = review()(messages)
        if fault == "missing_review":
            value["hypotheses"] = []
        elif fault == "scope":
            value["hypotheses"][0]["scope_supported"] = False
        elif fault == "unchecked":
            value["hypotheses"][0]["checked_evidence_ids"] = []
        return value
    initial = plan([]) if fault == "missing_plan" else plan(["invented-group"]) if fault == "unknown_plan" else plan()
    result, _, _ = run(repo, [initial, reads(repo), AIMessage(content="Validate"),
        lambda m: evaluation(m, classification="not_recommended", caller=False, candidate=False), reviewer])
    assert result.hypotheses[0].status == "inconclusive"
    assert result.status == "partial" and result.missing_information


def test_direct_e2e_recommended_provenance_routes_and_read_only(repo):
    before = fingerprints(repo)
    result, model, tools = normal(repo)
    assert result.status == "completed", result.model_dump_json(indent=2)
    assert result.quality_attribute == "reusability"
    assert result.findings[0].validation_status == "accepted"
    assert result.findings[0].classification == "recommended"
    assert result.findings[0].stable_id.startswith("REUSE-")
    assert result.execution_trace == ["plan_investigation", "investigate", "route:use_tools", "tools", "investigate",
        "route:validate", "evaluate_evidence", "route:finalize", "review_findings", "finalize"]
    assert result.model_calls == len(model.history) == 5 and result.tool_calls == 5
    assert len(model.bound_tools) == 7
    assert {r.path for r in result.findings[0].evidence} == {"sales.py", "billing.py", "orders.py", "invoices.py"}
    assert all(r.snapshot_hash == tools.context.input.snapshot_hash for r in result.findings[0].evidence)
    assert all(1 <= r.start_line <= r.end_line <= next(f.line_count for f in tools.accessible_snapshot.files if f.id == r.file_id)
               for r in result.findings[0].evidence)
    assert ReuseOpportunityResult.model_validate_json(result.model_dump_json()) == result
    assert fingerprints(repo) == before


def test_missing_caller_routes_back_to_targeted_inspection(repo):
    result, model, _ = run(repo, [plan(), reads(repo, ["sales.py", "billing.py"]), AIMessage(content="Validate"), evaluation,
        reads(repo, ["orders.py", "invoices.py"], relationships=False), AIMessage(content="Validate again"), evaluation, review("REUSE-001")],
        config=limits(max_iterations=2))
    assert result.status == "completed" and result.iterations == 2
    assert "route:inspect" in result.execution_trace
    assert "recommended_requires_inspected_callers" in model.history[4][1].content


def test_unknown_caller_allows_only_explicit_conditional_conclusion(repo):
    result, _, _ = run(repo, [plan(), reads(repo, ["sales.py", "billing.py"]), AIMessage(content="Validate"),
        lambda m: evaluation(m, classification="conditional", caller=False), review("REUSE-001")])
    assert result.status == "completed"
    assert result.findings[0].classification == "conditional" and result.examined_groups[0].unknowns


def test_model_not_recommended_assessment_preserves_domain_tradeoff_without_findings(repo):
    (repo / "sales.py").write_text("def apply_discount(amount):\n    return amount * 0.1\n", encoding="utf-8")
    (repo / "billing.py").write_text("def withhold_tax(amount):\n    return amount * 0.1\n", encoding="utf-8")
    def distinguish(value):
        assessment = value["group_assessments"][0]
        assessment.update(shared_responsibility="Only multiplication is shared; discount and withholding have different domain meanings.",
            meaningful_differences="Discount policy and statutory withholding vary independently.",
            proposed_boundary="Keep policies separate; no sharing proposed.")
        for profile in assessment["implementations"]:
            profile.update(purpose="Domain-specific monetary policy, not general aggregation.",
                inputs_outputs="Amount to policy-specific monetary value.", invariants="Policy rate applies independently.")
    result, _, _ = normal(repo, classification="not_recommended", candidate=False, caller=False, mutate=distinguish)
    assert result.status == "completed" and not result.findings
    assert result.examined_groups[0].classification == "not_recommended"
    assert result.hypotheses[0].status == "discarded"


def test_effect_difference_is_explicit_conditional_tradeoff(repo):
    source = (repo / "billing.py").read_text(encoding="utf-8")
    (repo / "billing.py").write_text(source.replace("    return round(result, 2)",
        "    print(result)\n    return round(result, 2)"), encoding="utf-8")
    group = discover(toolset(repo).accessible_snapshot, request(), limits()).selected_groups[0]
    billing_id = next(m.component_id for m in group.members if m.path == "billing.py")
    def effects(value):
        assessment = value["group_assessments"][0]
        assessment.update(risks_tradeoffs="Keep persistence outside the candidate shared computation if side effects are confirmed.",
            meaningful_differences="Billing prints the intermediate aggregate; sales has no explicit I/O.",
            unknowns=["Whether callers depend on the printed output is unverified."])
        for profile in assessment["implementations"]:
            if profile["component_id"] == billing_id:
                profile["side_effects"] = "Prints the aggregate to stdout before returning."
    result, _, _ = normal(repo, classification="conditional", mutate=effects)
    assert result.findings[0].classification == "conditional"
    assert result.examined_groups[0].unknowns


@pytest.mark.parametrize("fault", ["body", "unknown_id", "same_member", "caller_edge", "unknowns", "classification", "components", "blank_tradeoffs"])
def test_host_rejects_unsupported_positive_claim(repo, fault):
    def corrupt(value):
        a, c = value["group_assessments"][0], value["candidates"][0]
        if fault == "body":
            a["implementations"][0]["evidence_ids"] = []
        elif fault == "unknown_id":
            a["implementations"][0]["evidence_ids"].append("invented-id")
        elif fault == "same_member":
            a["implementations"][1] = a["implementations"][0].copy()
        elif fault == "caller_edge":
            a["callers"][0]["relationship_id"] = "invented-edge"
        elif fault == "unknowns":
            a["unknowns"] = ["Side effects are not understood"]
        elif fault == "classification":
            c["classification"] = "conditional"
        elif fault == "components":
            c["components"] = ["made-up-component"]
        else:
            a["risks_tradeoffs"] = " "
    result, _, _ = normal(repo, mutate=corrupt)
    assert result.status == "partial"
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert result.execution_trace[-1] == "limited_finalize"


def test_iteration_limit_preserves_evidence_and_unsupported_result(repo):
    result, model, _ = run(repo, [plan(), reads(repo, ["sales.py"]), AIMessage(content="Validate"), review()])
    assert result.status == "partial" and result.termination_reason == "iteration_limit"
    assert result.evidence and not result.examined_groups
    assert result.coverage.unassessed_groups
    assert not result.findings and len(model.history) == 4


@pytest.mark.parametrize("config", [{"max_total_tokens": 1000}, {"max_model_calls": 4}, {"max_context_characters": 4000}])
def test_hard_limits_terminate_without_accepting_unsupported_output(repo, config):
    result, _, _ = run(repo, [plan(), reads(repo), AIMessage(content="Validate"), evaluation, review("REUSE-001")], config=limits(**config))
    assert result.status in {"partial", "failed"}
    assert result.execution_trace[-1] == "limited_finalize"
    assert not any(f.validation_status == "accepted" for f in result.findings)
    expected = {"max_total_tokens": "token_limit", "max_tool_calls": "tool_call_limit",
        "max_model_calls": "model_call_limit", "max_context_characters": "context_limit"}
    assert result.termination_reason == expected[next(iter(config))]
    assert result.model_calls <= config.get("max_model_calls", 16)
    assert result.tool_calls <= config.get("max_tool_calls", 24)


def test_tool_failure_is_reported_and_does_not_silently_succeed(repo):
    message = reads(repo)
    message.tool_calls[1]["args"]["path"] = "missing.py"
    result, _, _ = run(repo, [plan(), message, AIMessage(content="Validate"), review()])
    assert result.status == "partial" and result.tool_failures
    assert not result.findings
    assert len(result.tool_failures) == len(result.tool_failure_details) == 1
    failure = result.tool_failure_details[0]
    assert failure.stage == "repository" and failure.provider_call_id == "read-0"
    assert failure.path == "missing.py" and failure.start_line == 1
    assert failure.code == "access_denied" and failure.message


def test_provider_failure_returns_failed_diagnostic(repo):
    result, _, _ = run(repo, [RuntimeError("simulated provider error")])
    assert result.status == "failed" and result.termination_reason == "model_or_schema_error"
    assert result.execution_trace[-1] == "limited_finalize"
    assert any("provider_request" in s for s in result.limitations)


def test_duplicate_findings_preserve_one_accepted_group(repo):
    def duplicate(value):
        value["candidates"].append({**value["candidates"][0], "id": "REUSE-002"})
    result, _, _ = run(repo, [plan(), reads(repo), AIMessage(content="Validate"),
        lambda m: evaluation(m, mutate=duplicate), review("REUSE-001", "REUSE-002")])
    assert sum(f.validation_status == "accepted" for f in result.findings) == 1
    assert result.findings[1].duplicate_of == "REUSE-001"
    assert result.findings[0].stable_id == result.findings[1].stable_id


def test_repeated_query_uses_existing_compact_cache(repo, monkeypatch):
    tools = toolset(repo)
    tools.limits = ToolLimits(compact=True)
    query = tools._query
    queries = []
    def counted(*args, **kwargs):
        queries.append(args[0])
        return query(*args, **kwargs)
    monkeypatch.setattr(tools, "_query", counted)
    result, _, _ = run(repo, [plan(), reads(repo), reads(repo), AIMessage(content="Validate"), evaluation, review("REUSE-001")], tools=tools)
    assert result.status == "completed"
    assert len(queries) == 5 and result.tool_calls == 10
    assert sum(m.cache_hit for m in tools.tool_measurements) == 5


def test_empty_candidate_queue_is_valid_not_a_finding_quota(repo):
    (repo / "sales.py").write_text("def constant():\n    return 7\n", encoding="utf-8")
    result, _, _ = run(repo, [{"objectives": [], "components": [], "hypotheses": []}, AIMessage(content="No comparable indexed pair"),
        {"sufficient": True, "hypotheses": [], "candidates": [], "group_assessments": [], "missing_information": []}, review()],
        audit_request=ReuseOpportunityRequest(targets=["sales.py"]))
    assert result.status == "completed" and not result.findings and result.tool_calls == 0
    assert result.coverage.selected_groups == [] and not result.coverage.exhaustive


def test_discovery_scope_and_bounded_coverage(repo):
    snapshot = toolset(repo).accessible_snapshot
    coverage = discover(snapshot, ReuseOpportunityRequest(), limits(max_discovery_symbols=2))
    assert coverage.shortlisted_symbols == 2 and coverage.omitted_symbols == 2
    for target in ["../outside", "missing.py", "README.md"]:
        with pytest.raises(ValueError):
            discover(snapshot, ReuseOpportunityRequest(targets=[target]), limits())


def test_multiple_cross_module_groups_and_evidence_are_not_duplicated(repo):
    (repo / "wholesale.py").write_text((repo / "sales.py").read_text(encoding="utf-8").replace("order_cost", "batch_total"), encoding="utf-8")
    def combined(messages):
        context = json.loads(messages[1].content)
        values = []
        for group in context["candidate_groups"]:
            scoped = {**context, "candidate_groups": [group]}
            altered = [messages[0], HumanMessage(content=json.dumps(scoped)), *messages[2:]]
            values.append(evaluation(altered, classification="conditional", caller=False))
        value = values[0]
        value["group_assessments"] = [a for v in values for a in v["group_assessments"]]
        value["candidates"] = [{**c, "id": "REUSE-" + str(i)} for i, v in enumerate(values) for c in v["candidates"]]
        return value
    result, _, _ = run(repo, [plan(), reads(repo, ["sales.py", "billing.py", "wholesale.py"]), AIMessage(content="Validate"),
        combined, review("REUSE-0", "REUSE-1", "REUSE-2")], config=limits(max_groups=3, max_planned_groups=3),
        audit_request=ReuseOpportunityRequest(targets=["sales.py", "billing.py", "wholesale.py"]))
    assert result.status == "completed" and len(result.examined_groups) == 3
    assert len({f.stable_id for f in result.findings}) == 3
    assert all(f.validation_status == "accepted" for f in result.findings)
    assert all(len(f.evidence_ids) == len(set(f.evidence_ids)) for f in result.findings)


def test_declaration_only_read_does_not_prove_body(repo):
    message = reads(repo)
    for call in message.tool_calls:
        if call["name"] == "get_source_excerpt" and call["args"]["path"] in {"sales.py", "billing.py"}:
            call["args"]["end_line"] = 1
    result, _, _ = run(repo, [plan(), message, AIMessage(content="Validate"), review()])
    assert not result.findings and not result.examined_groups
    assert any("Read both complete implementation bodies" in i for i in result.missing_information)


def test_caller_body_without_import_anchor_cannot_support_recommendation(repo):
    message = reads(repo)
    for call in message.tool_calls:
        if call["name"] == "get_source_excerpt" and call["args"]["path"] in {"orders.py", "invoices.py"}:
            call["args"]["start_line"] = 4
    result, _, _ = run(repo, [plan(), message, AIMessage(content="Validate"), evaluation, review("REUSE-001")])
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert any("caller_constraints_not_verified" in i for i in result.examined_groups[0].validation_issues)


@pytest.mark.parametrize("dirty", [False, True])
def test_git_revision_provenance(repo, dirty):
    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True)
    git("init")
    git("-c", "core.autocrlf=false", "add", ".")
    git("-c", "user.name=Offline Test", "-c", "user.email=test@example.invalid", "commit", "-m", "seed")
    if dirty:
        with (repo / "sales.py").open("a", encoding="utf-8") as stream:
            stream.write("# uncommitted\n")
    before = fingerprints(repo)
    if dirty:
        result, _, _ = run(repo, [plan(), reads(repo), AIMessage(content="Validate"), review()])
        assert not result.findings and result.termination_reason == "provenance_unverifiable"
    else:
        result, _, _ = normal(repo)
        assert result.findings[0].validation_status == "accepted"
    assert fingerprints(repo) == before


def test_slow_provider_deadline_returns_limited_result(repo):
    class Slow(NativeStructuredModel):
        async def ainvoke(self, messages, **kwargs):
            await asyncio.sleep(1)
            return await super().ainvoke(messages, **kwargs)
    result = asyncio.run(ReuseOpportunityAgent(Slow([plan()]), limits(timeout_seconds=0.05)).run(toolset(repo), request()))
    assert result.status == "failed" and result.termination_reason == "time_limit"
    assert result.execution_trace[-1] == "limited_finalize"


def test_external_cancellation_propagates_without_more_calls_or_writes(repo):
    before = fingerprints(repo)
    class Waiting(NativeStructuredModel):
        async def ainvoke(self, messages, **kwargs):
            entered.set()
            await asyncio.Event().wait()
    async def cancel():
        nonlocal entered
        entered = asyncio.Event()
        task = asyncio.create_task(ReuseOpportunityAgent(Waiting([]), limits()).run(toolset(repo), request()))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    entered = None
    asyncio.run(cancel())
    assert fingerprints(repo) == before


@pytest.mark.parametrize("extension,content", [
    ("js", "export function first(items) { return items.map(item => item.amount); }\n"),
    ("ts", "export function first(items: number[]): number[] { return items.map(item => item + 1); }\n"),
])
def test_javascript_typescript_indexes_supply_real_locations(repo, extension, content):
    (repo / ("one." + extension)).write_text(content, encoding="utf-8")
    (repo / ("two." + extension)).write_text(content.replace("first", "second"), encoding="utf-8")
    tools = toolset(repo)
    coverage = discover(tools.accessible_snapshot,
        ReuseOpportunityRequest(targets=["one." + extension, "two." + extension]), limits())
    assert len(coverage.selected_groups) == 1
    assert {m.symbol for m in coverage.selected_groups[0].members} == {"first", "second"}
    assert all(m.start_line == m.end_line == 1 for m in coverage.selected_groups[0].members)


def test_simulated_harness_preserves_tracing_and_result(repo, capsys):
    from run_architecture_boundary import run_audit

    from server.config.schemas import ModelSettings
    from server.infrastructure.tracing import NoOpTracingBackend

    spans = []
    class Trace(NoOpTracingBackend):
        async def wrap_stage(self, coro, *, name, **metadata):
            spans.append((name, metadata))
            return await coro
    model = NativeStructuredModel([plan(), reads(repo), AIMessage(content="Validate"), evaluation, review("REUSE-001")])
    asyncio.run(run_audit(SimpleNamespace(max_files=100), repo, request(), limits(), model,
        ModelSettings(provider="google", name="simulated-provider", temperature=0, max_tokens=4000),
        tracing_backend=Trace(), agent_class=ReuseOpportunityAgent))
    output = ReuseOpportunityResult.model_validate_json(capsys.readouterr().out)
    assert output.status == "completed" and spans[0][0] == "reuse-opportunity"
    assert spans[0][1]["agent_type"] == "reuse-opportunity"


def test_toolnode_schema_failure_is_observable_even_after_recovery(repo):
    invalid = AIMessage(content="", tool_calls=[{"name": "get_source_excerpt", "args": {"path": "sales.py", "start_line": -1}, "id": "bad-range"}])
    result, _, _ = run(repo, [plan(), invalid, reads(repo), AIMessage(content="Validate"), evaluation, review("REUSE-001")])
    assert result.status == "partial" and result.tool_failures
    assert result.findings[0].validation_status == "accepted"  # recovered evidence is retained
    assert any("bad-range" in f for f in result.tool_failures)
    assert len(result.tool_failure_details) == 1
    failure = result.tool_failure_details[0]
    assert failure.stage == "tool_node" and failure.path == "sales.py" and failure.start_line == -1
    assert failure.message and failure.call_id == "bad-range"


def test_failed_range_receipt_guides_bounded_repair(repo):
    invalid = AIMessage(content="", tool_calls=[{"name": "get_source_excerpt", "args": {
        "path": "sales.py", "start_line": 1, "end_line": 99999}, "id": "oversized"}])
    result, model, tools = run(repo, [plan(), invalid, reads(repo), AIMessage(content="Validate"), evaluation, review("REUSE-001")])
    assert result.findings[0].validation_status == "accepted"
    context = json.loads(model.history[2][1].content)
    assert context["tool_error_feedback"][0]["provider_call_id"] == "oversized"
    assert context["tool_error_feedback"][0]["code"] and context["tool_error_feedback"][0]["message"]
    assert all(read["arguments"]["end_line"] <= next(f.line_count for f in tools.accessible_snapshot.files
        if f.path == read["arguments"]["path"]) for read in context["next_source_reads"])
    assert len(result.tool_failure_details) == len(result.tool_failures) == 1


def test_duplicate_assessment_id_is_not_valid_support(repo):
    def duplicate(value):
        value["group_assessments"].append(value["group_assessments"][0].copy())
    result, _, _ = normal(repo, mutate=duplicate)
    assert result.status == "partial" and result.findings[0].validation_status == "insufficient_evidence"


def test_partial_results_survive_failure_in_later_iteration(repo):
    def gap(value):
        value.update(sufficient=False, missing_information=["Inspect numeric contract tests before final recommendation"])
    result, _, _ = run(repo, [plan(), reads(repo), AIMessage(content="Validate"),
        lambda m: evaluation(m, mutate=gap), RuntimeError("simulated later provider failure")], config=limits(max_iterations=2))
    assert result.status == "partial" and result.examined_groups[0].evidence
    assert result.findings and result.findings[0].validation_status == "insufficient_evidence"
    assert result.termination_reason == "model_or_schema_error"


def test_google_native_adapter_lean_schema_and_usage_with_mocked_transport(repo, monkeypatch):
    from google.genai import types
    from langchain_google_genai import ChatGoogleGenerativeAI

    from server.runtimes.investigation.agent import InvestigationExecution

    tools = toolset(repo)
    config = limits(max_output_tokens=512)
    model = ChatGoogleGenerativeAI(model="gemini-3.5-flash-lite", api_key="offline-test-key", max_tokens=2048, max_retries=0)
    requests, responses = [], []
    review_context = {}
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
            parts = [types.Part.from_function_call(name=c["name"], args=c["args"]) for c in reads(repo).tool_calls]
        else:
            if turn == 1:
                groups = [g.model_dump() for g in discover(tools.accessible_snapshot, request(), config).selected_groups]
                value = plan()([HumanMessage(content=""), HumanMessage(content=json.dumps({"candidate_groups": groups}))])
            elif turn == 3:
                value = "Validate the inspected source"
            elif turn == 4:
                schema = kwargs["config"].response_json_schema
                assert schema["title"] == "ReuseEvaluation" and "maxItems" not in json.dumps(schema)
                context = {"candidate_groups": [g.model_dump() for g in discover(tools.accessible_snapshot, request(), config).selected_groups],
                    "evidence": [r.model_dump() for r in InvestigationExecution.references(SimpleNamespace(tools=tools))]}
                value = evaluation([HumanMessage(content=""), HumanMessage(content=json.dumps(context)),
                    *[ToolMessage(content=r.model_dump_json(), tool_call_id=r.tool_call_id) for r in responses]])
                review_context.update(context | {"evaluation": value, "hypotheses": value["hypotheses"]})
            elif turn == 5:
                value = review("REUSE-001")([HumanMessage(content=""), HumanMessage(content=json.dumps(review_context))])
            else:
                raise AssertionError("Unexpected provider call")
            parts = [types.Part(text=json.dumps(value) if isinstance(value, dict) else value)]
        return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=parts), finish_reason="STOP")],
            usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=100, candidates_token_count=30, total_token_count=130))
    monkeypatch.setattr(model.async_client.models, "generate_content", generate_content)
    result = asyncio.run(ReuseOpportunityAgent(model, config).run(tools, request()))
    assert result.status == "completed" and result.findings[0].validation_status == "accepted"
    assert result.model_calls == len(requests) == 5 and result.accounted_tokens == 650 and result.estimated_tokens == 0
    assert model.max_output_tokens == 2048
    assert all(r["config"].max_output_tokens == 512 for r in requests)


@pytest.mark.skipif(os.getenv("REUSE_OPPORTUNITY_LIVE") != "1", reason="Opt-in paid semantic evaluation")
def test_live_seeded_evaluation(repo, capsys):
    from run_architecture_boundary import load_test_model, run_audit

    from server.runtimes.repository.model_runtime import close_model_clients

    model, settings = load_test_model(os.getenv("REUSE_OPPORTUNITY_AGENT_CONFIG", "dummy"))
    async def live():
        try:
            await run_audit(SimpleNamespace(max_files=100), repo, request(),
                ReuseOpportunityConfig(max_groups=1, max_total_tokens=100_000, max_model_calls=12, timeout_seconds=240),
                model, settings, agent_class=ReuseOpportunityAgent)
        finally:
            await close_model_clients(SimpleNamespace(llm=model))
    asyncio.run(live())
    result = ReuseOpportunityResult.model_validate_json(capsys.readouterr().out)
    print("LIVE provider evaluation (not deterministic semantic proof):", result.model_dump_json(indent=2))
    assert result.status in {"completed", "partial"} and result.plan is not None
    assert result.examined_groups and result.coverage.inspected_paths
    assert any(g.validation_status == "source_backed" for g in result.examined_groups)
