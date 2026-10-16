"""Offline: uv run pytest src/test-agents/test_modularity.py -q (from agent-server)."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from test_architecture_boundary import (
    NativeStructuredModel,
    ScriptedModel,
    fingerprints,
    toolset,
)

from server.agents.maintainability.modularity.coordinator import ModularityAgent, ModularityConfig
from server.agents.maintainability.modularity.coordinator.agent import route_after_synthesis
from server.agents.maintainability.modularity.coordinator.registry import INVESTIGATORS
from server.agents.maintainability.modularity.coordinator.schemas import (
    Assignment,
    EvidenceGap,
    InvocationRecord,
)
from server.agents.maintainability.modularity.coordinator.synthesis import (
    actionable,
    consolidate,
    detect_contradictions,
)
from server.runtimes.investigation.schemas import Finding, InvestigationConfig
from server.app.tracing_port import NoOpTracingBackend


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "main.py").write_text("def entry():\n    return 1\n", encoding="utf-8")
    return root


def tools(repo, **kwargs):
    return toolset(repo, max_model_calls=96, max_tool_calls=96, **kwargs)


def config(**kwargs):
    return ModularityConfig(invocation_limits=InvestigationConfig(
        max_model_calls=4, max_total_tokens=10_000, max_tool_calls=2), **kwargs)


def result(key, tools, request):
    snapshot = tools.accessible_snapshot
    return INVESTIGATORS[key].result_class(
        repository_id=snapshot.repository.name, commit=snapshot.repository.commit,
        snapshot_hash=snapshot.repository.snapshot_hash, objective=request.objective,
        plan={"objectives": [request.objective], "components": [], "hypotheses": []},
        findings=[], hypotheses=[], missing_information=[], limitations=[], termination_reason="sufficient_evidence",
        model_calls=4, tool_calls=1, iterations=1, accounted_tokens=100, estimated_tokens=100)


def factory(calls, *, fail=None, slow=None):
    def create(key, model, limits):
        async def run(tools, request):
            calls.append((key, id(tools), request.objective))
            tools.execute("get_source_excerpt", {"path": "main.py", "start_line": 1, "end_line": 2}, tool_call_id="read")
            if key == fail:
                raise RuntimeError("secret should not be exposed")
            if key == slow:
                await asyncio.sleep(1)
            return result(key, tools, request)
        return SimpleNamespace(run=run)
    return create


class Trace(NoOpTracingBackend):
    def __init__(self):
        self.records = []

    async def wrap_stage(self, coro, *, name, **metadata):
        self.records.append(metadata)
        return await coro


def test_complete_parallel_empty_results(repo):
    before = fingerprints(repo)
    calls, tracing = [], Trace()
    assessment = asyncio.run(ModularityAgent(NativeStructuredModel([{"summary": "Scoped assessment; no supported issues."}]),
        config(), tracing_backend=tracing, investigator_factory=factory(calls)).run(tools(repo)))
    assert assessment.status == "completed"
    assert len(calls) == 3 and len({c[1] for c in calls}) == 3
    assert {c[0] for c in calls} == set(INVESTIGATORS)
    assert len({r["invocation_id"] for r in tracing.records}) == 3
    assert assessment.rounds_completed == 1
    assert fingerprints(repo) == before


def test_two_round_targeted_followup(repo):
    calls, tracing = [], Trace()
    def resolution(messages):
        context = json.loads(messages[1].content)
        gap = context["gaps"][0]
        invocation = context["invocations"][-1]
        refs = [r for r in context["evidence"] if r.startswith(invocation["invocation_id"] + "/")]
        return {"summary": "Targeted question resolved.", "resolutions": [{"gap_id": gap["id"],
            "invocation_id": invocation["invocation_id"], "evidence_refs": refs,
            "explanation": "Targeted investigator inspected the function body."}]}
    model = NativeStructuredModel([
        {"summary": "Need a targeted check.", "gaps": [{"kind": "missing_evidence", "investigator_id": "responsibility",
            "question": "Does entry mix unrelated behavior?", "targets": ["main.py"]}]}, resolution])
    assessment = asyncio.run(ModularityAgent(model, config(), tracing_backend=tracing,
        investigator_factory=factory(calls)).run(tools(repo)))
    assert assessment.status == "completed"
    assert assessment.rounds_completed == 2
    assert len(calls) == 4 and calls[-1][0] == "responsibility"
    assert len({r["invocation_id"] for r in tracing.records}) == 4
    assert "plan_targeted_follow_up" in assessment.node_transitions
    assert assessment.resolved_gap_ids


@pytest.mark.parametrize("route,rounds,budget,action", [
    ("reinvestigate", 1, True, True), ("finalize_limited", 2, True, True),
    ("finalize_limited", 1, False, True), ("finalize", 1, True, False),
])
def test_router(route, rounds, budget, action):
    gap = EvidenceGap(id="g", kind="missing_evidence", investigator_id="responsibility", question="Inspect body")
    assert route_after_synthesis({"material_gaps": [gap], "rounds_completed": rounds, "max_rounds": 2,
        "budgets": {"can_dispatch": budget}, "actionable_followups": [gap] if action else []}) == route


def test_no_gap_route():
    assert route_after_synthesis({"material_gaps": []}) == "finalize"


def test_failed_investigator_preserves_others(repo):
    calls = []
    assessment = asyncio.run(ModularityAgent(NativeStructuredModel([{"summary": "Dependency investigation failed."}]),
        config(max_rounds=1), investigator_factory=factory(calls, fail="dependency_impact"),
        tracing_backend=NoOpTracingBackend()).run(tools(repo)))
    assert assessment.status == "partial"
    assert [r.status for r in assessment.invocations].count("completed") == 2
    assert assessment.invocations[-1].error == "RuntimeError"
    assert assessment.invocations[-1].consumption.model_calls_estimated
    assert assessment.termination_reason == "round_limit"


def test_duplicate_completed_question():
    assignment = Assignment(invocation_id="i", investigator_id="responsibility", round=1,
        question="Inspect Body", targets=["main.py"])
    record = InvocationRecord(assignment=assignment, status="completed")
    gap = EvidenceGap(id="g", kind="missing_evidence", investigator_id="responsibility",
        question=" inspect   body ", targets=["main.py"])
    assert not actionable(gap, [record])


def test_exhausted_budget_and_bad_synthesis(repo):
    assessment = asyncio.run(ModularityAgent(ScriptedModel([RuntimeError("provider error")]),
        config(max_total_tokens=1000), investigator_factory=factory([]),
        tracing_backend=NoOpTracingBackend()).run(tools(repo)))
    assert assessment.status == "failed"
    assert all(r.status == "skipped" for r in assessment.invocations)
    assert assessment.termination_reason == "resource_limit"


def test_real_investigator_graphs(repo):
    # Real three classes, native ToolNode and repository tools; only provider I/O is simulated.
    def create(key, model, limits):
        evaluation = {"sufficient": True, "hypotheses": [], "candidates": [], "missing_information": []}
        if key == "responsibility":
            evaluation["component_assessments"] = []
        if key == "dependency_impact":
            evaluation["dependency_assessments"] = []
        responses = [{"objectives": ["Inspect entry"], "components": ["main.py"], "hypotheses": []},
            {"unused": True}, {"unused": True}, evaluation, {"findings": [], "limitations": []}]
        from langchain_core.messages import AIMessage
        responses[1] = AIMessage(content="", tool_calls=[{"name": "get_source_excerpt",
            "args": {"path": "main.py", "start_line": 1, "end_line": 2}, "id": "source"}])
        responses[2] = AIMessage(content="Inspected scoped function body; no hypotheses.")
        return INVESTIGATORS[key].agent_class(NativeStructuredModel(responses), limits)
    assessment = asyncio.run(ModularityAgent(NativeStructuredModel([{"summary": "Collected all real investigator graphs."}]),
        ModularityConfig(provider_rate_limits={"requests_per_minute": None, "tokens_per_minute": None},
            invocation_limits=InvestigationConfig(max_model_calls=8, max_total_tokens=60_000)),
        investigator_factory=create, tracing_backend=NoOpTracingBackend()).run(tools(repo)))
    assert len(assessment.invocations) >= 3
    assert all(r.result is not None for r in assessment.invocations[:3])
    assert all(r.evidence for r in assessment.invocations[:3])
    assert assessment.status == "completed"


def test_all_fail_bounded_retry(repo):
    calls = []
    def create(key, model, limits):
        async def run(tools, request):
            calls.append(key)
            raise RuntimeError("failed")
        return SimpleNamespace(run=run)
    assessment = asyncio.run(ModularityAgent(NativeStructuredModel([{"summary": "Failed"}, {"summary": "Still failed"}]),
        config(), investigator_factory=create, tracing_backend=NoOpTracingBackend()).run(tools(repo)))
    assert assessment.status == "failed"
    assert len(calls) == 6
    assert len({r.assignment.invocation_id for r in assessment.invocations}) == 6
    assert assessment.rounds_completed == 2


def test_timeout_keeps_success_and_retrieved_evidence(repo):
    limits = config(max_rounds=1).model_copy(update={"invocation_limits": InvestigationConfig(
        max_model_calls=4, max_total_tokens=10_000, max_tool_calls=2, timeout_seconds=0.02)})
    assessment = asyncio.run(ModularityAgent(NativeStructuredModel([{"summary": "One timeout"}]),
        limits, investigator_factory=factory([], slow="responsibility"),
        tracing_backend=NoOpTracingBackend()).run(tools(repo)))
    assert assessment.status == "partial"
    record = next(r for r in assessment.invocations if r.status == "timeout")
    assert record.evidence and record.consumption.model_calls_estimated
    assert sum(r.status == "completed" for r in assessment.invocations) == 2


def test_cancellation_propagates(repo):
    async def execute():
        started = asyncio.Event()
        def create(key, model, limits):
            async def run(tools, request):
                started.set()
                await asyncio.Event().wait()
            return SimpleNamespace(run=run)
        task = asyncio.create_task(ModularityAgent(NativeStructuredModel([]), config(), investigator_factory=create,
            tracing_backend=NoOpTracingBackend()).run(tools(repo)))
        await started.wait()
        task.cancel()
        await task
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(execute())


def test_completed_equivalent_gap_does_not_loop(repo):
    calls = []
    def repeat(messages):
        context = json.loads(messages[1].content)
        initial = context["invocations"][0]
        return {"summary": "Cannot obtain different evidence", "gaps": [{"kind": "missing_evidence",
            "investigator_id": initial["investigator_id"], "question": calls[0][2], "targets": []}]}
    assessment = asyncio.run(ModularityAgent(NativeStructuredModel([repeat]), config(max_rounds=3),
        investigator_factory=factory(calls), tracing_backend=NoOpTracingBackend()).run(tools(repo)))
    assert len(calls) == 3
    assert assessment.status == "partial"
    assert assessment.termination_reason == "unresolved_no_useful_follow_up"


def finding_record(repo, invocation, status="accepted", title="Boundary concern"):
    tools_instance = tools(repo)
    assignment = Assignment(invocation_id=invocation, investigator_id="architecture_boundary", round=1,
        question="Assess boundary", targets=["main.py"])
    value = result("architecture_boundary", tools_instance, SimpleNamespace(objective="Assess boundary"))
    tools_instance.execute("get_source_excerpt", {"path": "main.py", "start_line": 1, "end_line": 2}, tool_call_id=invocation)
    from server.agents.maintainability.modularity.coordinator.agent import _Execution
    evidence = _Execution.references(tools_instance)
    finding = Finding(id="f1", title=title, description="Scoped concern", criterion_id="c1", kind="design_observation",
        components=["main.py"], evidence_ids=[e.id for e in evidence], justification="Source-backed claim",
        modularity_impact="Independent maintenance risk", severity="medium", confidence=0.8,
        recommendation="Review boundary", criterion={"id": "c1", "description": "Separate concerns",
            "origin": "design_principle", "provenance": "Declared design principle"},
        evidence=evidence, validation_status=status, review_rationale="Checked source")
    return InvocationRecord(assignment=assignment, status="completed", result=value.model_copy(update={"findings": [finding]}),
        evidence=evidence)


def test_consolidation_retains_contributors_and_distinct_evidence(repo):
    records = [finding_record(repo, "one"), finding_record(repo, "two"), finding_record(repo, "three", title="Different concern")]
    findings = consolidate(records, [], [], set())
    assert len(findings) == 2
    merged = next(f for f in findings if len(f.contributions) == 2)
    assert len(merged.evidence) == 2
    assert {c.invocation_id for c in merged.contributions} == {"one", "two"}
    assert merged.confidence is None  # no fabricated combined confidence
    assert merged.id == consolidate(records[:2], [], [], set())[0].id


def test_conflicting_findings_are_disputed(repo):
    records = [finding_record(repo, "one"), finding_record(repo, "two", status="rejected")]
    gaps = detect_contradictions(records, set())
    assert len(gaps) == 1 and gaps[0].kind == "contradiction"
    findings = consolidate(records, [], gaps, set())
    assert findings[0].status == "disputed"
    assert findings[0].severity is None and findings[0].confidence is None


def test_same_bytes_new_retrieval_id_does_not_justify_repeat(repo):
    record = finding_record(repo, "one")
    later = finding_record(repo, "two")
    gap = EvidenceGap(id="g", kind="missing_evidence", investigator_id="architecture_boundary",
        question=record.assignment.question, targets=record.assignment.targets,
        evidence_refs=[f"two/{e.id}" for e in later.evidence])
    assert not actionable(gap, [record, later])


def test_material_contradiction_takes_followup_branch(repo):
    records = [finding_record(repo, "one"), finding_record(repo, "two", status="rejected")]
    gaps = detect_contradictions(records, set())
    assert route_after_synthesis({"material_gaps": gaps, "actionable_followups": gaps,
        "rounds_completed": 1, "max_rounds": 2, "budgets": {"can_dispatch": True}}) == "reinvestigate"


def test_failed_sibling_does_not_erase_supported_findings(repo):
    supported = finding_record(repo, "original").result
    def create(key, model, limits):
        async def run(tools, request):
            if key == "dependency_impact":
                raise RuntimeError("failed")
            if key == "architecture_boundary":
                return supported.model_copy(update={"objective": request.objective})
            return result(key, tools, request)
        return SimpleNamespace(run=run)
    assessment = asyncio.run(ModularityAgent(NativeStructuredModel([{"summary": "One supported concern; incomplete coverage."}]),
        config(max_rounds=1), investigator_factory=create, tracing_backend=NoOpTracingBackend()).run(tools(repo)))
    assert assessment.status == "partial"
    assert len(assessment.consolidated_findings) == 1
    assert assessment.consolidated_findings[0].contributions[0].investigator_id == "architecture_boundary"
    assert assessment.consolidated_findings[0].evidence[0].path == "main.py"


def test_mismatched_snapshot_rejected(repo):
    def create(key, model, limits):
        async def run(tools, request):
            value = result(key, tools, request)
            return value.model_copy(update={"snapshot_hash": "0" * 64}) if key == "responsibility" else value
        return SimpleNamespace(run=run)
    assessment = asyncio.run(ModularityAgent(NativeStructuredModel([{"summary": "Mismatched result rejected."}]),
        config(max_rounds=1), investigator_factory=create, tracing_backend=NoOpTracingBackend()).run(tools(repo)))
    assert assessment.status == "partial"
    assert next(r for r in assessment.invocations if r.assignment.investigator_id == "responsibility").status == "failed"
