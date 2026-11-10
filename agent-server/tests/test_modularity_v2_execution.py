"""Real V2 coordinator graph with simulated native investigator interfaces."""

import asyncio
import json
from dataclasses import replace
from typing import ClassVar

import pytest
from pydantic import ValidationError
from test_architecture_boundary_planning import tools_for
from test_maintainability_v2_plan_audit import Model

from config.agents import InvestigationConfig
from server.agents.maintainability.v2.modularity.coordinator import (
    AssessmentRequest,
    AssessmentResult,
    ModularityConfig,
    ModularityCoordinator,
    dispatch,
    registry,
)
from server.agents.maintainability.v2.modularity.coordinator.registry import (
    registered_investigators as production_registry,
)
from server.contracts.audit import (
    AuditRequest,
    AuditResult,
    Criterion,
    EvidenceReference,
    Finding,
    InvestigationPlan,
)
from server.runtimes.repository.context import RepositoryContext


class Tracing:
    async def wrap_stage(self, operation, **metadata):
        return await operation


@pytest.fixture
def tools(tmp_path):
    tools = tools_for(tmp_path, {"Checkout/api.py": "class Checkout:\n    pass\n", "Checkout/store.py": "class Store:\n    pass\n"})
    tools.context = RepositoryContext(tools.context.snapshot, tools.context.input.model_copy(update={
        "budget": tools.context.input.budget.model_copy(update={"max_model_calls": 64, "max_tool_calls": 100,
            "max_total_tokens": 300_000, "max_tokens_per_objective": 300_000})}))
    return tools


def assignment(key="responsibility", **changes):
    return {"investigator_id": key, "objective": "Examine the requested Checkout interaction.", "targets": [],
        "constraints": ["Preserve uncertainty."], "rationale": "The original request concerns Checkout."} | changes


def ref(tools, identifier="e1", path="Checkout/api.py", **changes):
    file = next(file for file in tools.accessible_snapshot.files if file.path == path)
    return EvidenceReference(**({"id": identifier, "snapshot_hash": tools.context.input.snapshot_hash,
        "commit": tools.accessible_snapshot.repository.commit, "path": file.path, "file_id": file.id,
        "content_hash": file.content_hash, "kind": "source", "start_line": 1, "end_line": 2,
        "tool_call_id": "read-" + identifier} | changes))


def finding(tools, identifier="f1", **changes):
    criterion = Criterion(id="test", description="Explicit fixture rule.", origin="explicit", provenance="Test fixture.")
    return Finding(**({"id": identifier, "title": "Local observation", "description": "A concrete scoped observation.",
        "criterion_id": criterion.id, "kind": "design_observation", "components": ["Checkout/api.py"],
        "evidence_ids": ["e1"], "evidence": [ref(tools)], "justification": "Observed local behavior.",
        "modularity_impact": "Localized maintenance consequence.", "severity": "high", "confidence": 1.0,
        "recommendation": "Review the local contract.", "criterion": criterion, "validation_status": "accepted",
        "review_rationale": "Original investigator judgment, not coordinator review."} | changes))


def result(tools, request, findings=(), **changes):
    return AuditResult(**({"repository_id": tools.accessible_snapshot.repository.name, "commit": tools.accessible_snapshot.repository.commit,
        "snapshot_hash": tools.context.input.snapshot_hash, "objective": request.objective,
        "plan": InvestigationPlan(objectives=[request.objective], components=["Checkout/api.py"], hypotheses=[]),
        "findings": list(findings), "hypotheses": [], "missing_information": [], "limitations": ["Only the assigned local scope."],
        "termination_reason": "sufficient_evidence", "model_calls": 1, "tool_calls": 1, "iterations": 1,
        "accounted_tokens": 30, "estimated_tokens": 0, "evidence": [ref(tools)]} | changes))


def simulated_spec(original, behavior=None):
    class Investigator:
        config_type = InvestigationConfig
        instances: ClassVar[list] = []

        def __init__(self, model, config, *, provider_pacer=None):
            self.model, self.config = model, config
            self.instances.append(self)

        async def run(self, tools, request):
            self.tools, self.request = tools, request
            return await behavior(self, tools, request) if behavior else result(tools, request)

    return replace(original, agent_class=Investigator, result_class=AuditResult)


