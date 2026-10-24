r"""From agent-server:

    uv run pytest src/test-agents/test_reusability_e2e.py -v -s

Real default registry/coordinator/investigators/indexes/tools; only model I/O is simulated.
Optional paid model (YAML + .env + existing LangSmith):

    $env:REUSABILITY_E2E_LIVE = "1"
    uv run pytest src/test-agents/test_reusability_e2e.py -v -s -k live
"""

import asyncio
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from modularity_e2e_reporting import (
    AssessmentProgress,
    begin_assessment,
    emit,
    report_assessment,
)
from test_abstraction import evaluate as abstraction_evaluate
from test_abstraction import plan as abstraction_plan
from test_abstraction import reads as source_reads
from test_abstraction import review as abstraction_review
from test_architecture_boundary import fingerprints, toolset
from test_component_adaptability import evaluate as adaptability_evaluate
from test_component_adaptability import plan as adaptability_plan
from test_component_adaptability import review as adaptability_review
from test_reuse_opportunity import evaluation as reuse_evaluate
from test_reuse_opportunity import plan as reuse_plan
from test_reuse_opportunity import review as reuse_review

from server.agents.maintainability.reusability.coordinator import (
    ReusabilityAgent,
    ReusabilityAssessment,
    ReusabilityConfig,
    ReusabilityRequest,
)
from server.agents.maintainability.reusability.coordinator.registry import INVESTIGATORS
from server.app.tracing_port import LangSmithTracingBackend
from server.runtimes.investigation.schemas import InvestigationConfig

FOLLOW_UP = "Inspect the external construction seam and its effect on the scoped abstraction judgment."
TARGET = "Offline processing with a supplied backend, without changing the component source."
SEED = Path(__file__).parent / "fixtures" / "reusability"


@pytest.fixture
def audit_repository(tmp_path):
    root = tmp_path / "checkout"
    shutil.copytree(SEED, root)
    return root


def request():
    return ReusabilityRequest(targets=["policy.py"], target_context=TARGET)


def repository_tools(root):
    return toolset(root, max_model_calls=96, max_tool_calls=96, max_total_tokens=700_000,
        max_tokens_per_objective=700_000, max_retrieved_characters=600_000, max_elapsed_seconds=600)


def offline_config(**updates):
    # Runtime owns all scheduling/quotas. Only disable minute admission for fast
    # simulations; dedicated quota tests and the live case retain that coverage.
    return ReusabilityConfig(**({"max_rounds": 1, "max_total_tokens": 700_000,
        "provider_rate_limits": {"requests_per_minute": None, "tokens_per_minute": None},
        "invocation_limits": InvestigationConfig(max_model_calls=10, max_total_tokens=120_000,
            max_tool_calls=12, max_iterations=1)} | updates))


