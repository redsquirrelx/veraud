"""Real manager graph with controlled subordinate assessments and exact routing.

Run from agent-server: uv run pytest src/test-agents/test_maintainability_manager.py -v -s
"""

import asyncio
import json
import subprocess
from types import SimpleNamespace

import pytest
from test_architecture_boundary import NativeStructuredModel, fingerprints, toolset
from test_modularity import factory as modularity_factory
from test_reusability import factory as reusability_factory

from server.agents.maintainability.manager import (
    MaintainabilityConfig,
    MaintainabilityManagerAgent,
    MaintainabilityReport,
    MaintainabilityRequest,
)
from server.agents.maintainability.manager.agent import (
    MaintainabilityManagerExecution,
    coverage_router,
)
from server.agents.maintainability.manager.registry import COORDINATORS
from server.agents.maintainability.manager.schemas import RawAssessment
from server.agents.maintainability.modularity.coordinator.schemas import Consumption
from server.blackboard.identity import AuditIdentity
from server.blackboard.impls.memory import MemoryBlackboard
from server.infrastructure.tracing import NoOpTracingBackend
from server.runtimes.investigation.schemas import InvestigationConfig

BASE = ["analyze_audit_scope", "plan_audit", "delegate_auditors", "collect_assessments", "synthesize_assessments"]


def test_explicit_models_reach_coordinators_and_their_investigators(repo):
    from server.app.audit_models import MAINTAINABILITY_AGENT_TYPES

    selected = {name: NativeStructuredModel([{"summary": f"Synthesis by {name}"}])
        for name in MAINTAINABILITY_AGENT_TYPES}
    received = {}
    received_limits = {}
    overrides = {"modularity": 2000, "responsibility": 16000, "reusability": 12000}

    def coordinator(key, model, limits):
        received[key] = model
        received_limits[key] = limits.max_output_tokens
        make = modularity_factory([]) if key == "modularity" else reusability_factory([])

        def investigator(name, child_model, child_limits):
            received[name] = child_model
            received_limits[name] = child_limits.max_output_tokens
            return make(name, child_model, child_limits)

        return COORDINATORS[key].agent_class(model, limits, investigator_factory=investigator,
            tracing_backend=NoOpTracingBackend())

    agent = MaintainabilityManagerAgent(selected["maintainability_manager"], config(),
        coordinator_factory=coordinator, tracing_backend=NoOpTracingBackend())
    agent.agent_models = selected
    agent.agent_output_limits = overrides
    result = asyncio.run(agent.run(toolset(repo, max_model_calls=400, max_tool_calls=500,
        max_total_tokens=1_000_000, max_tokens_per_objective=1_000_000,
        max_output_tokens_per_call=16000), MaintainabilityRequest(targets=["main.py"])))
    assert result.status == "complete"
    assert set(received) == set(selected) - {"maintainability_manager"}
    assert all(model is selected[name] for name, model in received.items())
    assert all(value == overrides.get(name, 4000) for name, value in received_limits.items())


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "main.py").write_text("def entry():\n    return 1\n", encoding="utf-8")
    return root


def tools(root):
    return toolset(root, max_model_calls=400, max_tool_calls=500, max_total_tokens=1_000_000,
        max_tokens_per_objective=1_000_000, max_retrieved_characters=600_000, max_elapsed_seconds=600)


def config(**updates):
    return MaintainabilityConfig(**({"provider_rate_limits": {"requests_per_minute": None, "tokens_per_minute": None},
        "invocation_limits": {"max_rounds": 1, "max_total_tokens": 100_000,
            "invocation_limits": InvestigationConfig(max_model_calls=4, max_total_tokens=10_000, max_tool_calls=4)}} | updates))


class Events(NoOpTracingBackend):
    def __init__(self):
        self.records = []

    async def wrap_stage(self, coro, *, name, **metadata):
        self.records.append((name, metadata))
        return await coro