def fixture_registry():
    """Extra roles are test-only mocks, never V1 implementations or production bindings."""
    originals = production_registry()
    boundary = originals["architecture_boundary"]
    for key in ("responsibility", "dependency_impact"):
        originals[key] = replace(boundary, request_class=AuditRequest, result_class=AuditResult,
            completed_reasons=("sufficient_evidence",), capability=type(boundary.capability)(
                id=key, agent_name="SyntheticTestInvestigator", capability="Test-only capability.", constraints=[]))
    return originals


def run(tools, monkeypatch, assignments, behaviors=None, request=None, *, keys=None):
    originals = fixture_registry()
    specs = {key: simulated_spec(value, (behaviors or {}).get(key)) for key, value in originals.items()
        if keys is None or key in keys}
    monkeypatch.setattr(registry, "registered_investigators", lambda: specs)
    monkeypatch.setattr(dispatch, "registered_investigators", lambda: specs)
    model = Model({"objective": "Assess Checkout.", "assignments": assignments, "uncovered_requirements": [] if assignments else ["No applicable investigators."], "limitations": []})
    config = ModularityConfig(max_model_calls=48, max_tool_calls=90, provider_request_interval_seconds=0,
        invocation_limits=InvestigationConfig(max_model_calls=8, max_tool_calls=8, provider_request_interval_seconds=0))
    coordinator = ModularityCoordinator(model, config, tracing_backend=Tracing())
    output = asyncio.run(coordinator.run(tools, request or AssessmentRequest(objective="Assess Checkout.",
        original_objective="Original maintainability concern in Checkout.", constraints=["Read only."])))
    assert len(model.contexts) == 1  # Only plan_assessment; dispatch/collect/finalize add no LLM calls.
    assert output.node_transitions == ["plan_assessment", "delegate_investigations", "collect_findings", "finalize_assessment"]
    assert AssessmentResult.model_validate_json(output.model_dump_json()).model_dump(mode="json") == output.model_dump(mode="json")
    return output, specs


@pytest.mark.parametrize("count", [1, 2, 3])
def test_executes_only_selected_investigators_and_aggregates_once(tools, monkeypatch, count):
    keys = ["architecture_boundary", "dependency_impact", "responsibility"][:count]
    output, specs = run(tools, monkeypatch, [assignment(key) for key in keys])
    assert output.status == "completed" and len(output.invocations) == count
    assert {row.assignment.investigator_id for row in output.invocations} == set(keys)
    assert sum(len(spec.agent_class.instances) for spec in specs.values()) == count
    assert output.consumption.model_calls == count + 1 and output.consumption.accounted_tokens == 120 + count * 30
    assert len(output.evidence) == 1  # Shared source coordinates are not counted repeatedly.
    assert len(output.coverage.evaluated_investigation_ids) == count
    assert not output.coverage.global_compliance_established


def test_empty_plan_runs_no_investigator(tools, monkeypatch):
    output, specs = run(tools, monkeypatch, [])
    assert output.status == "not_applicable" and not output.invocations and not output.consolidated_findings
    assert all(not spec.agent_class.instances for spec in specs.values()) and output.consumption.model_calls == 1


def test_checkout_semantics_constraints_and_identity_travel_in_native_context(tools, monkeypatch):
    output, specs = run(tools, monkeypatch, [assignment()])
    instance = specs["responsibility"].agent_class.instances[0]
    data = json.loads(instance.request.architectural_context)
    assert instance.request.objective == assignment()["objective"]
    assert data["original_objective"] == output.request.original_objective
    assert data["targets"] is None and "Checkout" in data["delegated_objective"]
    assert "Read only." in data["constraints"] and "Preserve uncertainty." in data["constraints"]
    assert "not an instruction to audit the whole repository" in data["scope_rule"]
    assert all(data[key] == getattr(output, key) for key in ("repository_id", "commit", "snapshot_hash"))
    assert instance.tools is not tools and instance.tools._query_cache is not tools._query_cache


