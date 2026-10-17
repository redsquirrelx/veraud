r"""Desde agent-server (PowerShell):

    uv run pytest src/test-agents/test_modularity_e2e.py -v -s

Offline por defecto: solo se simula el proveedor, no los investigadores.
Prueba opcional con proveedor real (genera costes):

    $env:MODULARITY_E2E_LIVE = "1"
    uv run pytest src/test-agents/test_modularity_e2e.py -q -k live -s

Usa LLM_API_KEY del .env y config/dev-agents.yaml (entrada dummy por defecto;
MODULARITY_E2E_AGENT_CONFIG selecciona otra). LangSmith opcional con su clave.
No exige textos idénticos, hallazgos concretos ni dos rondas al proveedor real.
"""

import asyncio
import hashlib
import json
import os
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from modularity_e2e_reporting import (
    AssessmentProgress,
    begin_assessment,
    emit,
    report_assessment,
)
from test_architecture_boundary import (
    PLAN,
    NativeStructuredModel,
    evaluation,
    fingerprints,
    review,
    toolset,
)

from server.agents.maintainability.modularity.coordinator import (
    ModularityAgent,
    ModularityConfig,
    ModularityRequest,
)
from server.agents.maintainability.modularity.coordinator.registry import INVESTIGATORS
from server.app.tracing_port import LangSmithTracingBackend
from server.runtimes.investigation.schemas import (
    Criterion,
    InvestigationConfig,
    ProviderRateLimits,
)

FOLLOW_UP = "Follow-up: does report formatting change independently of persistence?"


@pytest.fixture
def audit_repository(tmp_path):
    root = tmp_path / "checkout"
    (root / "domain").mkdir(parents=True)
    (root / "storage").mkdir()
    (root / "domain" / "service.py").write_text(
        "from storage.db import save\n\n"
        "def execute(order):\n    save(order)\n    return f'Report: {order}'\n", encoding="utf-8")
    (root / "storage" / "db.py").write_text(
        "def save(order):\n    return {'stored': order}\n", encoding="utf-8")
    (root / "domain" / "report.py").write_text(
        "REPORT_VERSION = 2\n\ndef render(order):\n    return f'v{REPORT_VERSION}: {order}'\n", encoding="utf-8")
    return root


def request():
    return ModularityRequest(
        objective="Assess domain/storage modularity and separation of persistence and report formatting.",
        targets=["domain", "storage"],
        criteria=[Criterion(id="domain-rule", description="Domain must not import storage.",
                            origin="explicit", provenance="Declared fixture architecture rule")])


def limits(**updates):
    # Offline scenarios exercise orchestration, not provider quotas; dedicated tests
    # exercise RPM/TPM with a virtual clock instead of sleeping real minutes.
    return ModularityConfig(provider_rate_limits=ProviderRateLimits(
        requests_per_minute=None, tokens_per_minute=None), invocation_limits=InvestigationConfig(
        max_model_calls=8, max_tool_calls=8, max_total_tokens=60_000), **updates)


def repository_tools(root):
    return toolset(root, max_model_calls=96, max_tool_calls=96)


