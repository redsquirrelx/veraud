"""Source-linked execution diagnostics, distinct from software-quality findings."""

import re

from pydantic import BaseModel, Field

REASONS = {
    "security_legacy_scope": "Registro histórico: el adaptador marcó el alcance heurístico como parcial; este motivo no acredita por sí mismo un fallo o una interrupción.",
    "security_empty_scope": "No se encontraron archivos accesibles en el alcance de seguridad seleccionado.",
    "security_file_limit": "Se alcanzó el límite de archivos de seguridad; quedan archivos sin inspeccionar.",
    "security_source_read_failed": "No se pudo leer parte del código previsto para el análisis de seguridad.",
    "security_source_line_limit": "Una línea de código supera el límite de caracteres por fragmento; no pudo leerse completa.",
    "security_source_response_limit": "Una línea de código no cabe en el tamaño máximo de respuesta de la herramienta.",
    "security_retrieval_limit": "El presupuesto acumulado de recuperación de contenido no permite completar otra lectura de seguridad.",
    "security_source_access_denied": "El toolset rechazó el acceso a parte del código previsto para seguridad.",
    "security_source_range_invalid": "No está disponible el rango de código solicitado para seguridad; consulta el archivo y las líneas del diagnóstico.",
    "security_source_truncated": "Parte del código se inspeccionó mediante fragmentos truncados; la cobertura de seguridad es parcial.",
    "security_scope_incomplete": "Quedan archivos del alcance de seguridad sin inspeccionar.",
    "security_remediation_fallback": "No se completó una propuesta de remediación con el modelo; se conservaron el candidato y la propuesta local.",
    "security_interrupted": "El análisis de seguridad se interrumpió; se conservó el trabajo parcial.",
    "round_limit": "Se alcanzó el límite de rondas sin completar la cobertura requerida.",
    "model_call_limit": "Se alcanzó el límite de llamadas al modelo.",
    "tool_call_limit": "Se alcanzó el límite de llamadas a herramientas.",
    "token_limit": "Se agotó el presupuesto de tokens del agente.",
    "audit_token_limit": "Se agotó el presupuesto compartido de tokens de la auditoría.",
    "provider_retry_wait_limit": "Etapa pendiente: el proveedor solicitó una espera superior al límite automático; el trabajo recopilado se conserva.",
    "provider_daily_quota_exhausted": "Etapa pendiente: se agotó la cuota diaria del proveedor; reducir las solicitudes por minuto no la restablece. El trabajo recopilado se conserva.",
    "provider_request_timeout": "Etapa pendiente: el proveedor no respondió dentro del plazo de la petición; se conserva el trabajo parcial.",
    "provider_recovery_budget": "Etapa pendiente: se agotó el tiempo de recuperación del proveedor; el trabajo recopilado se conserva.",
    "provider_recovery_exhausted": "Etapa pendiente: el proveedor siguió fallando tras los reintentos permitidos; el trabajo recopilado se conserva.",
    "provider_retry_token_limit": "Etapa pendiente: tras el fallo del proveedor no quedan tokens suficientes para reintentar; el trabajo recopilado se conserva.",
    "provider_retry_call_limit": "Etapa pendiente: tras el fallo del proveedor no quedan llamadas disponibles para reintentar; el trabajo recopilado se conserva.",
    "provider_retry_wall_time_limit": "Etapa pendiente: la espera de recuperación supera el plazo restante; el trabajo recopilado se conserva.",
    "provider_tpm_request_limit": "La petición supera la cuota de tokens por minuto configurada.",
    "model_or_schema_error": "No pudo completarse una petición al modelo o la validación de su respuesta.",
    "schema_recovery_exhausted": "Se agotaron los intentos de corrección de la respuesta estructurada.",
    "no_investigation_progress": "La investigación terminó tras varios turnos sin evidencia nueva.",
    "zero_progress": "La última ronda no aportó evidencia nueva ni mejoró la cobertura.",
    "time_limit": "Se agotó el tiempo permitido para la ejecución.",
    "timeout": "Se agotó el tiempo permitido para la ejecución.",
    "context_limit": "La petición supera el contexto disponible del modelo.",
    "resource_limit": "No quedan recursos suficientes para otra investigación.",
    "execution_budget_exhausted": "No ejecutado: no se pudo reservar el presupuesto de la investigación.",
    "essential_investigation_failed": "Una investigación esencial no pudo completarse.",
    "no_actionable_follow_up": "Quedan aspectos sin resolver, sin un seguimiento útil disponible.",
    "unresolved_no_useful_follow_up": "Quedan aspectos sin resolver, sin un seguimiento útil disponible.",
}
INCOMPLETE = {"partial", "failed", "timeout", "skipped", "cancelled"}
EVENT = re.compile(r"security_source_read:|resource_shortfall:|provider_request:|response_schema|structured_output_setup:|provider_retry_(?:wait|token|call|wall_time)_limit:|"
    r"provider_recovery_(?:budget|exhausted):|source_not_inspected|boundary_[a-z_]+|review_unknown_candidates|unknown component ID")


