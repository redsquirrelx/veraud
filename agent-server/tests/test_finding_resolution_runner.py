"""Read audit JSON through Python without dumping large fixture contents."""

import importlib.util
import json
from pathlib import Path

import pytest

from server.agents.finding_resolution import (
    FindingInvestigation,
    FindingVerificationResult,
    VerificationPlan,
)
from server.contracts.audit import Consumption
from server.runtimes.repository.tools import RepositoryToolResponse


@pytest.fixture
def runner(monkeypatch):
    directory = Path(__file__).parents[1] / "src/test-agents"
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location("resolution_runner", directory / "run_finding_resolution.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_fixture_loads_all_original_findings_without_changes(runner):
    raw = runner.DEFAULT_FINDINGS.read_bytes()
    originals = json.loads(raw)["findings"]
    findings = runner.load_findings(runner.DEFAULT_FINDINGS)
    assert len(findings) == len(originals) == 3
    assert [finding.model_dump(mode="json") for finding in findings] == originals
    request = runner.FindingResolutionRequest(repository_path=str(runner.DEFAULT_REPOSITORY), findings=findings)
    assert [finding.model_dump(mode="json") for finding in request.findings] == originals
    assert runner.DEFAULT_FINDINGS.read_bytes() == raw
    assert runner.DEFAULT_REPOSITORY.is_dir()


def test_accepts_plain_findings_list_and_utf8_bom(runner, tmp_path):
    path = tmp_path / "findings.json"
    path.write_text("[]", encoding="utf-8-sig")
    assert runner.load_findings(path) == []


def test_readable_plan_shows_checks_criteria_and_pending_findings(runner):
    findings = runner.load_findings(runner.DEFAULT_FINDINGS)
    request = runner.FindingResolutionRequest(repository_path=str(runner.DEFAULT_REPOSITORY), findings=findings)
    plan = VerificationPlan(finding_id=findings[0].id, checks=[{
        "question": "Does the original dependency still exist?", "evidence_needed": ["Current source and callers"],
        "queries": [{"id": "read", "name": "get_source_excerpt", "arguments": {"path": "service.py"}}],
        "persists_if": "The same unsupported access is present.",
        "resolved_if": "Current consumers use the supported interface.",
    }], limitations=["No source has been read yet."])
    state = {"plans": [plan], "termination_reason": "model_call_limit", "limitations": ["Budget exhausted."],
        "consumption": Consumption(model_calls=1, accounted_tokens=200)}
    before = request.model_dump()
    text = runner.render_verification_plan(request, state)
    assert "PLAN DE VERIFICACION DE HALLAZGOS" in text
    assert "Planes generados: 1" in text and "Limite de llamadas alcanzado" in text
    assert findings[0].title in text and findings[0].description in text
    assert "Comprobacion 1:" in text and "get_source_excerpt(path='service.py')" in text
    assert "Persiste si [persists_if]:" in text and "Se considera resuelto si [resolved_if]:" in text
    assert "No source has been read yet." in text and "Budget exhausted." in text
    assert text.count("Sin plan generado") == len(findings) - 1
    assert "consultas NO se han ejecutado" in text and "Tokens contabilizados: 200" in text
    assert request.model_dump() == before


def test_readable_empty_input_is_not_reported_as_resolution(runner):
    request = runner.FindingResolutionRequest(repository_path="repository", findings=[])
    text = runner.render_verification_plan(request, {"plans": [], "termination_reason": "no_findings",
        "limitations": [], "consumption": Consumption()})
    assert "Sin hallazgos recibidos" in text and "No hay hallazgos que planificar" in text
    assert "no hay decisiones de resolucion" in text and "Llamadas LLM: 0" in text


def test_readable_investigation_shows_collected_source_not_a_resolution(runner):
    original = runner.load_findings(runner.DEFAULT_FINDINGS)[0]
    request = runner.FindingResolutionRequest(repository_path=str(runner.DEFAULT_REPOSITORY), findings=[original])
    plan = VerificationPlan(finding_id=original.id, checks=[{
        "question": "Inspect current code", "evidence_needed": ["Implementation"],
        "queries": [{"id": "read", "name": "get_source_excerpt", "arguments": {"path": original.components[0]}}],
        "persists_if": "Unsupported access remains.", "resolved_if": "Supported access is verified.",
    }])
    source = original.evidence[0].model_copy(update={"id": "current-source", "tool_call_id": "current-call"})
    record = FindingInvestigation(finding_id=original.id, finding=original, plan=plan,
        summary="Current implementation collected.", stop_reason="evidence_collected", evidence=[source],
        tool_results=[RepositoryToolResponse(tool_call_id="current-call", tool_name="get_source_excerpt",
            snapshot_hash=source.snapshot_hash, status="ok", data={"content": "def current(): return 1"})],
        history=[], limitations=[], consumption=Consumption(model_calls=3, tool_calls=1, accounted_tokens=600))
    assert record.model_dump(mode="json")["finding"] == original.model_dump(mode="json")
    text = runner.render_verification_plan(request, {"plans": [plan], "investigations": [record],
        "termination_reason": "investigations_completed", "limitations": [], "consumption": record.consumption})
    assert "INVESTIGACION Y EVIDENCIAS RECOPILADAS" in text and "def current(): return 1" not in text
    assert "current-source" in text and "current-call" in text and "600 tokens" in text
    assert "no hay decisiones de resolucion" in text and "consultas NO se han ejecutado" not in text


@pytest.mark.parametrize("phase", ["planificacion", "investigacion"])
def test_readable_errors_identify_the_failed_phase(runner, phase):
    original = runner.load_findings(runner.DEFAULT_FINDINGS)[0]
    request = runner.FindingResolutionRequest(repository_path=str(runner.DEFAULT_REPOSITORY), findings=[original])
    state = {"plans": [], "investigations": [], "finding": original,
        "termination_reason": "model_or_schema_error", "limitations": ["Response validation failed."], "consumption": Consumption()}
    if phase == "investigacion":
        plan = VerificationPlan(finding_id=original.id, checks=[{
            "question": "Inspect current code", "evidence_needed": ["Implementation"],
            "queries": [{"id": "read", "name": "get_source_excerpt", "arguments": {"path": original.components[0]}}],
            "persists_if": "Unsupported access remains.", "resolved_if": "Supported access is verified.",
        }])
        state.update(plans=[plan], finding=None, termination_reason="investigations_completed_with_errors",
            investigations=[FindingInvestigation(finding_id=original.id, finding=original, plan=plan,
                summary="Invalid investigation response.", stop_reason="model_or_schema_error", evidence=[], tool_results=[],
                history=[], limitations=["Response validation failed."], consumption=Consumption())])
    text = runner.render_verification_plan(request, state)
    assert f"Error de {phase}:" in text and "Response validation failed." in text
    other = "investigacion" if phase == "planificacion" else "planificacion"
    assert f"Error de {other}:" not in text
    if phase == "investigacion":
        assert "Hallazgos procesados con errores de investigacion" in text


def test_readable_output_includes_structured_diagnostics_and_global_summary(runner):
    original = runner.load_findings(runner.DEFAULT_FINDINGS)[0]
    request = runner.FindingResolutionRequest(repository_path=str(runner.DEFAULT_REPOSITORY), findings=[original])
    diagnostic = {"finding_id": original.id, "node": "plan_verification", "attempt": 1,
        "category": "tool_arguments", "error_type": "ValidationError", "scope": "finding",
        "issues": [{"field": "checks.0.queries.0.arguments.start_line", "rule": "greater_than_equal", "constraints": {"ge": 1}}]}
    state = {"plans": [], "investigations": [], "finding": original, "termination_reason": "model_or_schema_error",
        "limitations": ["plan_verification: response_schema attempt 1/1: ValueError (response unavailable or invalid)"],
        "consumption": Consumption()}
    capture = runner.DiagnosticCapture()
    record = runner.logging.makeLogRecord({"finding_resolution_diagnostic": diagnostic})
    capture.emit(record)
    text = runner.render_verification_plan(request, state, capture.diagnostics)
    assert "checks.0.queries.0.arguments.start_line" in text and "greater_than_equal" in text and "'ge': 1" in text
    assert "RESUMEN DE EJECUCION" in text and "Interrupcion global: model_or_schema_error" in text
    assert "response unavailable or invalid" not in text


def test_readable_output_displays_individual_evaluation(runner):
    original = runner.load_findings(runner.DEFAULT_FINDINGS)[0]
    request = runner.FindingResolutionRequest(repository_path=str(runner.DEFAULT_REPOSITORY), findings=[original])
    result = FindingVerificationResult(finding_id=original.id, status="inconclusive",
        reason="Evaluation could not proceed within the available token budget.", evidence_ids=[])
    text = runner.render_verification_plan(request, {"plans": [], "investigations": [], "results": [result],
        "finding": original, "termination_reason": "token_limit", "limitations": [], "consumption": Consumption()})
    assert "Evaluacion: inconclusive" in text and result.reason in text and "Inconclusive: 1" in text
    assert "evaluate_resolution no implementado" not in text and "Interrupcion global: token_limit" in text