class SimulatedProvider:
    """One shared model adapter; no factory or fake investigator/tool implementation.

    Response selection is keyed by actual prompt/schema context, so independent
    invocations can interleave without relying on a global response iterator.
    """

    def __init__(self, root, scenario):
        self.root, self.scenario = root, scenario
        self.calls = []
        self.bound_tools = []

    def bind_tools(self, tools):
        self.bound_tools.extend(t.name for t in tools)
        return self

    def with_structured_output(self, schema, *, method, include_raw):
        assert method == "json_schema" and include_raw
        parent = self
        class Structured:
            async def ainvoke(self, messages, **kwargs):
                raw = await parent.respond(messages, schema)
                try:
                    parsed = schema.model_validate(json.loads(raw.content))
                except (ValueError, TypeError) as error:
                    return {"raw": raw, "parsed": None, "parsing_error": error}
                return {"raw": raw, "parsed": parsed, "parsing_error": None}
        return Structured()

    async def ainvoke(self, messages, **kwargs):
        return await self.respond(messages)

    async def respond(self, messages, schema=None):
        context = json.loads(messages[1].content)
        key = ("abstraction" if "abstraction_candidates" in context else
               "reuse_opportunity" if "candidate_groups" in context else
               "component_adaptability" if "selected_components" in context else "coordinator")
        name = schema.__name__ if schema else "inspect"
        self.calls.append((key, name, context.get("objective")))
        # Yield provider I/O without implementing dispatch timing in the tests.
        await asyncio.sleep(0)
        if self.scenario == "provider_failure" and key == "reuse_opportunity" and name == "ReusePlan":
            raise RuntimeError("Simulated unavailable provider, not an investigator stub")
        if key == "coordinator":
            value = self.synthesis(context)
        elif name in {"InvestigationPlan", "AbstractionPlan", "ReusePlan", "AdaptabilityPlan"}:
            value = {"abstraction": abstraction_plan, "reuse_opportunity": reuse_plan,
                      "component_adaptability": adaptability_plan}[key]()
            if callable(value):
                value = value(messages)
        elif name in {"inspect", "InspectionDecision"}:
            used_tools = any(isinstance(m, ToolMessage) for m in messages)
            if used_tools:
                value = {"action": "validate", "tool_requests": []} if key == "component_adaptability" else AIMessage(content="Validate inspected evidence")
            else:
                paths = ["policy.py", "orders.py", "reports.py"] if key == "abstraction" else ["policy.py", "backend.py", "consumer.py"]
                if key == "abstraction" and context["objective"] == FOLLOW_UP and self.scenario != "zero_progress":
                    paths.append("alternative.py")
                tool_message = source_reads(self.root, paths)
                if key == "component_adaptability":
                    value = {"action": "use_tools", "tool_requests": [{"name": c["name"], "arguments_json": json.dumps(c["args"])} for c in tool_message.tool_calls]}
                    if self.scenario == "tool_failure":
                        value["tool_requests"][1]["arguments_json"] = json.dumps({"path": "missing.py"})
                else:
                    value = tool_message
        elif name == "AbstractionEvaluation":
            value = abstraction_evaluate(messages)
        elif name == "ReuseEvaluation":
            value = reuse_evaluate(messages, classification="conditional", caller=False, mutate=self.reuse_comparison)
        elif name == "AdaptabilityEvaluation":
            value = adaptability_evaluate(messages, mutate=self.adaptability_comparison)
        elif name in {"Review", "AbstractionReview", "ReuseReview", "AdaptabilityReview"}:
            value = {"abstraction": lambda: abstraction_review("ABS-001")(messages),
                      "reuse_opportunity": lambda: reuse_review("REUSE-001")(messages),
                      "component_adaptability": lambda: adaptability_review("ADAPT-001")(messages)}[key]()
        else:
            raise AssertionError(f"Unexpected real graph schema: {key}/{name}")
        return value if isinstance(value, AIMessage) else AIMessage(content=json.dumps(value))

    @staticmethod
    def reuse_comparison(value):
        group = value["group_assessments"][0]
        group.update(shared_responsibility="Aggregate numeric input and delegate persistence to the same backend.",
            meaningful_differences="Method/input names differ; both bodies forward a sum to client.save.",
            variation_points="Input iterable and the externally supplied numeric values vary.",
            proposed_boundary="Consider one implementation only if both public names have compatible contracts.",
            risks_tradeoffs="Preserve public names and backend behavior; the fixture does not establish external runtime effects.",
            unknowns=["Independent public API compatibility and numeric contracts need confirmation."])
        for profile in group["implementations"]:
            profile.update(purpose="Sum input values and delegate to the same client.save method.",
                inputs_outputs="Numeric iterable to the backend's result payload.",
                preconditions_postconditions="Values must support sum; backend result is returned unchanged.",
                side_effects="Delegates to client.save; the inspected seed backend returns a dictionary, not a real database call.",
                dependencies="sum and the component's client.save member.", invariants="One sum before delegation.")

    @staticmethod
    def adaptability_comparison(value):
        assessment = value["constraint_assessments"][0]
        assessment["observed_facts"] = ["PricePolicy constructs a ProductionClient with a literal endpoint; both public methods use that member."]
        for usage in assessment["usage"]:
            usage["instantiation_configuration"] = "Consumer constructs PricePolicy without a backend parameter; attribute reassignment may be an alternative seam."

    def synthesis(self, context):
        followup = self.scenario in {"follow_up", "round_limit", "zero_progress"}
        if followup and len(context["invocations"]) == 3:
            refs = next(f["evidence_refs"] for f in context["findings"].values() if f["investigator_id"] == "abstraction")
            return {"summary": "Investigated all three perspectives; inspect one external construction seam.", "gaps": [{
                "kind": "missing_evidence", "investigator_id": "abstraction", "question": FOLLOW_UP,
                "targets": ["policy.py"], "evidence_refs": refs[:1]}]}
        if followup:
            invocation = context["invocations"][-1]
            gap = next(g for g in context["gaps"] if g["question"] == FOLLOW_UP)
            refs = [r for r, e in context["evidence"].items() if r.startswith(invocation["invocation_id"] + "/")
                    and e["kind"] == "source" and (e["path"] == "alternative.py" or self.scenario == "zero_progress")]
            return {"summary": "Targeted source inspected; retain qualified investigator judgments.", "resolutions": [{
                "gap_id": gap["id"], "invocation_id": invocation["invocation_id"], "evidence_refs": refs[:8],
                "explanation": "Follow-up supplied source for the external configuration seam."}]}
        accepted = [(r, f) for r, f in context["findings"].items() if f["validation_status"] == "accepted"]
        conclusions = [{"statement": "Retain this source-linked investigator observation within its stated conditions.",
            "finding_refs": [r], "evidence_refs": f["evidence_refs"][:3]} for r, f in accepted]
        return {"summary": "Scoped synthesis; useful reuse, conditional sharing and adaptation constraints remain distinct.", "conclusions": conclusions}


