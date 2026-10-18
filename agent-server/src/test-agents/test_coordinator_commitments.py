"""Real coordinator/child graphs: retained scope and same-source validation repairs."""

import asyncio
import json
import shutil
from types import SimpleNamespace

import pytest
from test_architecture_boundary import NativeStructuredModel
from test_component_adaptability import READY, SEED, evaluate, plan, read, review
from test_modularity import config as modularity_config
from test_modularity import result as modularity_result
from test_reusability import config, execute, factory, fake_result, tools

from server.agents.maintainability.manager.synthesis import (
    assessment_indexes,
    synthesis_context,
)
from server.agents.maintainability.modularity.coordinator import ModularityAgent
from server.agents.maintainability.reusability.component_adaptability import (
    ComponentAdaptabilityAgent,
    ComponentAdaptabilityConfig,
)
from server.agents.maintainability.reusability.coordinator import (
    ReusabilityAgent,
    ReusabilityAssessment,
    ReusabilityRequest,
)
from server.app.tracing_port import NoOpTracingBackend
from server.runtimes.coordination.execution import CoordinatorExecution
from server.runtimes.coordination.synthesis import evidence_key
from server.runtimes.investigation.schemas import InvestigationConfig


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "checkout"
    shutil.copytree(SEED, root)
    (root / "main.py").write_text("def entry():\n    return 1\n", encoding="utf-8")
    return root