class ProviderScenario(NativeStructuredModel):
    """Stateless per-request provider responses; safe for concurrent real graphs.

    Uses the same native structured-output envelope as the existing adapter tests.
    It never invokes investigators, builds results, executes tools or changes state.
    """

    def __init__(self, *, follow_up=False, unresolved=False, fail_dependency=False):
        super().__init__([])
        self.follow_up = follow_up
        self.unresolved = unresolved
        self.fail_dependency = fail_dependency
        self.synthesis_calls = 0

    @staticmethod
    def investigator(context):
        objective = context["objective"]
        if objective == FOLLOW_UP:
            return "responsibility"
        for key, spec in INVESTIGATORS.items():
            if spec.capability.capability in objective:
                return key
        raise AssertionError("Provider received an unknown investigation objective")

    async def ainvoke(self, messages, **kwargs):
        self.history.append(messages)
        context = json.loads(messages[1].content)
        if "Now execute synthesize_findings" in messages[-1].content:
            self.synthesis_calls += 1
            value = self.synthesize(context)
        else:
            key = self.investigator(context)
            if self.fail_dependency and key == "dependency_impact":
                raise RuntimeError("Simulated provider outage")
            instruction = next((m.content for m in reversed(messages)
                if isinstance(m.content, str) and m.content.startswith("Now execute ")), "")
            if "Now execute plan_investigation" in instruction:
                value = PLAN if key == "architecture_boundary" else {
                    "objectives": [context["objective"]], "components": context.get("inventory", {}).get("directories", []),
                    "hypotheses": []}
            elif "Now execute evaluate_evidence" in instruction:
                if key == "architecture_boundary":
                    value = evaluation(messages)
                else:
                    value = {"sufficient": True, "hypotheses": [], "candidates": [], "missing_information": [],
                        "component_assessments" if key == "responsibility" else "dependency_assessments": []}
                    if context["objective"] == FOLLOW_UP:
                        refs = [e for e in context["evidence"] if e["path"] == "domain/report.py"]
                        value["component_assessments"] = [{
                            "id": "report-component", "component_id": refs[0]["file_id"],
                            "responsibilities": [{"id": "report-rendering", "description": "Render a versioned report",
                                "behaviors": ["render returns the report version and order as text"],
                                "possible_change_reasons": ["Report version and presentation requirements change"],
                                "supporting_evidence_ids": [e["id"] for e in refs]}],
                            "potentially_incompatible": [], "cohesion": "coherent",
                            "architectural_justification": "Versioned rendering is a separate report policy, not persistence.",
                            "evidence_ids": [e["id"] for e in refs],
                        }]
            elif "Now execute review_findings" in instruction:
                value = review()(messages) if key == "architecture_boundary" else {"findings": [], "limitations": []}
            elif any(isinstance(m, ToolMessage) for m in messages):
                return AIMessage(content="Source inspected; ready to evaluate.")
            else:
                paths = ["domain/report.py"] if context["objective"] == FOLLOW_UP else ["domain/service.py", "storage/db.py"]
                return AIMessage(content="", tool_calls=[{
                    "name": "get_source_excerpt", "args": {"path": path, "start_line": 1,
                        "end_line": {"domain/service.py": 5, "storage/db.py": 2, "domain/report.py": 4}[path]},
                    "id": f"source-{key}-{i}",
                } for i, path in enumerate(paths)])
        return AIMessage(content=json.dumps(value), usage_metadata={
            "input_tokens": 100, "output_tokens": 100, "total_tokens": 200})

    def synthesize(self, context):
        if not self.follow_up:
            return {"summary": "Retain the source-backed architectural boundary concern."}
        if self.synthesis_calls == 1:
            refs = [ref for ref, evidence in context["evidence"].items()
                    if evidence["path"] == "domain/service.py"][:1]
            return {"summary": "A targeted responsibility question remains.", "gaps": [{
                "kind": "missing_evidence", "investigator_id": "responsibility", "question": FOLLOW_UP,
                "targets": ["domain/report.py"], "evidence_refs": refs,
            }]}
        if self.unresolved:
            return {"summary": "Targeted evidence remains inconclusive; keep the material gap open."}
        invocation = next(i for i in context["invocations"] if i["gap_ids"])
        gap = next(g for g in context["gaps"] if g["id"] in invocation["gap_ids"])
        refs = [ref for ref, evidence in context["evidence"].items()
                if ref.startswith(invocation["invocation_id"] + "/") and evidence["path"] == "domain/report.py"]
        return {"summary": "Follow-up inspected report-specific policy; preserve the boundary finding.",
            "resolutions": [{"gap_id": gap["id"], "invocation_id": invocation["invocation_id"],
                "evidence_refs": refs, "explanation": "The report module exposes a separate report-version change reason."}]}