def assert_invariants(result, tools, root, before, config):
    assert fingerprints(root) == before
    assert result.snapshot_hash == tools.context.input.snapshot_hash
    assert result.consumption.model_calls <= config.max_model_calls
    assert result.consumption.tool_calls <= config.max_tool_calls
    assert result.consumption.accounted_tokens <= config.max_total_tokens
    assert len({r.assignment.invocation_id for r in result.invocations}) == len(result.invocations)
    assert len({r.assignment.request_id for r in result.invocations}) == len(result.invocations)
    assert {r.assignment.investigator_id for r in result.invocations[:3]} == set(INVESTIGATORS)
    for record in result.invocations:
        assert len({(e.id, e.tool_call_id) for e in record.evidence}) == len(record.evidence)
        if record.result:
            assert record.result.investigator == INVESTIGATORS[record.assignment.investigator_id].capability.agent_name
            assert record.result.plan is not None or record.result.status == "failed"
        for evidence in record.evidence:
            assert evidence.snapshot_hash == result.snapshot_hash
            assert (root / evidence.path).is_file()
            if evidence.kind == "source":
                assert 1 <= evidence.start_line <= evidence.end_line <= len((root / evidence.path).read_text(encoding="utf-8").splitlines())
    known = {f"{r.assignment.invocation_id}/{f.id}" for r in result.invocations if r.result for f in r.result.findings}
    assert all(c.reference in known for g in result.consolidated_findings for c in g.contributions)
    assert ReusabilityAssessment.model_validate_json(result.model_dump_json()) == result
    forbidden = {"decide_next_step", "plan_targeted_follow_up", "review_findings", "finalize_limited"}
    assert not forbidden.intersection(result.node_transitions)


def run_scenario(root, scenario, **config_updates):
    config = offline_config(**config_updates)
    model = SimulatedProvider(root, scenario)
    progress = AssessmentProgress(registry=INVESTIGATORS)
    agent = ReusabilityAgent(model, config, tracing_backend=progress)
    assert agent.factory is None  # Exercise default registry construction.
    tools = repository_tools(root)
    before = fingerprints(root)
    begin_assessment(scenario, "SIMULADO (solo respuestas LLM)", root, attribute="reusabilidad")
    result = asyncio.run(agent.run(tools, request()))
    report_assessment(result, registry=INVESTIGATORS, followup_path="synthesize_findings --yes--> delegate_investigations")
    assert_invariants(result, tools, root, before, config)
    assert len(progress.records) == sum(r.status != "skipped" for r in result.invocations)
    return result, model


def test_e2e_direct_finalization_all_real_investigators(audit_repository):
    result, model = run_scenario(audit_repository, "direct")
    assert result.status == "completed" and result.rounds_completed == 1
    assert all(r.status == "completed" and r.result.tool_calls > 0 for r in result.invocations)
    assert all(r.result.findings and any(f.validation_status == "accepted" for f in r.result.findings) for r in result.invocations)
    assert len(result.consolidated_findings) == len(result.conclusions) == 3
    assert {c[0] for c in model.calls} == {*INVESTIGATORS, "coordinator"}
    assert result.node_transitions == ["plan_assessment", "delegate_investigations", "collect_findings", "synthesize_findings", "finalize_assessment"]