@pytest.mark.parametrize("followup", ["repaired", "unchanged", "different_question", "input_preparation", "missing_assessment", "extra_gap"])
@pytest.mark.parametrize("through_manager", [False, True])
def test_same_source_repair_requires_final_validation_of_original_commitment(repo, followup, through_manager):
    calls = []
    seen_context = []

    def make(key, model, limits):
        async def run(child, args):
            if key != "component_adaptability":
                child.execute("get_source_excerpt", {"path": "service.py", "start_line": 1, "end_line": 9}, tool_call_id="read")
                return fake_result(key, child, args, finding=False)
            calls.append(args)
            first = len(calls) == 1

            def assess(messages):
                def mutate(value):
                    if first or followup == "unchanged":
                        value["constraint_assessments"][0]["seam_evidence_ids"] = []
                    if followup == "input_preparation":
                        value["constraint_assessments"][0].update(constraint_type="data_schema", seam_evidence_ids=
                            value["constraint_assessments"][0]["supporting_evidence_ids"], schema_dependency_basis="input_contract",
                            schema_adaptation_analysis="The function expects a specific input shape; caller preparation is unread.")
                        value["candidates"][0]["constraint_type"] = "data_schema"
                    if first and followup == "missing_assessment":
                        value.update(constraint_assessments=[], candidates=[])
                    if not first and followup == "extra_gap":
                        value["missing_information"] = ["External deployment contract is unread."]
                return evaluate(messages, mutate=mutate)

            original_plan = plan()

            def planned(messages):
                context = json.loads(messages[1].content)
                if not first:
                    assert context["follow_up_commitments"][0]["subject_ids"] == args.component_ids
                value = original_plan(messages)
                if not first and followup == "different_question":
                    value["hypotheses"][0]["question"] = "An unrelated question about the same component."
                return value

            worker = ComponentAdaptabilityAgent(NativeStructuredModel([
                planned, read(repo, ["service.py"], relationships=False), READY, assess, review("ADAPT-001")]),
                ComponentAdaptabilityConfig(**(limits.model_dump() | {"max_iterations": 1})))
            return await worker.run(child, args)
        return SimpleNamespace(run=run)

    def synthesis(messages):
        context = json.loads(messages[1].content)
        seen_context.append(context)
        if len(seen_context) == 1:
            invocation = next(i for i in context["invocations"] if i["investigator_id"] == "component_adaptability")
            assert invocation["hypotheses"][0]["status"] == "inconclusive"
            if followup == "missing_assessment":
                assert not invocation["analyses"] and invocation["source_inspected_subject_ids"]
            else:
                assert invocation["analyses"][0]["validation_status"] == "insufficient_evidence"
            assert len(context["gaps"]) == 1  # Assessment/candidate/hypothesis messages are one repair.
            assert context["gaps"][0]["task_type"] == ("source_inspection" if followup == "input_preparation" else "validation_repair")
            if followup == "input_preparation":
                assert "callers and input preparation" in context["gaps"][0]["question"]
            return {"summary": "The host rejected a source-backed claim pending seam review."}
        invocation = context["invocations"][-1]
        gap = next(g for g in context["gaps"] if g["id"] in invocation["gap_ids"])
        refs = [r for r in context["evidence"] if r.startswith(invocation["invocation_id"] + "/")]
        return {"summary": "Retain only the host-validated outcome.", "resolutions": [{"gap_id": gap["id"],
            "invocation_id": invocation["invocation_id"], "evidence_refs": refs,
            "explanation": "Reconsidered the already inspected body and completed independent seam review."}]}

    cfg = config(max_rounds=2 if followup == "extra_gap" else 4, invocation_limits=InvestigationConfig(max_model_calls=8,
        max_total_tokens=80_000, max_tool_calls=2, provider_rate_limits={"requests_per_minute": None, "tokens_per_minute": None}))
    if through_manager:
        from test_maintainability_manager import config as manager_config
        from test_maintainability_manager import tools as manager_tools

        from server.agents.maintainability.manager import (
            MaintainabilityManagerAgent,
            MaintainabilityRequest,
        )

        def coordinator(key, model, limits):
            return ReusabilityAgent(NativeStructuredModel([synthesis]), limits, investigator_factory=make,
                tracing_backend=NoOpTracingBackend())

        manager = MaintainabilityManagerAgent(NativeStructuredModel([
            {"summary": "Scoped assessment."}, {"summary": "Scoped repair."}]),
            manager_config(max_rounds=2, invocation_limits=cfg.model_copy(update={"max_rounds": 1})),
            coordinator_factory=coordinator, tracing_backend=NoOpTracingBackend())
        report = asyncio.run(manager.run(manager_tools(repo), MaintainabilityRequest(
            dimensions=["reusability"], targets=["service.py"])))
        assert len(report.assessments) == 2, report.model_dump_json(indent=2)
        before, after = report.assessments
        assert after.result is not None, after.error
        assert after.result.invocations[:3] == before.result.invocations
        assert len(after.result.invocations) == 4
        assert report.status == ("complete" if followup in {"repaired", "missing_assessment"} else "partial")
        result = after.result
    else:
        result = asyncio.run(ReusabilityAgent(NativeStructuredModel([synthesis, synthesis]), cfg,
            investigator_factory=make, tracing_backend=NoOpTracingBackend()).run(tools(repo), ReusabilityRequest(targets=["service.py"])))
    assert len(calls) == 2 and result.rounds_completed == 2, result.model_dump_json(indent=2)
    initial, repaired = [r for r in result.invocations if r.assignment.investigator_id == "component_adaptability"]
    assert {evidence_key(e) for e in initial.evidence} == {evidence_key(e) for e in repaired.evidence}
    assert calls[1].follow_up[0].source_invocation_id == initial.assignment.invocation_id
    assert calls[1].follow_up[0].subject_ids == initial.result.plan.hypotheses[0].component_ids
    if followup in {"repaired", "missing_assessment"}:
        assert result.status == "completed" and result.resolved_gap_ids and not result.material_gaps
    elif followup == "extra_gap":
        assert result.status == "partial" and result.resolved_gap_ids
        assert any("External deployment contract is unread." in g.diagnostics for g in result.material_gaps)
    else:
        assert result.status == "partial" and result.material_gaps and not result.resolved_gap_ids
        assert repaired.status == "partial"
    assert ReusabilityAssessment.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("reason", ["provider_daily_quota_exhausted", "provider_tpm_request_limit", "provider_request_timeout"])
def test_reusability_does_not_redispatch_terminal_provider_blockers(repo, reason):
    calls = []

    def blocked(key, value):
        return value.model_copy(update={"status": "partial", "termination_reason": reason}) if key == "abstraction" else value

    result = execute(repo, cfg=config(max_rounds=4), make=factory(calls, mutate=blocked))
    assert len(calls) == 3 and result.rounds_completed == 1
    assert result.status == "partial" and result.termination_reason == "no_useful_follow_up"