def controlled_coordinators(calls, *, fail=None, partial_first=False, persistent=False, delay=None, malformed=None, extra_followup_source=False):
    counts = {}
    reuse_make = reusability_factory([])
    def create(key, model, limits):
        async def run(child, request):
            counts[key] = counts.get(key, 0) + 1
            calls.append((key, child, request))
            if key == fail:
                raise RuntimeError("private provider credential must not appear")
            if delay and key == "modularity":
                await asyncio.sleep(delay)
            spec = COORDINATORS[key]
            # Build schema-correct controlled assessments using established fixture
            # adapters. Coordinator behavior here is not semantic accuracy evidence.
            make = modularity_factory([]) if key == "modularity" else reuse_make
            if key == "reusability" and counts[key] > 1 and extra_followup_source:
                original = make
                def with_additional_source(investigator, model, limits):
                    worker = original(investigator, model, limits)
                    async def inspect(tools, args):
                        tools.execute("get_source_excerpt", {"path": "extra.py", "start_line": 1, "end_line": 2}, tool_call_id="extra")
                        value = await worker.run(tools, args)
                        return value.model_copy(update={"tool_calls": value.tool_calls + 1})
                    return SimpleNamespace(run=inspect)
                make = with_additional_source
            result = await spec.agent_class(NativeStructuredModel([{"summary": "Controlled scoped assessment."}]), limits,
                investigator_factory=make, tracing_backend=NoOpTracingBackend()).run(child, request)
            if key == "reusability" and (persistent or partial_first and counts[key] == 1):
                records = [r.model_copy(update={"evidence": [], "result": r.result.model_copy(update={"findings": []})}) for r in result.invocations]
                result = result.model_copy(update={"status": "partial", "invocations": records, "consolidated_findings": []})
            if malformed and key == "reusability":
                result = result.model_copy(update={"snapshot_hash": "bad"} if malformed == "snapshot" else
                    {"consumption": Consumption(model_calls=9999)} if malformed == "usage" else {"objective": "stale objective"})
            return result
        return SimpleNamespace(run=run)
    return create


def run(root, drafts=None, *, cfg=None, factory=None, req=None):
    before = fingerprints(root)
    events = Events()
    result = asyncio.run(MaintainabilityManagerAgent(NativeStructuredModel(drafts or [{"summary": "Scoped synthesis."}]),
        cfg or config(), coordinator_factory=factory or controlled_coordinators([]), tracing_backend=events).run(tools(root),
        req or MaintainabilityRequest(targets=["main.py"])))
    print("MANAGER", result.status, result.termination_reason, result.node_transitions,
        [(r.assignment.investigator_id, r.assignment.attempt, r.status) for r in result.assessments])
    assert fingerprints(root) == before
    assert MaintainabilityReport.model_validate_json(result.model_dump_json()) == result
    assert all(e.snapshot_hash == result.snapshot_hash for e in result.evidence.values())
    assert len({r.assignment.invocation_id for r in result.assessments}) == len(result.assessments)
    return result, events


def test_manager_synthesis_can_recover_after_transient_provider_failure(repo):
    class Unavailable(Exception):
        status_code = 503

    model = NativeStructuredModel([Unavailable(), {"summary": "Recovered synthesis"}])
    agent = MaintainabilityManagerAgent(model, config(max_provider_retries=0), tracing_backend=NoOpTracingBackend())
    execution = MaintainabilityManagerExecution(agent, tools(repo), MaintainabilityRequest(targets=["main.py"]))
    state = execution.initial_state()
    state.update(execution.analyze_audit_scope(state))
    first = asyncio.run(execution.synthesize_assessments(state))
    assert any(gap.kind == "synthesis_failure" for gap in first["material_gaps"])
    state.update(first)
    second = asyncio.run(execution.synthesize_assessments(state))
    assert not any(gap.kind == "synthesis_failure" for gap in second["material_gaps"])
    assert second["summary"] == "Recovered synthesis"
    assert execution.synth.calls == execution.spent.model_calls == 2


def test_complete_first_pass_exact_nodes_and_provenance(repo):
    calls = []
    result, events = run(repo, factory=controlled_coordinators(calls, delay=0.01))
    assert result.status == "complete" and result.coverage.sufficient
    assert result.coverage.covered == ["modularity", "reusability"]
    assert result.node_transitions == [*BASE, "finalize_audit"]
    assert len(calls) == 2 and all(c[2].targets == ["main.py"] for c in calls)
    assert all(c[1].context.input.budget.max_retrieved_characters == 600_000 for c in calls)
    assert calls[0][1].retrieval_budget is calls[1][1].retrieval_budget
    assert len({id(c[1]) for c in calls}) == 2
    assert all(r.evidence_sufficient and len(r.result.invocations) == 3 for r in result.assessments)
    assert all(m["audit_id"] == result.assessment_id for name, m in events.records if name == "maintainability-coordinator")
    execution = MaintainabilityManagerExecution(MaintainabilityManagerAgent(NativeStructuredModel([]), config()), tools(repo), MaintainabilityRequest())
    graph = execution.graph.get_graph()
    assert set(graph.nodes) == {*BASE, "refine_audit_plan", "finalize_audit", "__start__", "__end__"}
    assert {(e.source, e.target) for e in graph.edges if e.conditional} == {
        ("synthesize_assessments", "finalize_audit"), ("synthesize_assessments", "refine_audit_plan")}