def test_documentary_request_preserves_scope_but_does_not_forward_external_instructions(tools, monkeypatch):
    from server.contracts.audit import InvestigationCommitment

    commitment = InvestigationCommitment(source_invocation_id="prior", question="Recheck this scope.", paths=["Checkout/api.py"])
    request = AssessmentRequest(objective="Checkout", targets=["Checkout"], follow_up=[commitment], follow_up_diagnostics=["Keep uncertainty."])
    output, specs = run(tools, monkeypatch, [assignment("architecture_boundary", targets=["Checkout/api.py"])], request=request)
    native = specs["architecture_boundary"].agent_class.instances[0].request
    assert native.targets == ["Checkout/api.py"] and not native.follow_up
    assert not native.follow_up_diagnostics
    assert "Recheck this scope." not in native.model_dump_json()
    assert "Keep uncertainty." not in native.model_dump_json()
    assert not {"objective", "architectural_context", "follow_up", "follow_up_diagnostics"} & native.model_dump().keys()
    assert output.initial_plan[0].question == native.objective
    assert output.initial_plan[0].source.objective == assignment()["objective"]
    assert output.initial_plan[0].source.targets == ["Checkout/api.py"]


@pytest.mark.parametrize("all_fail", [False, True])
def test_partial_and_total_failures_preserve_successful_siblings(tools, monkeypatch, all_fail):
    async def fail(instance, tools, request):
        token = tools.token_budget.reserve(25)
        token.settle(20)
        raise RuntimeError("secret provider text")

    behaviors = {"dependency_impact": fail}
    if all_fail:
        behaviors["responsibility"] = fail
    output, _ = run(tools, monkeypatch, [assignment(), assignment("dependency_impact")], behaviors)
    assert output.status == ("failed" if all_fail else "partial")
    assert len(output.execution_records) == len(output.invocations) == 2
    assert any(row.failure for row in output.invocations)
    assert output.consumption.model_calls_estimated
    assert "secret provider text" not in output.model_dump_json()
    assert bool(output.coverage.completed_investigation_ids) != all_fail


def test_no_finding_and_inconclusive_results_are_not_fabricated_as_findings(tools, monkeypatch):
    async def inconclusive(instance, tools, request):
        return result(tools, request, missing_information=["Contract not resolved."], termination_reason="model_call_limit")

    output, _ = run(tools, monkeypatch, [assignment(), assignment("dependency_impact")], {"dependency_impact": inconclusive})
    assert output.status == "partial" and not output.consolidated_findings
    assert len(output.coverage.completed_investigation_ids) == len(output.coverage.partial_investigation_ids) == 1
    row = next(row for row in output.invocations if row.assignment.investigator_id == "dependency_impact")
    assert row.result.missing_information == ["Contract not resolved."]


def test_equivalent_findings_merge_without_losing_evidence_or_original_origins(tools, monkeypatch):
    async def first(instance, tools, request):
        return result(tools, request, [finding(tools)])

    async def second(instance, tools, request):
        return result(tools, request, [finding(tools, "other-local-id")])

    output, _ = run(tools, monkeypatch, [assignment(), assignment("dependency_impact")],
        {"responsibility": first, "dependency_impact": second})
    assert len(output.consolidated_findings) == 1
    group = output.consolidated_findings[0]
    assert {c.finding["id"] for c in group.contributions} == {"f1", "other-local-id"}
    assert {c.investigator_id for c in group.contributions} == {"responsibility", "dependency_impact"}
    assert group.severity == "high" and group.confidence == 1.0 and not output.links
    assert all(c.finding["evidence"] for c in group.contributions)


@pytest.mark.parametrize("changes", [{"confidence": .7}, {"severity": "critical"}, {"description": "Another actual concern."},
    {"validation_status": "insufficient_evidence"}])
def test_related_but_non_equivalent_findings_keep_original_values(tools, monkeypatch, changes):
    async def first(instance, tools, request):
        return result(tools, request, [finding(tools)])

    async def second(instance, tools, request):
        return result(tools, request, [finding(tools, "second", **changes)])

    output, _ = run(tools, monkeypatch, [assignment(), assignment("dependency_impact")],
        {"responsibility": first, "dependency_impact": second})
    assert len(output.consolidated_findings) == 2 and len(output.links) == 1
    assert output.links[0].interpretation == "shared_anchors_only"
    original = next(group.contributions[0].finding for group in output.consolidated_findings if group.contributions[0].investigator_id == "dependency_impact")
    for key, value in changes.items():
        assert original[key] == value
    if "validation_status" in changes:
        assert output.status == "completed"  # Legacy values in synthetic payloads have no V2 verdict semantics.
        assert all("validation_status" not in group.model_dump() for group in output.consolidated_findings)