@pytest.mark.parametrize("through_manager", [False, True])
def test_modularity_closes_only_the_validated_same_source_component_repair(repo, through_manager):
    requests = []

    def make(key, model, limits):
        async def run(child, args):
            child.execute("get_source_excerpt", {"path": "main.py", "start_line": 1, "end_line": 2}, tool_call_id="read")
            value = modularity_result(key, child, args)
            if key != "responsibility":
                return value
            requests.append(args)
            first = len(requests) == 1
            source = next(f for f in child.accessible_snapshot.files if f.path == "main.py")
            evidence = CoordinatorExecution.references(child)
            hypothesis = {"id": "h1", "question": "Are entry's responsibilities coherent?",
                "status": "inconclusive" if first else "discarded", "evidence_ids": [e.id for e in evidence]}
            data = value.model_dump() | {"plan": {"objectives": [args.objective], "components": [source.id], "hypotheses": [hypothesis]},
                "hypotheses": [hypothesis], "missing_information": ["Resolve assessment a1: independent_scope_review_incomplete"] if first else [],
                "termination_reason": "iteration_limit" if first else "sufficient_evidence", "components_investigated": [{
                    "id": "a1", "component_id": source.id, "responsibilities": [], "potentially_incompatible": [],
                    "cohesion": "inconclusive" if first else "coherent", "architectural_justification": "Scoped entry body review.",
                    "evidence_ids": [e.id for e in evidence], "path": "main.py", "file_id": source.id,
                    "evidence": evidence, "validation_status": "insufficient_evidence" if first else "source_backed",
                    "validation_issues": ["independent_scope_review_incomplete"] if first else []}]}
            return type(value).model_validate(data)
        return SimpleNamespace(run=run)

    def synthesize(messages):
        context = json.loads(messages[1].content)
        if len(requests) == 1:
            assert len(context["gaps"]) == 1 and context["gaps"][0]["task_type"] == "validation_repair"
            return {"summary": "A component review remains unresolved."}
        invocation = context["invocations"][-1]
        return {"summary": "The component assessment is now host-validated.", "resolutions": [{
            "gap_id": invocation["gap_ids"][0], "invocation_id": invocation["invocation_id"],
            "evidence_refs": [r for r in context["evidence"] if r.startswith(invocation["invocation_id"] + "/")],
            "explanation": "Completed independent review on the same inspected component body."}]}

    if through_manager:
        from test_maintainability_manager import config as manager_config
        from test_maintainability_manager import tools as manager_tools

        from server.agents.maintainability.manager import (
            MaintainabilityManagerAgent,
            MaintainabilityReport,
            MaintainabilityRequest,
        )
        from server.blackboard.impls.memory import MemoryBlackboard

        board = MemoryBlackboard()
        def coordinator(key, model, limits):
            return ModularityAgent(NativeStructuredModel([synthesize]), limits, investigator_factory=make,
                tracing_backend=NoOpTracingBackend())
        report = asyncio.run(MaintainabilityManagerAgent(NativeStructuredModel([
            {"summary": "Pending review."}, {"summary": "Resolved review."}]), manager_config(),
            coordinator_factory=coordinator, tracing_backend=NoOpTracingBackend(), blackboard=board).run(
                manager_tools(repo), MaintainabilityRequest(dimensions=["modularity"])))
        assert report.status == "complete", report.model_dump_json(indent=2)
        assert len(report.assessments) == 2
        before, after = report.assessments
        assert after.assignment.baseline_invocation_id == before.assignment.invocation_id
        assert after.result.invocations[:3] == before.result.invocations
        assert len(after.result.invocations) == 4
        assert after.consumption.model_calls == after.result.consumption.model_calls - before.result.consumption.model_calls
        assert after.consumption.tool_calls == 1
        assert report.resolved_gap_ids
        from server.agents.maintainability.manager.validation import validate_accounting
        from server.services.execution_failures import ExecutionValidationError

        tampered = after.result.model_copy(update={"invocations": [
            after.result.invocations[0].model_copy(update={"warnings": ["rewritten history"]}),
            *after.result.invocations[1:]]})
        with pytest.raises(ExecutionValidationError, match="histórica"):
            validate_accounting(tampered, after.assignment.budget, baseline=before.result)
        assert MaintainabilityReport.model_validate_json(report.model_dump_json()) == report
        assessment = after.result
    else:
        assessment = asyncio.run(ModularityAgent(NativeStructuredModel([synthesize, synthesize]), modularity_config(),
            investigator_factory=make, tracing_backend=NoOpTracingBackend()).run(tools(repo)))
    assert assessment.status == "completed" and assessment.resolved_gap_ids
    assert len(requests) == 2 and requests[-1].follow_up[0].subject_ids