class ExecutionDiagnostic(BaseModel):
    agent_id: str
    invocation_id: str
    status: str | None = None
    termination_reason: str | None = None
    explanation: str
    incidents: list[str] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)
    source_record_ids: list[str] = Field(default_factory=list)


def execution_records(assessments, evidence=(), findings=()):
    """Include children with zero evidence; their parent still retains their result/error."""
    executions = {}

    def visit(report, agent, invocation, status, error, source, failure=None):
        if not invocation:
            return
        previous = executions.get(invocation, {})
        report = report if isinstance(report, dict) else {}
        executions[invocation] = {"agent_id": agent or "agente", "invocation_id": invocation,
            "status": status or report.get("status"), "error": error or previous.get("error"), "report": report,
            "failure": failure or previous.get("failure"),
            "source_record_ids": list(dict.fromkeys([*previous.get("source_record_ids", []), source]))}
        for child in [*report.get("invocations", []), *report.get("assessments", [])]:
            if not isinstance(child, dict):
                continue
            assignment = child.get("assignment", {})
            visit(child.get("result"), assignment.get("investigator_id"), assignment.get("invocation_id"),
                child.get("status"), child.get("error"), source, child.get("failure"))

    for record in assessments:
        visit(record.details.get("report", record.model_dump(mode="json")), record.agent_id,
            record.invocation_id, record.status, None, record.id)
    for record in [*evidence, *findings]:
        report = record.details.get("investigation")
        if isinstance(report, dict) and record.invocation_id not in executions:
            visit(report, record.agent_id, record.invocation_id, report.get("status"), None, record.id)
    return list(executions.values())


def execution_diagnostics(assessments, evidence=(), findings=()):
    issues = []
    for execution in execution_records(assessments, evidence, findings):
        report = execution["report"]
        failure = execution.get("failure") or {}
        reason = report.get("termination_reason") or failure.get("code") or (
            execution["error"] if execution["error"] in REASONS else "timeout" if execution["status"] == "timeout" else None)
        if execution["status"] not in INCOMPLETE and reason not in REASONS:
            continue
        inherited = set()

        def collect_children(value, inherited=inherited):
            for child in [*value.get("invocations", []), *value.get("assessments", [])]:
                result = child.get("result") or {}
                inherited.update(result.get("limitations", []))
                inherited.update(result.get("missing_information", []))
                inherited.update(child.get("warnings", []))
                collect_children(result)

        collect_children(report)
        diagnostics = list(dict.fromkeys(value for value in [*report.get("limitations", []),
            *report.get("missing_information", [])] if isinstance(value, str) and value not in inherited and EVENT.search(value)))
        if execution["error"]:
            diagnostics.insert(0, execution["error"])
        diagnostics.extend(failure.get("diagnostics", []))
        if failure:
            diagnostics.append(f"Etapa: {failure.get('stage')}")
        for resource in failure.get("resources", []):
            diagnostics.append(f"{resource['resource']}: disponible={resource['available']:g}; requerido={resource['required']:g}")
        incidents = []
        joined = "\n".join(diagnostics)
        for code in sorted(set(re.findall(r"http_status=(\d{3})", joined))):
            incidents.append({"503": "Google/proveedor no disponible (HTTP 503).",
                "400": "El proveedor rechazó una petición (HTTP 400); la causa exacta requiere el diagnóstico de campos.",
                "429": "El proveedor informó un límite de cuota (HTTP 429)."}.get(code, f"Error del proveedor HTTP {code}."))
        if "response_schema" in joined:
            incidents.append("Se registraron respuestas que no cumplieron el contrato de evaluación o revisión.")
        if "source_not_inspected" in joined or "boundary_" in joined:
            incidents.append("No se pudo validar parte de la evidencia o de su correspondencia con las afirmaciones.")
        explanation = failure.get("summary") or REASONS.get(reason, f"Motivo registrado: {reason}." if reason else
            "No se publicó una causa específica para esta ejecución incompleta.")
        issues.append(ExecutionDiagnostic(**{key: execution[key] for key in
            ("agent_id", "invocation_id", "status", "source_record_ids")}, termination_reason=reason,
            explanation=explanation, incidents=incidents, diagnostics=diagnostics))
    return issues