def test_invalid_evidence_is_reported_and_original_payload_is_retained(tools, monkeypatch):
    async def invalid(instance, tools, request):
        return result(tools, request, [finding(tools, evidence=[ref(tools, content_hash="stale")])])

    output, _ = run(tools, monkeypatch, [assignment()], {"responsibility": invalid})
    # Runner raw output is authoritative: invalid evidence is retained as partial,
    # not erased, so the blackboard persists the same findings.
    assert output.status == "partial" and len(output.consolidated_findings) == 1
    assert output.execution_records[0].value.findings[0].evidence[0].content_hash == "stale"
    assert any("not fully supported" in note for note in output.invocations[0].result.missing_information)


def test_native_continuation_is_forwarded_not_reinvented(tools, monkeypatch):
    from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.schemas import (
        BoundaryResult,
    )

    base = result(tools, registry.registered_investigators()["architecture_boundary"].request_class())
    prior = BoundaryResult.model_validate(base.model_dump())
    request = AssessmentRequest(objective="Checkout", continuations={"architecture_boundary": prior})
    output, specs = run(tools, monkeypatch, [assignment("architecture_boundary")], request=request)
    native = specs["architecture_boundary"].agent_class.instances[0].request
    assert native.continuation == prior
    assert output.consumption.accounted_tokens == 150  # Prior input usage is not charged again.


def test_unsupported_continuation_does_not_silently_start_a_fresh_investigation(tools, monkeypatch):
    request = AssessmentRequest(objective="Checkout", continuations={"responsibility": {"prior": "result"}})
    output, specs = run(tools, monkeypatch, [assignment()], request=request)
    assert output.status == "failed" and not specs["responsibility"].agent_class.instances
    assert output.invocations[0].failure.code == "unsupported_continuation"


def test_concurrent_children_have_isolated_caches_and_budget_scopes(tools, monkeypatch):
    async def scenario():
        both = asyncio.Event()
        entered = []

        async def behavior(instance, child_tools, request):
            entered.append(instance)
            if len(entered) == 2:
                both.set()
            await asyncio.wait_for(both.wait(), timeout=1)
            assert child_tools is not tools
            return result(child_tools, request)

        originals = fixture_registry()
        specs = {key: simulated_spec(value, behavior) for key, value in originals.items() if key in {"responsibility", "dependency_impact"}}
        monkeypatch.setattr(registry, "registered_investigators", lambda: specs)
        monkeypatch.setattr(dispatch, "registered_investigators", lambda: specs)
        model = Model({"objective": "Checkout", "assignments": [assignment(), assignment("dependency_impact")], "uncovered_requirements": [], "limitations": []})
        coordinator = ModularityCoordinator(model, ModularityConfig(max_model_calls=32, max_parallel=2, provider_request_interval_seconds=0,
            invocation_limits=InvestigationConfig(max_model_calls=8, max_tool_calls=4, provider_request_interval_seconds=0)), tracing_backend=Tracing())
        output = await coordinator.run(tools, AssessmentRequest(objective="Checkout"))
        assert output.status == "completed" and len(entered) == 2
        assert entered[0].tools._query_cache is not entered[1].tools._query_cache
        assert entered[0].tools.token_budget is not entered[1].tools.token_budget
        assert entered[0].tools.token_budget.root is entered[1].tools.token_budget.root

    asyncio.run(scenario())


def test_identical_native_requests_are_not_dispatched_twice(tools, monkeypatch):
    output, specs = run(tools, monkeypatch, [assignment(), assignment(rationale="Another rationale for the same request.")])
    assert len(specs["responsibility"].agent_class.instances) == 1
    assert len(output.invocations) == 2 and output.status == "partial"
    assert any(row.failure and row.failure.code == "duplicate_invocation_request" for row in output.invocations)