def test_equal_polarity_does_not_merge_different_assessed_contexts(repo):
    def context_specific(key, value):
        if key != "component_adaptability":
            return value
        finding = value.findings[0].model_copy(update={"assessed_context": "A different jurisdiction"})
        return value.model_copy(update={"findings": [finding]})

    def merge(messages):
        context = json.loads(messages[1].content)
        refs = [ref for ref, finding in context["findings"].items() if finding["polarity"] == "barrier"]
        return {"summary": "Attempt to merge distinct contexts.", "groups": [{"finding_refs": refs}]}

    result = execute(repo, [merge], cfg=config(max_rounds=1), make=factory([], mutate=context_specific))
    assert len(result.consolidated_findings) == 3
    assert any(g.kind == "synthesis_failure" for g in result.material_gaps)


def test_conditional_qualifications_survive_conclusions_and_manager_projection(repo):
    conditions = [f"Compatibility condition {i}" for i in range(16)]

    def conditional(key, value):
        if key != "reuse_opportunity":
            return value
        f = value.findings[0].model_copy(update={"classification": "conditional", "conditions": conditions,
            "sharing_boundary": "A parsing helper only; caller policy remains separate.", "unknowns": ["Caller compatibility is unread."]})
        return value.model_copy(update={"findings": [f]})

    def conclude(messages):
        context = json.loads(messages[1].content)
        ref = next(r for r, f in context["findings"].items() if f["investigator_id"] == "reuse_opportunity")
        return {"summary": "Scoped sharing proposal.", "conclusions": [{"statement": "Extract immediately; all callers are compatible.",
            "finding_refs": [ref], "evidence_refs": context["findings"][ref]["evidence_refs"],
            "limitations": [f"Original limitation {i}" for i in range(12)]}]}

    result = execute(repo, [conclude], make=factory([], mutate=conditional))
    assert result.status == "completed"
    assert "Extract immediately" not in result.conclusions[0].statement
    assert "all callers are compatible" not in result.conclusions[0].statement
    assert "parsing helper only" in result.conclusions[0].statement
    assert all(condition in "\n".join(result.conclusions[0].limitations) for condition in conditions)
    assert ReusabilityAssessment.model_validate_json(result.model_dump_json()) == result
    record = SimpleNamespace(result=result, assignment=SimpleNamespace(invocation_id="coordinator", investigator_id="reusability", gap_ids=[]),
        status="completed", coverage_issues=[], warnings=[])
    findings, evidence = assessment_indexes([record])
    context = synthesis_context({"assessment_id": "audit", "scope": SimpleNamespace(model_dump=dict)},
        SimpleNamespace(objective="Maintainability", targets=[]), [record], findings, evidence, {})
    contribution = next(c for f in context["findings"].values() for c in f["contributions"] if c["investigator_id"] == "reuse_opportunity")
    assert contribution["conditions"] == conditions
    assert contribution["sharing_boundary"] == "A parsing helper only; caller policy remains separate."
    assert contribution["unknowns"] == ["Caller compatibility is unread."]
    from server.agents.maintainability.manager.synthesis import qualified_summary

    summary = qualified_summary("Extract immediately: caller compatibility is guaranteed.", findings)
    assert "Extract immediately" not in summary
    assert "A parsing helper only" in summary
    assert all(condition in summary for condition in conditions)
    assert contribution["recommendation"] == result.invocations[1].result.findings[0].recommendation