def assert_invariants(assessment, tools, root, before, config):
    assert fingerprints(root) == before
    assert assessment.snapshot_hash == tools.context.input.snapshot_hash
    assert 1 <= assessment.rounds_completed <= config.max_rounds
    assert 3 <= len(assessment.invocations) <= config.max_invocations
    assert {r.assignment.investigator_id for r in assessment.invocations if r.assignment.round == 1} == set(INVESTIGATORS)
    identifiers = {r.assignment.invocation_id for r in assessment.invocations}
    assert len(identifiers) == len(assessment.invocations)
    assert assessment.node_transitions.count("finalize_assessment") == 1
    files = {f.id: f for f in tools.accessible_snapshot.files}
    for record in assessment.invocations:
        assert record.duration_seconds >= 0
        assert record.consumption.model_calls >= 0
        for evidence in record.evidence:
            assert evidence.snapshot_hash == assessment.snapshot_hash
            assert evidence.commit == assessment.commit
            assert files[evidence.file_id].path == evidence.path
            assert hashlib.sha256((root / evidence.path).read_bytes()).hexdigest() == evidence.content_hash
            if evidence.kind == "source":
                assert 1 <= evidence.start_line <= evidence.end_line <= files[evidence.file_id].line_count
        if record.assignment.round > 1:
            assert record.assignment.gap_ids
    for finding in assessment.consolidated_findings:
        assert finding.evidence
        for contribution in finding.contributions:
            assert contribution.invocation_id in identifiers
            assert contribution.finding.validation_status == "accepted"
            assert contribution.finding.evidence
    if assessment.material_gaps:
        assert assessment.status != "completed"
    if assessment.status == "completed":
        assert not assessment.material_gaps
        assert {r.assignment.investigator_id for r in assessment.invocations if r.status == "completed"} == set(INVESTIGATORS)


def offline_run(root, **scenario):
    before = fingerprints(root)
    tools, config, tracing = repository_tools(root), limits(), AssessmentProgress()
    model = ProviderScenario(**scenario)
    title = ("Fallo del proveedor; conservacion de hallazgos" if scenario.get("fail_dependency") else
             "Seguimiento sin resolver; corte por limites" if scenario.get("unresolved") else
             "Seguimiento dirigido de dos rondas" if scenario.get("follow_up") else "Evaluacion suficiente en una ronda")
    begin_assessment(title, "SIMULADO (sin llamadas externas)", root)
    # Default registry dispatch: no investigator_factory and no investigator doubles.
    assessment = asyncio.run(ModularityAgent(model, config, tracing_backend=tracing).run(tools, request()))
    report_assessment(assessment)
    assert_invariants(assessment, tools, root, before, config)
    assert {r["invocation_id"] for r in tracing.records} == {r.assignment.invocation_id for r in assessment.invocations}
    emit("  Verificado: evidencia, limites, trazas y repositorio sin modificaciones.\n")
    return assessment, model


def test_e2e_one_round_real_investigators(audit_repository):
    assessment, model = offline_run(audit_repository)
    assert assessment.status == "completed"
    assert assessment.rounds_completed == 1 and len(assessment.invocations) == 3
    assert "plan_targeted_follow_up" not in assessment.node_transitions
    assert all(r.status == "completed" and r.evidence and r.result.tool_calls == 2 for r in assessment.invocations)
    assert len(assessment.consolidated_findings) == 1
    finding = assessment.consolidated_findings[0]
    assert finding.contributions[0].investigator_id == "architecture_boundary"
    assert any(e.path == "domain/service.py" and e.start_line == 1 for e in finding.evidence)
    assert model.synthesis_calls == 1