def test_underreported_tokens_do_not_disappear_or_get_charged_twice(tools, monkeypatch):
    async def understated(instance, tools, request):
        reservation = tools.token_budget.reserve(150)
        reservation.settle(100)
        return result(tools, request, accounted_tokens=30)

    output, _ = run(tools, monkeypatch, [assignment()], {"responsibility": understated})
    assert output.status == "partial" and output.consumption.accounted_tokens == 220
    assert output.invocations[0].consumption.accounted_tokens == 100
    assert output.invocations[0].result.accounted_tokens == 30  # Original report remains intact.


def test_investigator_cannot_override_global_budget_policy():
    bridge = object.__new__(dispatch.InvestigationDispatch)
    bridge.config = ModularityConfig()
    native = registry.registered_investigators()["architecture_boundary"]
    resolved = bridge.invocation_config(native, InvestigationConfig())
    assert not any(key.startswith("unlimited_") for key in type(resolved).model_fields)
    with pytest.raises(ValidationError):
        InvestigationConfig(unlimited_model_calls=True)


def test_coordinator_cancellation_reaches_the_actual_child_task(tools, monkeypatch):
    async def scenario():
        started, cleaned = asyncio.Event(), asyncio.Event()

        async def blocked(instance, tools, request):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        native = fixture_registry()["responsibility"]
        specs = {"responsibility": simulated_spec(native, blocked)}
        monkeypatch.setattr(registry, "registered_investigators", lambda: specs)
        monkeypatch.setattr(dispatch, "registered_investigators", lambda: specs)
        model = Model({"objective": "Checkout", "assignments": [assignment()], "uncovered_requirements": [], "limitations": []})
        coordinator = ModularityCoordinator(model, ModularityConfig(provider_request_interval_seconds=0,
            invocation_limits=InvestigationConfig(max_model_calls=4, max_tool_calls=4, provider_request_interval_seconds=0)), tracing_backend=Tracing())
        task = asyncio.create_task(coordinator.run(tools, AssessmentRequest(objective="Checkout")))
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(cleaned.wait(), timeout=1)

    asyncio.run(scenario())


def test_validation_failure_in_one_result_does_not_erase_a_valid_sibling(tools, monkeypatch):
    async def stale(instance, tools, request):
        return result(tools, request, snapshot_hash="wrong-snapshot")

    output, _ = run(tools, monkeypatch, [assignment(), assignment("dependency_impact")], {"dependency_impact": stale})
    assert output.status == "partial" and len(output.coverage.completed_investigation_ids) == 1
    invalid = next(row for row in output.invocations if row.assignment.investigator_id == "dependency_impact")
    assert invalid.status == "failed" and invalid.failure.code == "repository_provenance_mismatch"
    raw = next(row for row in output.execution_records if row.assignment.investigator_id == "dependency_impact")
    assert raw.value.snapshot_hash == "wrong-snapshot"


def test_insufficient_envelope_does_not_start_or_charge_an_investigator(tools, monkeypatch):
    native = fixture_registry()["responsibility"]
    registered = simulated_spec(native)
    specs = {"responsibility": registered}
    monkeypatch.setattr(registry, "registered_investigators", lambda: specs)
    monkeypatch.setattr(dispatch, "registered_investigators", lambda: specs)
    model = Model({"objective": "Checkout", "assignments": [assignment()], "uncovered_requirements": [], "limitations": []})
    coordinator = ModularityCoordinator(model, ModularityConfig(max_model_calls=4, provider_request_interval_seconds=0), tracing_backend=Tracing())
    output = asyncio.run(coordinator.run(tools, AssessmentRequest(objective="Checkout")))
    assert output.status == "failed" and not registered.agent_class.instances
    assert output.invocations[0].status == "skipped" and output.invocations[0].failure.code == "execution_budget_exhausted"
    assert output.consumption.model_calls == 1


def test_non_executable_registration_returns_an_error_not_a_fabricated_result(tools, monkeypatch):
    class MissingRun:
        config_type = InvestigationConfig

        def __init__(self, model, config, **kwargs):
            pass

    native = fixture_registry()["responsibility"]
    specs = {"responsibility": replace(native, agent_class=MissingRun, result_class=AuditResult)}
    monkeypatch.setattr(registry, "registered_investigators", lambda: specs)
    monkeypatch.setattr(dispatch, "registered_investigators", lambda: specs)
    model = Model({"objective": "Checkout", "assignments": [assignment()], "uncovered_requirements": [], "limitations": []})
    coordinator = ModularityCoordinator(model, ModularityConfig(provider_request_interval_seconds=0), tracing_backend=Tracing())
    output = asyncio.run(coordinator.run(tools, AssessmentRequest(objective="Checkout")))
    assert output.status == "failed" and not output.consolidated_findings
    assert output.invocations[0].result is None and output.invocations[0].failure.exception_type == "AttributeError"