@pytest.mark.parametrize("tamper", [None, "git_blob_id", "content_hash", "tool_call_id", "start_line", "symbol_ids"])
def test_canonical_attribution_survives_collection_and_rejects_tampering(repo, monkeypatch, tamper):
    from test_modularity import result as leaf_result

    from server.runtimes.coordination.execution import CoordinatorExecution
    from server.runtimes.investigation.agent import InvestigationExecution
    from server.runtimes.investigation.provenance import CommitVerification

    monkeypatch.setattr("server.runtimes.investigation.agent.verify_commit",
        lambda *args: CommitVerification(True, "line_endings_equivalent", "b" * 40))
    for args in (["init"], ["add", "main.py"], ["-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "fixture"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    calls, returned_usage = [], []

    def coordinator_factory(key, model, limits):
        def investigator_factory(identifier, model, child_limits):
            async def inspect(child, request):
                calls.append(identifier)
                child.execute("list_files", {}, tool_call_id="metadata")
                child.execute("get_source_excerpt", {"path": "main.py", "start_line": 1, "end_line": 2}, tool_call_id="source")
                # Exercise real host verification and collection, without provider calls.
                host = SimpleNamespace(tools=child, _commit_checks=child.commit_verifications, remaining_seconds=lambda: 10)
                host.attributed_reference = lambda ref: InvestigationExecution.attributed_reference(host, ref)
                refs, _ = InvestigationExecution.verify_references(host, CoordinatorExecution.references(child))
                return leaf_result(identifier, child, request).model_copy(update={"evidence": refs, "tool_calls": 2})
            return SimpleNamespace(run=inspect)

        async def assess(child, request):
            result = await COORDINATORS[key].agent_class(NativeStructuredModel([{"summary": "Verified partial work."}]), limits,
                investigator_factory=investigator_factory, tracing_backend=NoOpTracingBackend()).run(child, request)
            returned_usage.append(result.consumption)
            if tamper:
                record = result.invocations[0]
                refs = list(record.result.evidence)
                value = {"git_blob_id": "c" * 40, "content_hash": "d" * 64, "tool_call_id": "different",
                    "start_line": 2, "symbol_ids": ["different"]}[tamper]
                refs[-1] = refs[-1].model_copy(update={tamper: value})
                altered = record.model_copy(update={"result": record.result.model_copy(update={"evidence": refs})})
                result = result.model_copy(update={"invocations": [altered, *result.invocations[1:]]})
            return result
        return SimpleNamespace(run=assess)

    parent_tools = tools(repo)
    result = asyncio.run(MaintainabilityManagerAgent(NativeStructuredModel([{"summary": "Manager synthesis."}]),
        config(), coordinator_factory=coordinator_factory, tracing_backend=NoOpTracingBackend()).run(parent_tools,
        MaintainabilityRequest(dimensions=["modularity"], targets=["main.py"])))
    assert len(calls) == 3  # A deterministic collection failure must not restart the coordinator.
    assessment = result.assessments[0]
    assert assessment.consumption == returned_usage[0]
    assert not assessment.consumption.model_calls_estimated
    if tamper:
        assert assessment.result is None and not assessment.evidence
        assert assessment.failure.code == "uncollected_nested_evidence"
        assert f"differing_fields={tamper}" in assessment.failure.diagnostics
        assert any("result.evidence[1]" in line for line in assessment.failure.diagnostics)
    else:
        assert result.status == "complete"
        for record in assessment.result.invocations:
            assert record.evidence == record.result.evidence
            assert len({e.id for e in record.evidence}) == len(record.evidence) == 2
            assert {e.kind for e in record.evidence} == {"source", "metadata"}
            assert all(e.commit_verification == "line_endings_equivalent" and e.git_blob_id == "b" * 40 for e in record.evidence)


def test_shared_budget_dispatches_both_dimensions_and_all_investigators(repo):
    from config.agents.audit import AuditAgentDefaults, apply_audit_defaults
    from server.runtimes.repository.shared_tokens import SharedTokenBudget

    investigators = []

    def coordinator_factory(key, model, limits):
        assert limits.max_total_tokens == 500000
        make = modularity_factory([]) if key == "modularity" else reusability_factory([])

        def investigator_factory(identifier, model, child_limits):
            investigators.append((identifier, child_limits.max_total_tokens))
            worker = make(identifier, model, child_limits)

            async def run(child_tools, request):
                result = await worker.run(child_tools, request)
                # Simulate known per-agent usage: three investigators together
                # exceed their coordinator's personal 500k allowance.
                reservation = child_tools.token_budget.reserve(200000)
                assert reservation is not None
                reservation.settle(200000)
                return result.model_copy(update={"accounted_tokens": 200000, "estimated_tokens": 0})

            return SimpleNamespace(run=run)

        return COORDINATORS[key].agent_class(NativeStructuredModel([{"summary": "Controlled assessment."}]), limits,
            investigator_factory=investigator_factory, tracing_backend=NoOpTracingBackend())

    configured = apply_audit_defaults(config(), AuditAgentDefaults(max_context_characters=160000, max_total_tokens=500000))
    repository_tools = toolset(repo, max_model_calls=400, max_tool_calls=500,
        max_total_tokens=3000000, max_tokens_per_objective=3000000,
        max_retrieved_characters=600000, max_elapsed_seconds=600)
    repository_tools.token_budget = SharedTokenBudget(3000000)
    manager = MaintainabilityManagerAgent(NativeStructuredModel([{"summary": "Scoped synthesis."}]), configured,
        coordinator_factory=coordinator_factory, tracing_backend=NoOpTracingBackend())
    result = asyncio.run(manager.run(repository_tools, MaintainabilityRequest(targets=["main.py"])))
    assert result.status == "complete"
    assert {item.assignment.investigator_id for item in result.assessments} == {"modularity", "reusability"}
    assert len(investigators) == len({identifier for identifier, _ in investigators}) == 6
    assert all(tokens == 500000 for _, tokens in investigators)
    assert all(len(item.result.invocations) == 3 for item in result.assessments)
    assert all(item.result.consumption.accounted_tokens > 500000 for item in result.assessments)
    assert 1200000 <= repository_tools.token_budget.used < 3000000


def test_blackboard_propagates_through_manager_coordinators_and_factory_investigators(repo):
    board = MemoryBlackboard()
    coordinators, investigators = [], []

    def create_coordinator(key, model, limits):
        make = modularity_factory([]) if key == "modularity" else reusability_factory([])

        def create_investigator(identifier, model, limits):
            investigator = make(identifier, model, limits)
            investigators.append(investigator)
            return investigator

        coordinator = COORDINATORS[key].agent_class(
            NativeStructuredModel([{"summary": "Controlled assessment."}]), limits,
            investigator_factory=create_investigator, tracing_backend=NoOpTracingBackend(),
        )
        coordinators.append(coordinator)
        return coordinator

    manager = MaintainabilityManagerAgent(
        NativeStructuredModel([{"summary": "Scoped synthesis."}]), config(),
        coordinator_factory=create_coordinator, tracing_backend=NoOpTracingBackend(), blackboard=board,
        audit_identity=AuditIdentity(run_id="shared-audit", invocation_id="root-execution"),
    )
    result = asyncio.run(manager.run(tools(repo), MaintainabilityRequest(targets=["main.py"])))

    assert result.status == "complete"
    assert result.assessment_id == "shared-audit"
    assert len(coordinators) == 2 and len(investigators) == 6
    assert all(agent.blackboard is board for agent in [manager, *coordinators, *investigators])
    assessments = board.query_assessments(result.assessment_id)
    assert len(assessments) == 3
    parent = next(a for a in assessments if a.agent_id == "maintainability_manager")
    assert parent.status == result.status
    assert parent.invocation_id == "root-execution"
    assert parent.details["report"] == result.model_dump(mode="json", serialize_as_any=True)
    assert len(parent.assessment_ids) == 2
    assert set(parent.assessment_ids) == {a.id for a in assessments if a is not parent}
    assert len(parent.evidence_ids) == 6
    assert all(board.get_evidence(result.assessment_id, identifier) is not None for identifier in parent.evidence_ids)
    assert {a.invocation_id for a in assessments if a.id in parent.assessment_ids} == {
        a.assignment.invocation_id for a in result.assessments}
    investigator_ids = {
        invocation.assignment.invocation_id for assessment in result.assessments for invocation in assessment.result.invocations
    }
    evidence = [board.get_evidence(result.assessment_id, identifier) for identifier in parent.evidence_ids]
    assert {record.invocation_id for record in evidence} == investigator_ids
    assert len({record.invocation_id for record in [*assessments, *evidence]}) == 9
    assert all(assessment.result.assessment_id == assessment.assignment.invocation_id for assessment in result.assessments)
    baseline_model = NativeStructuredModel([{"summary": "Scoped synthesis."}])
    baseline = asyncio.run(MaintainabilityManagerAgent(
        baseline_model, config(), coordinator_factory=controlled_coordinators([]), tracing_backend=NoOpTracingBackend(),
    ).run(tools(repo), MaintainabilityRequest(targets=["main.py"])))
    assert len(manager.model.history) == len(baseline_model.history) == 1
    assert all(len(coordinator.model.history) == 1 for coordinator in coordinators)
    assert result.consumption.model_calls == baseline.consumption.model_calls
    assert result.consumption.tool_calls == baseline.consumption.tool_calls
    assert result.node_transitions == baseline.node_transitions


def test_publication_conflict_keeps_siblings_and_usage_without_restarting_coordinator(repo):
    from test_modularity import result as leaf_result

    from server.blackboard.models import Evidence
    from server.runtimes.coordination.execution import CoordinatorExecution

    board, coordinator_calls, investigator_calls, originals = MemoryBlackboard(), [], [], []

    def create_coordinator(key, model, limits):
        coordinator_calls.append(key)

        def create_investigator(identifier, model, limits):
            worker = SimpleNamespace()

            async def inspect(child, request):
                investigator_calls.append(identifier)
                child.execute("get_source_excerpt", {"path": "main.py", "start_line": 1, "end_line": 2}, tool_call_id="read")
                if identifier == "responsibility":
                    # Simulate an interrupted prior publication with a genuine
                    # conflicting record, not a completed investigator receipt.
                    publication = worker._blackboard_publication
                    ref = CoordinatorExecution.references(child)[0]
                    original = Evidence(**publication._identity("evidence", ref.id), source=ref.path,
                        **ref.model_dump(exclude={"id", "path", "content_hash"}), content_hash="PRIVATE_ORIGINAL_HASH")
                    board.publish_evidence(original)
                    originals.append(original)
                return leaf_result(identifier, child, request)

            worker.run = inspect
            return worker

        return COORDINATORS[key].agent_class(NativeStructuredModel([{"summary": "Retain siblings; publication conflict unresolved."}]),
            limits, investigator_factory=create_investigator, tracing_backend=NoOpTracingBackend())

    manager = MaintainabilityManagerAgent(NativeStructuredModel([{"summary": "Coverage remains incomplete."}]),
        config(max_rounds=3), coordinator_factory=create_coordinator, tracing_backend=NoOpTracingBackend(), blackboard=board)
    report = asyncio.run(manager.run(tools(repo), MaintainabilityRequest(dimensions=["modularity"], targets=["main.py"])))
    assert coordinator_calls == ["modularity"] and len(investigator_calls) == 3
    assert report.status == "partial" and report.termination_reason == "no_actionable_follow_up"
    assessment = report.assessments[0]
    assert assessment.result is not None and assessment.failure is None
    records = assessment.result.invocations
    failed = next(r for r in records if r.assignment.investigator_id == "responsibility")
    assert failed.status == "failed" and failed.result is None
    assert failed.failure.code == "blackboard_publication_conflict" and failed.failure.stage == "publish_result"
    assert "PRIVATE_ORIGINAL_HASH" not in failed.failure.model_dump_json()
    assert failed.consumption.model_calls == 4 and not failed.consumption.model_calls_estimated
    assert assessment.consumption.model_calls == 13 and report.consumption.model_calls == 14
    assert all(r.status == "completed" for r in records if r is not failed)
    assert board.get_evidence(originals[0].run_id, originals[0].id) == originals[0]
    assert len(board.query_evidence(report.assessment_id)) == 3


def test_partial_audits_publish_available_children_and_reusing_the_manager_starts_a_new_audit(repo):
    board = MemoryBlackboard()
    manager = MaintainabilityManagerAgent(
        NativeStructuredModel([{"summary": "Partial audit."}, {"summary": "Another partial audit."}]),
        config(max_rounds=1), coordinator_factory=controlled_coordinators([], fail="reusability"),
        tracing_backend=NoOpTracingBackend(), blackboard=board,
    )
    reports = [asyncio.run(manager.run(tools(repo), MaintainabilityRequest(targets=["main.py"]))) for _ in range(2)]

    assert reports[0].assessment_id != reports[1].assessment_id
    for report in reports:
        assert report.status == "partial"
        records = board.query_assessments(report.assessment_id)
        assert len(records) == 2
        parent = next(record for record in records if record.agent_id == "maintainability_manager")
        assert parent.status == "partial" and len(parent.assessment_ids) == 1
        assert parent.limitations and parent.gaps
        assert parent.details["report"]["assessments"][1]["status"] == "failed"
        assert all(board.get_evidence(report.assessment_id, identifier) is not None for identifier in parent.evidence_ids)


def test_coverage_refinement_targets_only_reusability(repo):
    calls = []
    result, _ = run(repo, [{"summary": "Missing reuse evidence."}, {"summary": "Coverage recovered."}],
        factory=controlled_coordinators(calls, partial_first=True))
    assert result.status == "complete" and result.rounds_completed == 2
    assert [c[0] for c in calls] == ["modularity", "reusability", "reusability"]
    assert result.node_transitions == [*BASE, "refine_audit_plan", "delegate_auditors", "collect_assessments", "synthesize_assessments", "finalize_audit"]
    assert [h.decision.route for h in result.synthesis_history] == ["no", "yes"]
    assert result.assessments[1].status == "partial" and result.assessments[2].status == "completed"
    assert result.assessments[2].assignment.attempt == 2 and result.assessments[2].assignment.gap_ids


def test_partial_coordinator_exception_preserves_success(repo):
    calls = []
    result, _ = run(repo, cfg=config(max_rounds=1), factory=controlled_coordinators(calls, fail="reusability"))
    assert result.status == "partial" and not result.coverage.sufficient
    assert result.coverage.covered == ["modularity"] and len(result.assessments) == 2
    assert result.assessments[1].error == "RuntimeError"
    assert "private provider" not in result.model_dump_json()
    assert result.assessments[0].result and result.assessments[1].consumption.model_calls_estimated
    assert result.node_transitions == [*BASE, "finalize_audit"]


@pytest.mark.parametrize("updates,reason", [({"max_rounds": 1}, "round_limit"),
    ({"max_invocations": 2}, "resource_limit"), ({"max_attempts_per_dimension": 1}, "no_actionable_follow_up")])
def test_exhaustion_finalizes_without_sufficient_coverage(repo, updates, reason):
    result, _ = run(repo, cfg=config(**updates), factory=controlled_coordinators([], persistent=True))
    assert result.status == "partial" and result.termination_reason == reason
    assert not result.coverage.sufficient and result.coverage.route == "yes"
    assert result.node_transitions == [*BASE, "finalize_audit"] and len(result.assessments) == 2


def test_persistent_gap_is_bounded_and_preserves_prior_attempt(repo):
    result, _ = run(repo, [{"summary": "Missing evidence."}, {"summary": "Still missing."}],
        cfg=config(max_rounds=4), factory=controlled_coordinators([], persistent=True))
    assert result.status == "partial" and result.rounds_completed == 2
    assert result.termination_reason == "zero_progress" and len(result.assessments) == 3


def test_single_dimension_scope_does_not_delegate_unrequested_dimension(repo):
    calls = []
    result, _ = run(repo, req=MaintainabilityRequest(dimensions=[" Modularity ", "modularity"], targets=["main.py"]),
        factory=controlled_coordinators(calls))
    assert result.status == "complete" and [c[0] for c in calls] == ["modularity"]
    assert result.coverage.required == result.coverage.covered == ["modularity"] and not result.unresolved_gaps


def test_unsupported_requested_dimensions_are_not_claimed_as_passed(repo):
    result, _ = run(repo, req=MaintainabilityRequest(dimensions=["modularity", "testability"], targets=["main.py"]))
    assert result.status == "partial" and result.scope.unsupported == ["testability"]
    assert not result.coverage.sufficient and any(g.kind == "unsupported" for g in result.unresolved_gaps)


def test_no_supported_dimension_finalizes_failed(repo):
    result, events = run(repo, req=MaintainabilityRequest(dimensions=["analysability"]))
    assert result.status == "failed" and not result.assessments and not events.records
    assert result.node_transitions == [*BASE, "finalize_audit"]


def test_token_budget_skips_unfunded_coordinators(repo):
    calls = []
    result, _ = run(repo, cfg=config(max_total_tokens=1000), factory=controlled_coordinators(calls))
    assert not calls and result.status == "failed" and result.termination_reason == "resource_limit"
    assert result.consumption.model_calls == 0 and all(r.status == "skipped" for r in result.assessments)


@pytest.mark.parametrize("malformed", ["snapshot", "usage", "objective"])
def test_malformed_subordinate_results_cannot_supply_coverage(repo, malformed):
    result, _ = run(repo, cfg=config(max_rounds=1), factory=controlled_coordinators([], malformed=malformed))
    assert result.status == "partial" and result.assessments[-1].result is None
    assert not result.assessments[-1].evidence and result.assessments[-1].error == "ValueError"


def test_unknown_synthesis_references_are_not_accepted(repo):
    result, _ = run(repo, [{"summary": "Invalid", "links": [{"kind": "overlap", "finding_refs": ["fake/a", "fake/b"], "rationale": "Invalid"}]}])
    assert result.status == "partial" and any(g.kind == "synthesis_failure" for g in result.unresolved_gaps)


def conflict(messages):
    context = json.loads(messages[1].content)
    refs = list(context["findings"])[:2]
    return {"summary": "Controlled contradiction requires a targeted check.", "links": [{"kind": "contradiction", "finding_refs": refs,
        "rationale": "Simulated disagreement, not semantic proof."}], "gaps": [{"id": "proposed", "kind": "contradiction", "coordinator": "reusability",
        "question": "Inspect the contradiction using additional source context.", "targets": ["main.py"], "finding_refs": refs}]}


def test_blocking_conflict_stays_unresolved_when_limits_prevent_followup(repo):
    result, _ = run(repo, [conflict], cfg=config(max_rounds=1))
    assert result.status == "partial" and result.coverage.covered == ["modularity", "reusability"]
    assert not result.coverage.sufficient and any(g.kind == "contradiction" for g in result.unresolved_gaps)
    assert result.links[0].kind == "contradiction"


def test_blocking_conflict_refines_only_assigned_coordinator(repo):
    calls = []
    result, _ = run(repo, [conflict, {"summary": "No new source; contradiction retained."}],
        factory=controlled_coordinators(calls))
    assert result.status == "partial" and [c[0] for c in calls] == ["modularity", "reusability", "reusability"]
    assert result.termination_reason == "round_limit" and any(g.kind == "contradiction" for g in result.unresolved_gaps)


def test_duplicate_unknown_and_stale_responses_do_not_overwrite_attempts(repo):
    async def execute():
        agent = MaintainabilityManagerAgent(NativeStructuredModel([]), config(), coordinator_factory=controlled_coordinators([]))
        execution = MaintainabilityManagerExecution(agent, tools(repo), MaintainabilityRequest(targets=["main.py"]))
        state = execution.initial_state()
        state.update(execution.analyze_audit_scope(state))
        state.update(execution.plan_audit(state))
        state.update(await execution.delegate_auditors(state))
        first = state["execution_records"][0]
        unknown = first.model_copy(update={"assignment": first.assignment.model_copy(update={"invocation_id": "unknown"})})
        state["execution_records"] += [first, unknown]
        update = execution.collect_assessments(state)
        assert len(update["investigation_results"]) == 2 and len(update["ignored_responses"]) == 2
        spent = execution.spent
        state.update(update)
        state["execution_records"] = [first, RawAssessment(assignment=first.assignment.model_copy(update={"round": 9}), status="failed")]
        late = execution.collect_assessments(state)
        assert late["investigation_results"] == update["investigation_results"] and execution.spent == spent
        assert len(late["ignored_responses"]) == 4
    asyncio.run(execute())


def test_router_does_not_equate_forced_stop_with_sufficiency(repo):
    result, _ = run(repo, cfg=config(max_rounds=1), factory=controlled_coordinators([], persistent=True))
    assert coverage_router({"decision": result.coverage, "actionable_followups": []}) == "yes"
    assert not result.coverage.sufficient


def test_duplicate_and_late_responses_through_actual_manager_graph(repo, monkeypatch):
    original = MaintainabilityManagerExecution.delegate_auditors
    async def duplicate(self, state):
        update = await original(self, state)
        first = update["execution_records"][0]
        stale = first.model_copy(update={"assignment": first.assignment.model_copy(update={"invocation_id": "late", "round": 99})})
        update["execution_records"] += [first, stale]
        return update
    monkeypatch.setattr(MaintainabilityManagerExecution, "delegate_auditors", duplicate)
    result, _ = run(repo)
    assert result.status == "complete" and len(result.assessments) == 2
    assert len(result.ignored_responses) == 2 and "late" in result.ignored_responses
    assert result.node_transitions == [*BASE, "finalize_audit"]
    assert result.consumption.model_calls == 27  # 13 per child + manager synthesis.


def test_timeout_retains_other_coordinator_and_charges_unknown_reservation(repo):
    def create(key, model, limits):
        if key != "reusability":
            return controlled_coordinators([])(key, model, limits)
        async def run(*args):
            await asyncio.Event().wait()
        return SimpleNamespace(run=run)
    child = config().invocation_limits.model_copy(update={"timeout_seconds": 0.5})
    result, _ = run(repo, cfg=config(max_rounds=1, invocation_limits=child), factory=create)
    assert result.status == "partial" and result.assessments[0].result
    assert result.assessments[1].status == "timeout" and result.assessments[1].consumption.model_calls_estimated


def test_parent_cancellation_propagates_and_cancels_pending_work(repo):
    async def execute():
        started, cancelled = asyncio.Event(), []
        def create(key, *args):
            async def run(*args):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.append(key)
            return SimpleNamespace(run=run)
        agent = MaintainabilityManagerAgent(NativeStructuredModel([]), config(), coordinator_factory=create,
            tracing_backend=NoOpTracingBackend())
        task = asyncio.create_task(agent.run(tools(repo), MaintainabilityRequest()))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled and set(cancelled) <= {"modularity", "reusability"}
    asyncio.run(execute())


def test_requested_subscopes_are_enforced_and_not_expanded_by_synthesis(repo):
    with pytest.raises(ValueError, match="outside the requested scope"):
        run(repo, req=MaintainabilityRequest(targets=["main.py"], dimension_targets={"reusability": ["outside.py"]}))
    def outside(messages):
        return {"summary": "Invalid target", "gaps": [{"id": "invalid", "coordinator": "reusability", "kind": "quality",
            "question": "Inspect outside scope", "targets": ["../outside.py"]}]}
    result, _ = run(repo, [outside])
    assert result.status == "partial" and any(g.kind == "synthesis_failure" for g in result.unresolved_gaps)


def test_google_native_manager_schema_and_usage_without_paid_transport(repo, monkeypatch):
    from google.genai import types
    from langchain_google_genai import ChatGoogleGenerativeAI

    model = ChatGoogleGenerativeAI(model="gemini-3.5-flash-lite", api_key="offline-key", max_tokens=2048, max_retries=0)
    requests = []
    async def generate_content(**kwargs):
        requests.append(kwargs)
        schema = kwargs["config"].response_json_schema
        assert schema["title"] == "AssessmentSynthesis" and "maxItems" not in json.dumps(schema)
        return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model",
            parts=[types.Part(text=json.dumps({"summary": "Scoped synthesis through mocked Google transport."}))]), finish_reason="STOP")],
            usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=100, candidates_token_count=30, total_token_count=130))
    monkeypatch.setattr(model.async_client.models, "generate_content", generate_content)
    result = asyncio.run(MaintainabilityManagerAgent(model, config(max_output_tokens=512, provider_request_timeout_seconds=3),
        coordinator_factory=controlled_coordinators([]), tracing_backend=NoOpTracingBackend()).run(tools(repo),
            MaintainabilityRequest(targets=["main.py"])))
    assert result.status == "complete" and len(requests) == 1
    assert result.consumption.accounted_tokens >= 730 and result.consumption.model_calls == 27
    assert model.max_output_tokens == 2048 and requests[0]["config"].max_output_tokens == 512
    assert model.timeout is None and requests[0]["config"].http_options.timeout == 3000


def test_conflict_resolution_requires_assigned_completed_attempt_and_new_source(repo):
    (repo / "extra.py").write_text("def extra():\n    return 2\n", encoding="utf-8")
    def resolve(messages):
        context = json.loads(messages[1].content)
        gap = next(g for g in context["gaps"] if g["kind"] == "contradiction")
        invocation = context["assessments"][-1]
        evidence = [r for r, e in context["evidence"].items() if r.startswith(invocation["invocation_id"] + "/") and e["path"] == "extra.py"]
        return {"summary": "Controlled targeted resolution from additional inspected source.", "resolutions": [{
            "gap_id": gap["id"], "invocation_id": invocation["invocation_id"], "evidence_refs": evidence[:1],
            "rationale": "The follow-up supplied the previously uninspected function body range."}]}
    result, _ = run(repo, [conflict, resolve], factory=controlled_coordinators([], extra_followup_source=True))
    assert result.status == "complete" and result.resolved_gap_ids and not result.unresolved_gaps
    assert result.links[0].status == "resolved" and result.synthesis_history[0].gaps