@pytest.mark.parametrize("responsibility_limited", [False, True])
def test_manager_collection_reuses_real_child_publications_and_tool_measurements(audit_repository, responsibility_limited):
    from server.agents.maintainability.manager import (
        MaintainabilityConfig,
        MaintainabilityManagerAgent,
        MaintainabilityRequest,
    )
    from server.app.tracing_port import NoOpTracingBackend
    from server.blackboard.identity import AuditIdentity
    from server.blackboard.impls.memory import MemoryBlackboard

    originals, writes, coordinator_calls = {}, {}, []

    class Board(MemoryBlackboard):
        def publish_evidence(self, record):
            writes[record.id] = writes.get(record.id, 0) + 1
            originals.setdefault(record.id, record.model_copy(deep=True))
            return super().publish_evidence(record)

    class Scenario(ProviderScenario):
        async def ainvoke(self, messages, **kwargs):
            answer = await super().ainvoke(messages, **kwargs)
            if responsibility_limited and "Now execute evaluate_evidence" in messages[-1].content:
                context = json.loads(messages[1].content)
                if self.investigator(context) == "responsibility":
                    return AIMessage(content=json.dumps({"sufficient": False, "hypotheses": [], "candidates": [],
                        "missing_information": ["More responsibility evidence required"], "component_assessments": []}),
                        usage_metadata={"input_tokens": 100, "output_tokens": 100, "total_tokens": 200})
            return answer

    configured = limits(max_rounds=1)
    configured = configured.model_copy(update={"invocation_limits": configured.invocation_limits.model_copy(update={"max_iterations": 10})})

    def coordinator_factory(key, model, child_limits):
        coordinator_calls.append(key)
        # Real default investigator registry and lifecycle; only provider responses are simulated.
        return ModularityAgent(Scenario(), child_limits, tracing_backend=NoOpTracingBackend())

    board = Board()
    manager = MaintainabilityManagerAgent(NativeStructuredModel([{"summary": "Retained original child work."}]),
        MaintainabilityConfig(max_rounds=1, invocation_limits=configured,
            provider_rate_limits={"requests_per_minute": None, "tokens_per_minute": None}),
        coordinator_factory=coordinator_factory, tracing_backend=NoOpTracingBackend(), blackboard=board,
        audit_identity=AuditIdentity(run_id="measured-audit", invocation_id="manager"))
    report = asyncio.run(manager.run(repository_tools(audit_repository), MaintainabilityRequest(dimensions=["modularity"],
        targets=["domain", "storage"], criteria=request().criteria)))
    assert coordinator_calls == ["modularity"]
    assessment = report.assessments[0]
    assert assessment.result is not None and assessment.failure is None
    responsibility = next(r for r in assessment.result.invocations if r.assignment.investigator_id == "responsibility")
    assert responsibility.failure is None and responsibility.result is not None
    if responsibility_limited:
        assert report.status == assessment.status == responsibility.status == "partial"
        assert responsibility.result.termination_reason == "model_call_limit"
    else:
        assert report.status == "complete" and responsibility.status == "completed"
    assert assessment.result.consolidated_findings  # Accepted boundary finding survives partial responsibility coverage.
    evidence = board.query_evidence("measured-audit")
    assert evidence and all(writes[e.id] == 1 and e == originals[e.id] for e in evidence)
    assert all(e.details["measurement"]["call_id"] == e.tool_call_id for e in evidence)
    assert all(e.details["tool_name"] == "get_source_excerpt" for e in evidence)
    assert len(board.query_assessments("measured-audit")) == 2


def test_e2e_two_rounds_real_investigators(audit_repository):
    assessment, model = offline_run(audit_repository, follow_up=True)
    assert assessment.status == "completed"
    assert assessment.rounds_completed == 2 and len(assessment.invocations) == 4
    follow_up = assessment.invocations[-1]
    assert follow_up.assignment.investigator_id == "responsibility" and follow_up.assignment.round == 2
    assert follow_up.status == "completed" and follow_up.result.tool_calls == 1
    assert follow_up.result.components_investigated[0].validation_status == "source_backed"
    assert {e.path for e in follow_up.evidence} == {"domain/report.py"}
    assert set(follow_up.assignment.gap_ids) <= set(assessment.resolved_gap_ids)
    assert assessment.node_transitions.count("delegate_investigations") == 2
    assert assessment.node_transitions.count("plan_targeted_follow_up") == 1
    assert model.synthesis_calls == 2
    assert assessment.consolidated_findings  # initial supported finding survives follow-up