def test_planner_failure_closes_the_graph_without_invoking_any_investigator(tools):
    model = Model("invalid JSON")
    coordinator = ModularityCoordinator(model, ModularityConfig(provider_request_interval_seconds=0), tracing_backend=Tracing())
    output = asyncio.run(coordinator.run(tools, AssessmentRequest(objective="Checkout")))
    assert output.status == "failed" and output.plan is None and not output.invocations
    assert output.node_transitions[-1] == "finalize_assessment" and len(model.contexts) == 1


def test_single_invocation_limit_is_effective_without_forcing_all_three(tools, monkeypatch):
    originals = fixture_registry()
    specs = {key: simulated_spec(value) for key, value in originals.items()}
    monkeypatch.setattr(registry, "registered_investigators", lambda: specs)
    monkeypatch.setattr(dispatch, "registered_investigators", lambda: specs)
    model = Model({"objective": "Checkout", "assignments": [assignment(key) for key in specs], "uncovered_requirements": [], "limitations": []})
    coordinator = ModularityCoordinator(model, ModularityConfig(max_model_calls=48, max_invocations=1,
        provider_request_interval_seconds=0), tracing_backend=Tracing())
    output = asyncio.run(coordinator.run(tools, AssessmentRequest(objective="Checkout")))
    assert output.status == "partial" and len(output.coverage.not_executed_investigation_ids) == 2
    assert sum(len(spec.agent_class.instances) for spec in specs.values()) == 1
    assert output.consumption.model_calls == 2
    with pytest.raises(ValidationError):
        ModularityConfig(max_rounds=2)  # This graph cannot be configured to introduce a new round.


def test_negative_reported_usage_is_not_accepted_as_a_resource_credit(tools, monkeypatch):
    async def negative(instance, tools, request):
        return result(tools, request, accounted_tokens=-30)

    output, _ = run(tools, monkeypatch, [assignment()], {"responsibility": negative})
    assert output.status == "failed"
    assert output.invocations[0].failure.code == "invalid_investigator_consumption"
    assert output.execution_records[0].value.accounted_tokens == -30
    assert output.consumption.accounted_tokens >= 120


def test_documentary_finding_schema_has_no_legacy_review_fields(tools):
    from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.schemas import (
        BoundaryFinding,
        BoundaryResult,
    )

    legacy = finding(tools).model_dump()
    native = BoundaryFinding.model_validate({key: value for key, value in legacy.items()
        if key not in {"validation_status", "review_rationale"}})
    for field in ("validation_status", "review_rationale"):
        assert field not in BoundaryFinding.model_fields
        assert field not in json.dumps(BoundaryResult.model_json_schema())
        with pytest.raises(ValidationError):
            BoundaryFinding.model_validate(native.model_dump() | {field: legacy[field]})
    # The V1/common contract is deliberately unchanged.
    assert {"validation_status", "review_rationale"} <= Finding.model_fields.keys()


def test_v2_graph_uses_unified_agent_observer_without_extra_calls(tools, monkeypatch):
    from test_agent_execution_observer import Sink

    from server.agent_services.execution_tracking import ExecutionObserver
    from server.agent_services.execution_tracking.buffer import ExecutionEventBuffer

    journal, sink = ExecutionEventBuffer(), Sink()
    observer = ExecutionObserver(sink, buffer=journal)
    with observer.scope(71):
        output, _ = run(tools, monkeypatch, [assignment("architecture_boundary")])
    events = [event for _, _, event in journal.pending()]
    assert output.status == "completed" and output.consumption.model_calls == 2
    assert any(event["kind"] == "node.started" and event["name"] == "finalize_assessment" for event in events)
    sink.acknowledged = True
    assert asyncio.run(observer.flush()) and not journal.pending()
