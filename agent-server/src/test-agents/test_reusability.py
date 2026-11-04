"""Real coordinator graph/conditional edges, controlled investigator/model responses.

Includes a small actual-investigator integration. Dedicated default-registry E2Es
and the optional paid smoke live in test_reusability_e2e.py.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest
from test_architecture_boundary import NativeStructuredModel, fingerprints, toolset

from server.agents.maintainability.reusability.coordinator import (
    ReusabilityAgent,
    ReusabilityAssessment,
    ReusabilityConfig,
    ReusabilityRequest,
)
from server.agents.maintainability.reusability.coordinator.agent import (
    ReusabilityExecution,
    route_after_synthesis,
)
from server.agents.maintainability.reusability.coordinator.registry import INVESTIGATORS
from server.agents.maintainability.reusability.coordinator.schemas import Route
from server.infrastructure.tracing import NoOpTracingBackend
from server.runtimes.coordination.execution import CoordinatorExecution
from server.runtimes.investigation.schemas import InvestigationConfig

TARGET = "Offline processing with an injected backend."
FOLLOW_UP = "Inspect whether the backend can be supplied through the public construction boundary."


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "main.py").write_text("def entry():\n    return 1\n", encoding="utf-8")
    return root


def tools(root, **updates):
    return toolset(root, max_model_calls=96, max_tool_calls=96, **updates)


def config(**updates):
    return ReusabilityConfig(**({"provider_rate_limits": {"requests_per_minute": None, "tokens_per_minute": None},
        "invocation_limits": InvestigationConfig(max_model_calls=4, max_total_tokens=10_000, max_tool_calls=2)} | updates))


def request():
    return ReusabilityRequest(targets=["main.py"], target_context=TARGET)


def fake_result(key, child, args, *, finding=True, status="completed"):
    snapshot = child.accessible_snapshot
    refs = CoordinatorExecution.references(child)
    criterion = args.criteria[0]
    value = {"repository_id": snapshot.repository.name, "commit": snapshot.repository.commit,
        "snapshot_hash": snapshot.repository.snapshot_hash, "objective": args.objective,
        "status": status, "plan": {"objectives": [args.objective], "components": [], "hypotheses": []},
        "findings": [], "hypotheses": [], "missing_information": [], "limitations": ["Simulated investigator judgments for orchestration assertions."],
        "termination_reason": "sufficient_evidence", "model_calls": 4, "tool_calls": 1,
        "iterations": 1, "accounted_tokens": 100, "estimated_tokens": 100}
    if key == "component_adaptability":
        value["target_context"] = args.target_context
    if finding:
        f = {"id": "F1", "title": "Scoped " + key + " observation", "description": "Controlled source-linked investigator observation.",
            "criterion_id": criterion.id, "kind": "design_observation", "components": ["main.py"],
            "evidence_ids": [r.id for r in refs], "justification": "Controlled fixture output, not semantic proof.",
            "modularity_impact": "Qualitative reuse consequence.", "severity": "low", "confidence": 0.8,
            "recommendation": "Review conditions before changing the design.", "criterion": criterion,
            "evidence": refs, "validation_status": "accepted", "review_rationale": "Controlled investigator review."}
        if key == "abstraction":
            f.update(category="coupling", assessment_ids=["a1"], basis="usage_evidence")
        elif key == "reuse_opportunity":
            f.update(group_id="g1", classification="recommended")
        else:
            f.update(assessment_ids=["a1"], constraint_type="dependency_injection", classification="verified_obstacle")
        value["findings"] = [f]
    return INVESTIGATORS[key].result_class.model_validate(value)


def factory(calls, *, fail=None, status="completed", mutate=None, delays=None, completed=None, followup_new=True):
    counts = {}
    def create(key, model, limits):
        async def run(child, args):
            counts[key] = counts.get(key, 0) + 1
            # Retain the objects: bare id() values can be reused after a fast
            # completed invocation is collected by Python's allocator.
            calls.append((key, child, args))
            child.execute("get_source_excerpt", {"path": "main.py", "start_line": 1,
                "end_line": 2 if counts[key] > 1 and followup_new else 1}, tool_call_id="source")
            if delays:
                await asyncio.sleep(delays.get(key, 0))
            if key == fail:
                raise RuntimeError("private error details must not appear")
            value = fake_result(key, child, args, status=status)
            if mutate:
                value = mutate(key, value)
            if completed is not None:
                completed.append(key)
            return value
        return SimpleNamespace(run=run)
    return create


class Trace(NoOpTracingBackend):
    def __init__(self):
        self.records = []

    async def wrap_stage(self, coro, *, name, **metadata):
        self.records.append((name, metadata))
        return await coro


def execute(repo, drafts=None, *, cfg=None, make=None, tracing=None):
    return asyncio.run(ReusabilityAgent(NativeStructuredModel(drafts or [{"summary": "Scoped synthesis of collected results."}]),
        cfg or config(), investigator_factory=make or factory([]), tracing_backend=tracing or NoOpTracingBackend()).run(tools(repo), request()))


def proposed_gap():
    return {"kind": "missing_evidence", "investigator_id": "component_adaptability", "question": FOLLOW_UP, "targets": ["main.py"]}


def resolution(messages):
    context = json.loads(messages[1].content)
    invocation = context["invocations"][-1]
    gap = next(g for g in context["gaps"] if g["question"] == FOLLOW_UP)
    refs = [r for r in context["evidence"] if r.startswith(invocation["invocation_id"] + "/")]
    return {"summary": "Follow-up inspected additional source.", "resolutions": [{"gap_id": gap["id"],
        "invocation_id": invocation["invocation_id"], "evidence_refs": refs, "explanation": "Additional function body range inspected."}]}


def test_direct_finalize_exact_topology_provenance_read_only(repo):
    before = fingerprints(repo)
    calls, trace = [], Trace()
    result = execute(repo, make=factory(calls), tracing=trace)
    assert result.status == "completed" and result.quality_attribute == "reusability"
    assert result.rounds_completed == 1 and len(calls) == len(result.invocations) == 3
    assert result.node_transitions == ["plan_assessment", "delegate_investigations", "collect_findings", "synthesize_findings", "finalize_assessment"]
    assert {c[0] for c in calls} == set(INVESTIGATORS) and len({id(c[1]) for c in calls}) == 3
    assert all(c[2].targets == ["main.py"] for c in calls)
    assert calls[-1][2].target_context == TARGET
    assert len({r.assignment.invocation_id for r in result.invocations}) == 3
    assert len({r.assignment.request_id for r in result.invocations}) == 3
    assert len({r.assignment.round_id for r in result.invocations}) == 1
    assert all(a.evidence_expectations and a.priority for a in result.initial_plan)
    assert all(name == "reusability-investigation" and m["request_id"] and m["round_id"] for name, m in trace.records)
    assert len(result.consolidated_findings) == 3 and result.consumption.model_calls == 13
    assert fingerprints(repo) == before
    assert ReusabilityAssessment.model_validate_json(result.model_dump_json()) == result
    # Inspect the actual compiled graph, not just a reported sequence.
    agent = ReusabilityAgent(NativeStructuredModel([]), config(), tracing_backend=NoOpTracingBackend())
    graph = ReusabilityExecution(agent, tools(repo), request()).graph.get_graph()
    assert set(graph.nodes) == {"__start__", "__end__", *result.node_transitions}
    assert {(e.source, e.target) for e in graph.edges if e.conditional} == {
        ("synthesize_findings", "delegate_investigations"), ("synthesize_findings", "finalize_assessment")}


def test_targeted_follow_up_returns_directly_to_delegate_without_initial_batch(repo):
    calls = []
    result = execute(repo, [{"summary": "Need one context check.", "gaps": [proposed_gap()]}, resolution], make=factory(calls))
    assert result.status == "completed" and result.rounds_completed == 2 and len(calls) == 4
    assert calls[-1][0] == "component_adaptability" and calls[-1][2].objective == FOLLOW_UP
    assert [c[0] for c in calls].count("abstraction") == [c[0] for c in calls].count("reuse_opportunity") == 1
    assert result.synthesis_history[0].decision.route == Route.YES and result.synthesis_history[1].decision.route == Route.NO
    assert result.node_transitions == ["plan_assessment", *["delegate_investigations", "collect_findings", "synthesize_findings"] * 2, "finalize_assessment"]
    assert len(result.invocations) == 4 and result.resolved_gap_ids
    assert len({r.assignment.round_id for r in result.invocations}) == 2


def test_partial_failure_retains_successes_and_failure_evidence(repo):
    result = execute(repo, cfg=config(max_rounds=1), make=factory([], fail="reuse_opportunity"))
    assert result.status == "partial" and sum(r.status == "completed" for r in result.invocations) == 2
    failed = next(r for r in result.invocations if r.status == "failed")
    assert failed.error == "RuntimeError" and failed.evidence and failed.consumption.model_calls_estimated
    assert "private error details" not in result.model_dump_json()
    assert result.termination_reason == "round_limit" and result.material_gaps


def test_reported_partial_never_silently_becomes_complete(repo):
    result = execute(repo, cfg=config(max_rounds=1), make=factory([], status="partial"))
    assert result.status == "partial" and all(r.status == "partial" for r in result.invocations)


@pytest.mark.parametrize("cfg,reason", [(config(max_rounds=1), "round_limit"), (config(max_invocations=3), "resource_limit")])
def test_follow_up_with_exhausted_round_or_invocation_budget_uses_no_branch(repo, cfg, reason):
    calls = []
    result = execute(repo, [{"summary": "Need follow-up.", "gaps": [proposed_gap()]}], cfg=cfg, make=factory(calls))
    assert len(calls) == 3 and result.status == "partial" and result.termination_reason == reason
    assert result.continuation_decision.route == Route.NO


def test_total_budget_exhaustion_skips_calls_and_fails_explicitly(repo):
    calls = []
    result = execute(repo, cfg=config(max_total_tokens=1000), make=factory(calls))
    assert not calls and result.status == "failed"
    assert all(r.status == "skipped" for r in result.invocations)


def test_out_of_order_concurrent_returns_do_not_lose_results(repo):
    calls, finished = [], []
    result = execute(repo, make=factory(calls, delays={"abstraction": 0.03, "reuse_opportunity": 0.01}, completed=finished))
    assert finished == ["component_adaptability", "reuse_opportunity", "abstraction"]
    assert result.status == "completed" and {r.assignment.investigator_id for r in result.invocations} == set(INVESTIGATORS)
    assert all(r.result and r.evidence for r in result.invocations)


def test_conclusions_and_relationships_only_reference_collected_sources(repo):
    def draft(messages):
        context = json.loads(messages[1].content)
        refs = list(context["findings"])
        own = context["findings"][refs[0]]["evidence_refs"]
        return {"summary": "Qualified cross-perspective synthesis.", "conclusions": [{"statement": "Controlled observation retained.",
            "finding_refs": [refs[0]], "evidence_refs": own}], "relationships": [{"kind": "tradeoff", "finding_refs": refs[:2],
            "evidence_refs": own, "rationale": "Sharing and coupling need joint consideration, not automatic merging."}]}
    result = execute(repo, [draft])
    assert result.status == "completed" and len(result.conclusions) == len(result.finding_relationships) == 1
    assert len(result.consolidated_findings) == 3
    known = {f"{r.assignment.invocation_id}/{e.id}" for r in result.invocations for e in r.evidence}
    assert set(result.conclusions[0].evidence_refs) <= known


def test_fabricated_synthesis_reference_is_rejected_not_certified(repo):
    result = execute(repo, [{"summary": "Unsupported conclusion", "conclusions": [{"statement": "Invented", "finding_refs": ["unknown/F"],
        "evidence_refs": ["unknown/E"]}]}], cfg=config(max_rounds=1))
    assert result.status == "partial" and not result.conclusions
    assert any(g.kind == "synthesis_failure" for g in result.material_gaps)
    assert len(result.consolidated_findings) == 3


def test_grouping_preserves_equivalent_cross_agent_contributions(repo):
    def draft(messages):
        context = json.loads(messages[1].content)
        refs = [ref for ref, finding in context["findings"].items() if finding["polarity"] == "barrier"]
        return {"summary": "Controlled equivalent obstacle group.", "groups": [{"finding_refs": refs}]}
    result = execute(repo, [draft])
    assert result.status == "completed" and len(result.consolidated_findings) == 2
    group = next(f for f in result.consolidated_findings if len(f.contributions) == 2)
    assert {c.investigator_id for c in group.contributions} == {"abstraction", "component_adaptability"}
    assert group.confidence is None
    assert ReusabilityAssessment.model_validate_json(result.model_dump_json()) == result


def test_incompatible_grouping_is_not_allowed_to_erase_opposing_lenses(repo):
    def draft(messages):
        context = json.loads(messages[1].content)
        return {"summary": "Bad grouping", "groups": [{"finding_refs": list(context["findings"])}]}
    result = execute(repo, [draft], cfg=config(max_rounds=1))
    assert result.status == "partial" and len(result.consolidated_findings) == 3
    assert any(g.kind == "synthesis_failure" for g in result.material_gaps)


def test_unresolved_contradictions_remain_explicit_and_disputed(repo):
    def conflict(messages):
        context = json.loads(messages[1].content)
        refs = list(context["findings"])[:2]
        evidence = context["findings"][refs[0]]["evidence_refs"]
        return {"summary": "Controlled disagreement remains unresolved.", "relationships": [{"kind": "conflicts",
            "finding_refs": refs, "evidence_refs": evidence, "rationale": "Sharing and coupling conclusions require a targeted check."}],
            "gaps": [{"kind": "contradiction", "investigator_id": "abstraction", "question": "Does sharing retain a valid boundary?",
                "targets": ["main.py"], "finding_refs": refs, "evidence_refs": evidence}],
            "conclusions": [{"statement": "One scoped perspective supports the observation, but the disagreement is open.",
                "finding_refs": [refs[0]], "evidence_refs": evidence}]}
    result = execute(repo, [conflict], cfg=config(max_rounds=1))
    assert result.status == "partial" and result.material_gaps[0].kind == "contradiction"
    assert result.finding_relationships[0].resolution_status == "unresolved"
    assert result.conclusions[0].status == "disputed"
    assert any(f.status == "disputed" for f in result.consolidated_findings)


def test_bad_follow_up_target_fails_synthesis_explicitly(repo):
    result = execute(repo, [{"summary": "Invalid path", "gaps": [{**proposed_gap(), "targets": ["../outside"]}]}], cfg=config(max_rounds=1))
    assert result.status == "partial" and any(g.kind == "synthesis_failure" for g in result.material_gaps)


def test_duplicate_completed_question_is_not_redispatched(repo):
    def repeat(messages):
        invocation = json.loads(messages[1].content)["invocations"][0]
        question = request().objective + "\n" + INVESTIGATORS[invocation["investigator_id"]].capability.capability
        return {"summary": "Repeated completed question is not new work.", "gaps": [{"kind": "missing_evidence",
            "investigator_id": invocation["investigator_id"], "question": question, "targets": ["main.py"]}]}
    calls = []
    result = execute(repo, [repeat], make=factory(calls), cfg=config(max_rounds=4))
    assert len(calls) == 3 and result.rounds_completed == 1
    assert result.status == "partial" and result.termination_reason == "no_useful_follow_up"


def test_unspecified_target_remains_null_through_delegation(repo):
    calls = []
    result = asyncio.run(ReusabilityAgent(NativeStructuredModel([{"summary": "No declared destination context."}]), config(),
        investigator_factory=factory(calls), tracing_backend=NoOpTracingBackend()).run(tools(repo), ReusabilityRequest(targets=["main.py"])))
    assert result.target_context is None and calls[-1][2].target_context is None


def test_google_native_synthesis_schema_and_usage_without_paid_calls(repo, monkeypatch):
    from google.genai import types
    from langchain_google_genai import ChatGoogleGenerativeAI

    model = ChatGoogleGenerativeAI(model="gemini-3.5-flash-lite", api_key="offline-test-key", max_tokens=2048, max_retries=0)
    requests = []
    async def generate_content(**kwargs):
        requests.append(kwargs)
        schema = kwargs["config"].response_json_schema
        assert schema["title"] == "SynthesisDraft" and "maxItems" not in json.dumps(schema)
        return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model",
            parts=[types.Part(text=json.dumps({"summary": "Scoped synthesis through mocked Google transport."}))]), finish_reason="STOP")],
            usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=100, candidates_token_count=30, total_token_count=130))
    monkeypatch.setattr(model.async_client.models, "generate_content", generate_content)
    result = asyncio.run(ReusabilityAgent(model, config(max_output_tokens=512), investigator_factory=factory([]),
        tracing_backend=NoOpTracingBackend()).run(tools(repo), request()))
    assert result.status == "completed" and len(requests) == 1
    assert result.consumption.model_calls == 13 and result.consumption.accounted_tokens == 430
    assert result.consumption.estimated_tokens == 300
    assert model.max_output_tokens == 2048 and requests[0]["config"].max_output_tokens == 512


@pytest.mark.parametrize("fault", ["range", "ledger", "usage", "target", "snapshot"])
def test_invalid_investigator_contract_preserves_observations_not_claims(repo, fault):
    def mutate(key, value):
        if key != "component_adaptability":
            return value
        if fault in {"range", "ledger"}:
            finding = value.findings[0]
            ref = finding.evidence[0].model_copy(update={"end_line": 99} if fault == "range" else {"id": "fabricated"})
            f = finding.model_copy(update={"evidence": [ref], "evidence_ids": [ref.id]})
            return value.model_copy(update={"findings": [f]})
        return value.model_copy(update={"model_calls": 999} if fault == "usage" else {"target_context": "invented"} if fault == "target" else {"snapshot_hash": "wrong"})
    result = execute(repo, cfg=config(max_rounds=1), make=factory([], mutate=mutate))
    assert result.status == "partial"
    invalid = result.invocations[-1]
    assert invalid.status == "failed" and invalid.result is None and invalid.evidence
    assert len(result.consolidated_findings) == 2


def test_nonprogress_follow_up_cannot_close_gap_with_new_retrieval_ids(repo):
    result = execute(repo, [{"summary": "Need follow-up.", "gaps": [proposed_gap()]}, resolution],
        cfg=config(max_rounds=3), make=factory([], followup_new=False))
    assert result.status == "partial" and result.rounds_completed == 2
    assert result.termination_reason == "zero_progress" and not result.resolved_gap_ids


def test_essential_failure_retries_are_bounded_without_zero_progress_loop(repo):
    calls = []
    result = execute(repo, [{"summary": "One failure."}, {"summary": "Still failed."}],
        cfg=config(max_rounds=4), make=factory(calls, fail="abstraction", followup_new=False))
    assert result.status == "partial" and len(calls) == 4 and result.rounds_completed == 2


def test_deadline_and_cancellation_preserve_runtime_guards(repo):
    calls = []
    result = execute(repo, cfg=config(max_rounds=1, invocation_limits=InvestigationConfig(
        max_model_calls=4, max_total_tokens=10_000, max_tool_calls=2, timeout_seconds=0.01)),
        make=factory(calls, delays={"abstraction": 1}))
    assert result.status == "partial" and any(r.status == "timeout" and r.evidence for r in result.invocations)
    async def cancel():
        started = asyncio.Event()
        def waiting(*args):
            async def run(*args):
                started.set()
                await asyncio.Event().wait()
            return SimpleNamespace(run=run)
        agent = ReusabilityAgent(NativeStructuredModel([]), config(), investigator_factory=waiting, tracing_backend=NoOpTracingBackend())
        task = asyncio.create_task(agent.run(tools(repo), request()))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(cancel())


def test_router_checks_structured_state_even_if_decision_claims_yes(repo):
    result = execute(repo)
    state = {"continuation_decision": result.continuation_decision.model_copy(update={"route": Route.YES}),
        "material_gaps": [], "pending_assignments": [], "actionable_followups": [], "rounds_completed": 1,
        "max_rounds": 2, "budgets": {"can_dispatch": True}}
    assert route_after_synthesis(state) == Route.NO


def test_real_three_investigator_graphs_models_only_simulated(repo):
    from langchain_core.messages import AIMessage
    from test_abstraction import evaluate as abstraction_evaluate
    from test_abstraction import plan as abstraction_plan
    from test_abstraction import reads as abstraction_reads
    from test_abstraction import review as abstraction_review
    from test_component_adaptability import plan as adaptability_plan
    from test_component_adaptability import review as adaptability_review

    from server.runtimes.investigation.provider import ProviderPacer
    from server.runtimes.investigation.schemas import ProviderRateLimits

    for path, text in {
        "policy.py": "class PricePolicy:\n    def total(self, amounts):\n        return sum(amounts)\n",
        "orders.py": "from policy import PricePolicy\ndef order_total(amounts):\n    return PricePolicy().total(amounts)\n",
        "reports.py": "from policy import PricePolicy\ndef report_total(amounts):\n    return PricePolicy().total(amounts)\n",
    }.items():
        (repo / path).write_text(text, encoding="utf-8")
    before = fingerprints(repo)
    created = []
    def create(key, model, limits):
        if key == "abstraction":
            replies = [abstraction_plan(), abstraction_reads(repo, ["policy.py", "orders.py", "reports.py"]),
                AIMessage(content="Validate"), abstraction_evaluate, abstraction_review("ABS-001")]
        else:
            plan = {"objectives": ["Inspect scoped policy"], "components": [], "hypotheses": []}
            review = {"findings": [], "limitations": []}
            if key == "reuse_opportunity":
                replies = [plan, AIMessage(content="", tool_calls=[{"name": "get_source_excerpt", "args": {"path": "policy.py", "start_line": 1, "end_line": 3}, "id": "read"}]),
                    AIMessage(content="No comparable indexed pair"), {"sufficient": True, "hypotheses": [], "candidates": [],
                    "group_assessments": [], "missing_information": []}, review]
            else:
                def clear(messages):
                    context = json.loads(messages[1].content)
                    return {"sufficient": True, "hypotheses": [{"id": "h1", "question": "Is backend substitution blocked by the public construction path?",
                        "criterion_id": "component-adaptability", "status": "discarded", "rationale": "The inspected scoped policy has no backend dependency."}], "candidates": [], "constraint_assessments": [],
                        "cleared_components": [c["component_id"] for c in context["selected_components"]],
                        "coverage_rationale": "Inspected policy body, no demonstrated backend dependency in this bounded fixture.", "missing_information": []}
                replies = [adaptability_plan(), {"action": "use_tools", "tool_requests": [{"name": "get_source_excerpt",
                    "arguments_json": json.dumps({"path": "policy.py", "start_line": 1, "end_line": 3})}]},
                    {"action": "validate", "tool_requests": []}, clear, adaptability_review()]
        investigator = INVESTIGATORS[key].agent_class(NativeStructuredModel(replies), limits)
        created.append(investigator)
        return investigator
    shared_pacer = ProviderPacer(rate_limits=ProviderRateLimits(requests_per_minute=None, tokens_per_minute=None))
    result = asyncio.run(ReusabilityAgent(NativeStructuredModel([{"summary": "All actual investigator graphs executed over source."}]),
        config(invocation_limits=InvestigationConfig(max_model_calls=8, max_total_tokens=100_000, max_tool_calls=8)),
        investigator_factory=create, tracing_backend=NoOpTracingBackend(), provider_pacer=shared_pacer).run(tools(repo),
            ReusabilityRequest(targets=["policy.py"], target_context=TARGET)))
    print("OFFLINE: actual investigators/tools; model responses simulated:", [(r.assignment.investigator_id, r.status, r.result.model_calls if r.result else 0) for r in result.invocations])
    assert result.status == "completed", result.model_dump_json(indent=2)
    assert len(result.invocations) == 3 and all(r.result and r.evidence for r in result.invocations)
    assert all(r.status == "completed" for r in result.invocations)
    assert all(investigator.provider_pacer is shared_pacer for investigator in created)
    assert len({type(r.result).__name__ for r in result.invocations}) == 3
    assert result.invocations[0].result.findings[0].category == "useful_abstraction"
    assert ReusabilityAssessment.model_validate_json(result.model_dump_json()) == result
    assert fingerprints(repo) == before