def test_e2e_unresolved_followup_stops_at_round_limit(audit_repository):
    assessment, _ = offline_run(audit_repository, follow_up=True, unresolved=True)
    assert assessment.status == "partial" and assessment.termination_reason == "round_limit"
    assert assessment.rounds_completed == 2 and len(assessment.invocations) == 4
    assert assessment.material_gaps and assessment.consolidated_findings


def test_e2e_provider_failure_preserves_successful_graphs(audit_repository):
    assessment, _ = offline_run(audit_repository, fail_dependency=True)
    assert assessment.status == "partial"
    assert any(g.kind == "essential_failure" and g.investigator_id == "dependency_impact" for g in assessment.material_gaps)
    assert assessment.consolidated_findings
    assert all(r.result.termination_reason == "model_or_schema_error" for r in assessment.invocations
               if r.assignment.investigator_id == "dependency_impact")


def test_e2e_progress_matches_actual_assessment(audit_repository, monkeypatch):
    import modularity_e2e_reporting

    lines = []
    monkeypatch.setattr(modularity_e2e_reporting, "emit", lines.append)
    monkeypatch.setitem(offline_run.__globals__, "emit", lines.append)
    assessment, _ = offline_run(audit_repository, follow_up=True, unresolved=True)
    output = "\n".join(lines)
    assert "Proveedor: SIMULADO" in output
    assert "Estado de la evaluacion: partial" in output
    assert "Finalizacion: round_limit" in output
    assert "Ruta ejecutada: reinvestigate" in output
    assert f"Lagunas materiales pendientes: {len(assessment.material_gaps)}" in output
    for record in assessment.invocations:
        agent = INVESTIGATORS[record.assignment.investigator_id].capability.agent_name
        assert f"{agent} [{record.assignment.invocation_id[:8]}] -> {record.status}" in output
        assert f"{record.consumption.accounted_tokens} tokens contabilizados" in output
    assert output.count("-> iniciado") == len(assessment.invocations)
    assert output.count("-> resultado recibido") == len(assessment.invocations)
    assert "Resultado del test: lo determina pytest" in output


@pytest.mark.skipif(os.getenv("MODULARITY_E2E_LIVE") != "1", reason="Explicit opt-in required for paid provider calls")
def test_e2e_live_provider(audit_repository):
    from run_architecture_boundary import load_test_model

    from server.runtimes.repository.model_runtime import close_model_clients

    async def execute():
        model, settings = load_test_model(os.getenv("MODULARITY_E2E_AGENT_CONFIG", "dummy"))
        config = ModularityConfig(max_output_tokens=min(4000, settings.max_tokens), max_parallel=3,
            investigation_start_interval_seconds=1,
            provider_request_interval_seconds=0.5, provider_retry_backoff_seconds=5,
            invocation_limits=InvestigationConfig(max_model_calls=12, max_total_tokens=60_000,
                max_tool_calls=16, timeout_seconds=180,
                provider_request_interval_seconds=0.5, provider_retry_backoff_seconds=5))
        before = fingerprints(audit_repository)
        tools = repository_tools(audit_repository)
        try:
            begin_assessment("Smoke test con proveedor real", f"REAL ({settings.provider}/{settings.name})", audit_repository)
            assessment = await ModularityAgent(model, config,
                tracing_backend=AssessmentProgress(LangSmithTracingBackend())).run(tools, request())
            report_assessment(assessment)
            assert_invariants(assessment, tools, audit_repository, before, config)
            assert_live_success(assessment)
            emit("  Verificado: evidencia, limites, repositorio sin modificaciones y evaluacion completa de al menos un investigador.\n")
        finally:
            await close_model_clients(SimpleNamespace(llm=model))
    asyncio.run(execute())


def assert_live_success(assessment):
    """Tool activity alone is not a successful semantic assessment smoke test."""
    assert any(r.status == "completed" and r.result and r.result.plan and r.evidence
               for r in assessment.invocations), "Ningun investigador completo la evaluacion; revisar diagnosticos del proveedor."
    assert not any(g.kind == "synthesis_failure" for g in assessment.material_gaps), "La sintesis fallo; revisar diagnosticos del proveedor."
