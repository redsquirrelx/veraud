"""Deterministic console presentation of the typed result; no source reads or model calls."""

import json

from server.agents.maintainability.analysability.code_comprehension.schemas import (
    CodeComprehensionResult,
)

SEVERITY = {"info": "informativa", "low": "baja", "medium": "media", "high": "alta", "critical": "crítica"}
HYPOTHESIS = {"confirmed": "Confirmada", "discarded": "Descartada", "pending": "Pendiente", "inconclusive": "Inconclusa"}


def format_result(result: CodeComprehensionResult, output: str = "readable") -> str:
    if output == "raw":
        return json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2)
    if output != "readable":
        raise ValueError(f"Unknown output format: {output}")

    findings = [f for f in result.findings if f.validation_status == "accepted"]
    complete = (result.termination_reason == "sufficient_evidence" and not result.missing_information
        and not result.inconclusive_investigations and result.hypotheses
        and all(h.status in {"confirmed", "discarded"} for h in result.hypotheses))
    if findings:
        conclusion = f"Se confirmaron {len(findings)} hallazgo(s) de comprensión en el alcance inspeccionado."
    elif complete and all(h.status == "discarded" for h in result.hypotheses):
        conclusion = "No se confirmaron problemas de comprensión en las hipótesis examinadas."
    elif complete:
        conclusion = ("No hay hallazgos aceptados. Algunas hipótesis se confirmaron, pero sus propuestas "
            "no superaron la revisión como hallazgos; consulte los motivos de rechazo.")
    else:
        conclusion = "No hay hallazgos aceptados; la evidencia disponible no permite concluir que el código sea claro."
    if not complete:
        conclusion += " La investigación quedó incompleta o con incertidumbre."

    lines = ["ANALIZABILIDAD · COMPRENSIÓN DEL CÓDIGO", "=" * 42,
        f"Repositorio: {result.repository_id}", f"Objetivo: {result.objective}",
        f"Versión: {result.commit or 'sin commit disponible'}", f"Snapshot: {result.snapshot_hash}",
        f"Cierre: {result.termination_reason}", "", "CONCLUSIÓN", conclusion,
        "Las conclusiones son locales: no certifican la claridad de todo el repositorio."]
    evidence = {r.id: r for r in result.evidence}
    for finding in findings:
        evidence.update({r.id: r for r in finding.evidence})
    aliases = {identifier: f"E{index}" for index, identifier in enumerate(evidence, 1)}

    def location(ref):
        span = f":{ref.start_line}" if ref.start_line is not None else " (metadatos)"
        if ref.end_line is not None and ref.end_line != ref.start_line:
            span += f"–{ref.end_line}"
        provenance = {"exact": "commit verificado", "line_endings_equivalent": "commit verificado (CRLF/LF)",
            "unverified": "atribución al commit no verificada"}.get(ref.commit_verification, "identificado por snapshot/hash")
        return f"[{aliases[ref.id]}] {ref.path}{span} — {provenance}"

    lines.extend(["", f"HALLAZGOS ACEPTADOS ({len(findings)})"])
    if not findings:
        lines.append("Ninguno.")
    for index, finding in enumerate(findings, 1):
        lines.extend([f"{index}. {finding.title}",
            f"   Severidad: {SEVERITY.get(finding.severity, finding.severity)} | Confianza: {finding.confidence:.0%}",
            f"   Problema: {finding.description}", f"   Sustento: {finding.justification}",
            f"   Impacto en la comprensión: {finding.modularity_impact}",
            f"   Recomendación: {finding.recommendation}", f"   Revisión crítica: {finding.review_rationale}",
            "   Evidencias:"])
        lines.extend(f"     {location(ref)}" for ref in finding.evidence)

    lines.extend(["", "COMPONENTES INVESTIGADOS"])
    if not result.comprehension_assessments:
        lines.append("No se completaron evaluaciones de componentes.")
    for assessment in result.comprehension_assessments:
        subject = assessment.path or assessment.component_id
        if assessment.symbol_name:
            subject += f" · {assessment.symbol_name}"
        conclusion_label = ("Sin conclusión validada" if assessment.validation_status != "source_backed" else
            {"clear": "Comportamiento inspeccionado claro", "problematic": "Dificultad observada; ver revisión de hallazgos",
                "inconclusive": "Inconcluso"}[assessment.conclusion])
        lines.extend([f"- {subject}: {conclusion_label}", f"  Pregunta: {assessment.comprehension_question}",
            f"  Responsabilidad: {assessment.responsibility}", f"  Comportamiento: {assessment.observed_behavior}",
            f"  Explicación alternativa: {assessment.alternative_explanation}",
            f"  Contraste de evidencia: {assessment.counterevidence_analysis}"])
        if assessment.difficulty:
            lines.append(f"  Dificultad propuesta (no implica aceptación): {assessment.difficulty}")
        lines.extend(f"  Límite local: {item}" for item in assessment.limitations)
        lines.extend(f"  Validación pendiente: {item}" for item in assessment.validation_issues)

    lines.extend(["", "HIPÓTESIS Y SU RESOLUCIÓN"])
    if not result.hypotheses:
        lines.append("No se produjo un plan de hipótesis válido.")
    for hypothesis in result.hypotheses:
        lines.extend([f"- {HYPOTHESIS[hypothesis.status]}: {hypothesis.question}",
            f"  Motivo: {hypothesis.rationale or 'Sin justificación registrada.'}"])

    if result.candidate_diagnostics:
        lines.extend(["", "PROPUESTAS NO ACEPTADAS (NO SON HALLAZGOS)"])
        for diagnostic in result.candidate_diagnostics:
            label = "Rechazada" if diagnostic.status == "rejected" else "Evidencia insuficiente"
            lines.append(f"- {diagnostic.candidate_id}: {label}")
            lines.extend(f"  {reason}" for reason in diagnostic.reasons)

    if evidence:
        lines.extend(["", "EVIDENCIAS INSPECCIONADAS", "Referencias a archivos y rangos; no se vuelve a leer el código."])
        lines.extend(f"- {location(ref)}" for ref in evidence.values())
    lines.extend(["", "INFORMACIÓN FALTANTE"])
    lines.extend(f"- {item}" for item in result.missing_information)
    if not result.missing_information:
        lines.append("Sin pendientes declarados; interpretar junto con el motivo de cierre y los límites.")
    if result.deferred_stages:
        lines.extend(["", "ETAPAS PENDIENTES DEL PROVEEDOR"])
        lines.extend(f"- {stage.node}: {stage.reason} ({stage.attempts} intento(s))" for stage in result.deferred_stages)
    lines.extend(["", "LIMITACIONES"])
    lines.extend(f"- {item}" for item in result.limitations)
    lines.extend(["", "CONSUMO", f"Llamadas al modelo: {result.model_calls} | Herramientas: {result.tool_calls} | Rondas: {result.iterations}",
        f"Tokens contabilizados: {result.accounted_tokens} | Parte estimada: {result.estimated_tokens}"])
    return "\n".join(lines)