def test_e2e_targeted_followup_actual_graphs(audit_repository):
    result, _ = run_scenario(audit_repository, "follow_up", max_rounds=2)
    assert result.status == "completed" and result.rounds_completed == 2
    assert len(result.invocations) == 4 and result.invocations[-1].assignment.investigator_id == "abstraction"
    assert result.invocations[-1].assignment.question == FOLLOW_UP
    assert any(e.path == "alternative.py" and e.kind == "source" for e in result.invocations[-1].evidence)
    assert [r.assignment.investigator_id for r in result.invocations].count("reuse_opportunity") == 1
    assert [r.assignment.investigator_id for r in result.invocations].count("component_adaptability") == 1
    assert [h.decision.route for h in result.synthesis_history] == ["yes", "no"]
    assert result.resolved_gap_ids


def test_e2e_provider_failure_retains_other_actual_results(audit_repository):
    result, _ = run_scenario(audit_repository, "provider_failure")
    assert result.status == "partial"
    assert sum(r.status == "completed" for r in result.invocations) == 2
    assert next(r for r in result.invocations if r.assignment.investigator_id == "reuse_opportunity").result.status == "failed"
    assert len(result.consolidated_findings) == 2 and result.material_gaps


def test_e2e_missing_source_reports_partial_without_accepting_claim(audit_repository):
    result, _ = run_scenario(audit_repository, "tool_failure")
    assert result.status == "partial"
    record = next(r for r in result.invocations if r.assignment.investigator_id == "component_adaptability")
    assert record.status == "partial" and record.result.tool_failures
    assert not any(f.validation_status == "accepted" for f in record.result.findings)
    assert len(result.consolidated_findings) == 2


def test_e2e_round_exhaustion_uses_normal_no_edge(audit_repository):
    result, _ = run_scenario(audit_repository, "round_limit")
    assert result.status == "partial" and result.termination_reason == "round_limit"
    assert result.rounds_completed == 1 and len(result.invocations) == 3
    assert result.continuation_decision.route == "no" and result.node_transitions[-1] == "finalize_assessment"


def test_e2e_token_envelope_prevents_unfunded_dispatch(audit_repository):
    result, model = run_scenario(audit_repository, "token_limit", max_total_tokens=1000, max_rounds=2)
    assert result.status == "failed" and result.termination_reason == "resource_limit"
    assert all(r.status == "skipped" and r.result is None for r in result.invocations)
    assert result.consumption.model_calls == result.consumption.tool_calls == 0
    assert not model.calls and not result.consolidated_findings


def test_e2e_zero_progress_does_not_repeat_initial_batch(audit_repository):
    result, _ = run_scenario(audit_repository, "zero_progress", max_rounds=3)
    assert result.status == "partial" and result.termination_reason == "zero_progress"
    assert result.rounds_completed == 2 and len(result.invocations) == 4
    assert not result.resolved_gap_ids


@pytest.mark.skipif(os.getenv("REUSABILITY_E2E_LIVE") != "1", reason="Explicit opt-in required for paid provider calls")
def test_e2e_live_provider(audit_repository):
    from run_architecture_boundary import load_test_model

    from server.runtimes.repository.model_runtime import close_model_clients

    async def live():
        model, settings = load_test_model(os.getenv("REUSABILITY_E2E_AGENT_CONFIG", "dummy"))
        config = ReusabilityConfig(max_rounds=1, max_output_tokens=min(4000, settings.max_tokens), timeout_seconds=300,
            investigation_start_interval_seconds=1, provider_request_interval_seconds=0.5, provider_retry_backoff_seconds=5,
            invocation_limits=InvestigationConfig(max_model_calls=12, max_total_tokens=80_000, max_tool_calls=16, timeout_seconds=240))
        tools, before = repository_tools(audit_repository), fingerprints(audit_repository)
        try:
            begin_assessment("Smoke con proveedor real", f"REAL ({settings.provider}/{settings.name})", audit_repository, attribute="reusabilidad")
            result = await ReusabilityAgent(model, config,
                tracing_backend=AssessmentProgress(LangSmithTracingBackend(), registry=INVESTIGATORS)).run(tools, request())
            report_assessment(result, registry=INVESTIGATORS, followup_path="synthesize_findings --yes--> delegate_investigations")
            assert_invariants(result, tools, audit_repository, before, config)
            assert len(result.invocations) == 3 and result.status in {"completed", "partial"}
            assert any(r.status == "completed" and r.result and r.result.plan and any(e.kind == "source" for e in r.evidence) for r in result.invocations)
            assert not any(g.kind == "synthesis_failure" for g in result.material_gaps)
            emit("  Smoke valido: al menos un investigador completo con evidencia; precision semantica requiere revision separada.")
        finally:
            await close_model_clients(SimpleNamespace(llm=model))
    asyncio.run(live())
