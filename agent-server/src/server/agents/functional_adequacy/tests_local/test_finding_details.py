"""Regression coverage for functional findings consumed by the audit inspector."""

import asyncio
from types import SimpleNamespace

import pytest

from server.agents.functional_adequacy.audit import _publish_exploratory
from server.agents.functional_adequacy.exploratory import evaluate_capabilities
from server.agents.functional_adequacy.finding_details import (
    documentary_references,
    exploratory_details,
    requirement_details,
)
from server.agents.functional_adequacy.repository_adapter import prepare_snapshot_input
from server.agents.functional_adequacy.schemas import (
    DocumentReference,
    FunctionalCapability,
    RequirementResult,
)
from server.blackboard.identity import AuditIdentity
from server.reporting.knowledge import report_findings
from server.services.repository_analysis import RepositoryAnalysisService


def test_published_findings_populate_inspector_without_changing_classification(tmp_path):
    (tmp_path / "service.py").write_text(
        'def get_product():\n    """REQ-001: consultar producto."""\n    pass\n',
        encoding="utf-8",
    )
    (tmp_path / "requirements.md").write_text(
        "# Requisitos\n\n## REQ-001: Consultar producto\nDebe devolver el producto solicitado.\n",
        encoding="utf-8",
    )
    snapshot = asyncio.run(RepositoryAnalysisService().analyze(str(tmp_path)))
    prepared = prepare_snapshot_input(snapshot, [])
    context = prepared.repository_context
    findings = evaluate_capabilities(context.capabilities, context.document_references)
    output = SimpleNamespace(capabilities=context.capabilities, findings=findings, limitations=[],
        model_dump=lambda **kwargs: {"audit_mode": "exploratory"})
    published, evidence, assessments = [], [], []
    board = SimpleNamespace(publish_finding=published.append, publish_evidence=evidence.append,
        publish_assessment=assessments.append)
    _publish_exploratory(snapshot, prepared, output, board, AuditIdentity(),
        SimpleNamespace(used=0, estimated=0))

    reports, _, _ = report_findings(published, evidence, assessments)
    report = next(item for item in reports if item.criterion.id == "correccion")
    assert "get_product" in report.impact
    assert "no demuestra un defecto" in report.impact
    assert "modularidad" not in report.impact
    assert "Completar la implementación esqueleto" in report.recommendation
    assert report.verification_status == "inconclusive"
    assert report.evidence_ids
    refs = report.technical_details["documentary_references"]
    assert refs == [{"subject": "REQ-001", "statement": "Consultar producto (Definición)",
        "constraint": "unspecified", "certainty": "unknown", "category": "definition", "quotes": [{
            "path": "requirements.md", "start_line": 3, "end_line": 4,
            "quote": "## REQ-001: Consultar producto\nDebe devolver el producto solicitado."}]}]
    assert report.technical_details["functional_finding"]["classification"] == "no_verificado"


def test_document_projection_rejects_missing_or_invalid_ranges_and_deduplicates():
    source = SimpleNamespace(language="markdown", status="processed", content="## REQ-001\nTexto real.")
    ref = DocumentReference(requirement_id="REQ-001", document_path="requirements.md", start_line=1, end_line=2)
    references = [ref, ref, ref.model_copy(update={"document_path": "missing.md"}),
        ref.model_copy(update={"end_line": 3}), ref.model_copy(update={"end_line": 0})]
    projected = documentary_references(references, {"requirements.md": source})
    assert len(projected) == 1
    assert projected[0]["quotes"][0]["quote"] == source.content
    assert documentary_references([], {"requirements.md": source}) == []


def test_missing_evidence_recommends_verification_not_a_fabricated_fix():
    capability = FunctionalCapability(capability_id="missing", name="get_product", kind="function",
        description="Capacidad sin evidencia")
    result = evaluate_capabilities([capability])[0]
    impact, recommendation = exploratory_details(result, capability)
    assert "no_verificado" in impact
    assert "antes de concluir" in recommendation
    assert result.document_references == []


@pytest.mark.parametrize(("status", "expected"), [
    ("cumple", "no se propone una corrección"),
    ("no_cumple", "discrepancia"),
    ("evidencia_insuficiente", "antes de modificar código"),
])
def test_requirement_presentation_preserves_uncertainty(status, expected):
    result = RequirementResult(requirement_id="REQ-001", description="Consultar producto",
        status=status, justification="Evaluación limitada a la evidencia retenida.")
    impact, recommendation = requirement_details(result)
    assert "REQ-001" in impact and status in impact
    assert "no una prueba funcional ejecutada" in impact
    assert expected in recommendation
