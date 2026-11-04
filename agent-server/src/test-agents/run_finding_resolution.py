"""Run finding resolution; defaults to example_repos/A's repository and findings.

    uv run python src/test-agents/run_finding_resolution.py
    uv run python src/test-agents/run_finding_resolution.py REPOSITORY --findings FILE

Output is readable by default; use --output json for structured output.
Planning and investigation use the configured LLM and may incur provider costs.
"""

import argparse
import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace

from pydantic import TypeAdapter
from run_architecture_boundary import load_test_model

from server.agents.finding_resolution import (
    FindingResolutionAgent,
    FindingResolutionConfig,
    FindingResolutionRequest,
)
from server.agents.finding_resolution.diagnostics import (
    failure_text,
    safe_arguments,
    safe_text,
)
from server.agents.maintainability.modularity.architecture_boundary.schemas import (
    BoundaryFinding,
)
from server.config.logs import get_logger
from server.contracts.audit import Finding
from server.runtimes.repository.context import RepositoryContext
from server.runtimes.repository.model_runtime import close_model_clients
from server.runtimes.repository.schemas import ExecutionBudget, RepositoryInput
from server.runtimes.repository.tools import RepositoryToolset
from server.services.repository_analysis import (
    RepositoryAnalysisInput,
    RepositoryAnalysisService,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
DEFAULT_REPOSITORY = FIXTURES / "example_repos" / "A" / "fixture_A"
DEFAULT_FINDINGS = FIXTURES / "example_repos" / "A" / "findings.json"


def load_findings(path: str | Path) -> list[Finding]:
    """Read only the findings into agent input, retaining specialized audit fields."""
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    rows = payload["findings"] if isinstance(payload, dict) else payload
    return TypeAdapter(list[Finding | BoundaryFinding]).validate_python(rows)


class DiagnosticCapture(logging.Handler):
    """CLI-only capture: no diagnostic fields are added to agent contracts/state."""

    def __init__(self):
        super().__init__()
        self.diagnostics = []
        self.traces = []

    def emit(self, record):
        if hasattr(record, "finding_resolution_diagnostic"):
            self.diagnostics.append(record.finding_resolution_diagnostic)
        if hasattr(record, "finding_resolution_trace"):
            self.traces.append(record.finding_resolution_trace)


def render_verification_plan(request, state, diagnostics=(), traces=()):
    """Present final decisions alongside plans, current evidence and diagnostics."""
    statuses = {"planning_completed": "Planificacion completada", "no_findings": "Sin hallazgos recibidos",
        "investigations_completed": "Investigacion y evaluacion completadas",
        "investigations_completed_with_errors": "Hallazgos procesados con errores de investigacion o evaluacion",
        "model_call_limit": "Limite de llamadas alcanzado", "token_limit": "Limite de tokens alcanzado",
        "time_limit": "Tiempo disponible agotado", "model_or_schema_error": "Error del modelo o de validacion; consulte la fase afectada"}
    plans = {plan.finding_id: plan for plan in state["plans"]}
    investigations = {item.finding_id: item for item in state.get("investigations", [])}
    final = state.get("final_result")
    results = {item.finding_id: item for item in (final.results if final else state.get("results", []))}
    usage = state["consumption"]
    lines = ["PLAN DE VERIFICACION DE HALLAZGOS", "=" * 50,
        f"Repositorio: {request.repository_path}",
        f"Estado: {statuses.get(state['termination_reason'], state['termination_reason'])}",
        f"Hallazgos recibidos: {len(request.findings)} | Planes generados: {len(plans)}",
        ("Resultado final validado; un resultado por hallazgo original." if final else
            "Evaluaciones individuales registradas; no se ha ejecutado una finalizacion de auditoria."
            if results else "Solo recopilacion de evidencias: no hay decisiones de resolucion."
            if investigations else "Las consultas NO se han ejecutado y no hay decisiones de resolucion.")]
    if not request.findings:
        lines.append("\nNo hay hallazgos que planificar. Esto no demuestra ausencia de problemas.")
    for number, finding in enumerate(request.findings, 1):
        errors = [event for event in diagnostics if event["finding_id"] == finding.id]
        lines.extend(["", f"{number}. {safe_text(finding.title)}", f"   ID: {finding.id}",
            f"   Problema original: {safe_text(finding.description)}",
            f"   Elementos afectados: {', '.join(finding.components)}"])
        result = results.get(finding.id)
        if result:
            lines.extend([f"   Evaluacion: {result.status}", f"   Justificacion: {safe_text(result.reason)}",
                f"   Evidencias citadas: {', '.join(result.evidence_ids) or 'ninguna'}"])
        for event in errors:
            lines.append(f"   Diagnostico [{event['node']} / {event['category']} / intento {event['attempt']}]:")
            if event.get("error_type"):
                lines.append(f"     Tipo: {event['error_type']}")
            if event.get("http_status") is not None:
                lines.append(f"     HTTP: {event['http_status']} {event.get('provider_facts', '')}")
            if event.get("generation_outcome"):
                lines.append(f"     Generacion: {event['generation_outcome']}")
            if event.get("safe_detail"):
                lines.append(f"     Detalle: {event['safe_detail']}")
            for issue in event["issues"]:
                lines.append(f"     Campo: {issue['field']} | Regla: {issue['rule']}"
                    + (f" | Restriccion: {issue['constraints']}" if issue.get("constraints") else ""))
        plan = plans.get(finding.id)
        if plan is None:
            current = state.get("finding")
            if current is not None and current.id == finding.id and state["termination_reason"] == "model_or_schema_error":
                lines.append("   Error de planificacion: no se obtuvo un plan valido para este hallazgo.")
            else:
                lines.append("   Sin plan generado; este hallazgo queda pendiente.")
            continue
        for index, check in enumerate(plan.checks, 1):
            lines.extend(["", f"   Comprobacion {index}: {safe_text(check.question)}", "     Evidencias que se necesitan:"])
            lines.extend(f"       - {safe_text(item)}" for item in check.evidence_needed)
            lines.append("     Consultas propuestas en el plan:")
            for query in check.queries:
                arguments = ", ".join(f"{key}={value!r}" for key, value in safe_arguments(query.arguments).items())
                lines.append(f"       - {query.name}({arguments})")
            lines.extend([f"     Persiste si [persists_if]: {safe_text(check.persists_if)}",
                f"     Se considera resuelto si [resolved_if]: {safe_text(check.resolved_if)}",
                "     Criterios propuestos: la evaluacion debe contrastarlos con el problema original."])
        if plan.limitations:
            lines.append("   Limitaciones de este plan:")
            lines.extend(f"     - {safe_text(item)}" for item in plan.limitations)
        investigation = investigations.get(finding.id)
        if investigation:
            lines.extend(["", "   INVESTIGACION Y EVIDENCIAS RECOPILADAS",
                f"     Cierre de recopilacion: {investigation.stop_reason}", f"     Resumen: {safe_text(investigation.summary)}"])
            if investigation.stop_reason == "model_or_schema_error":
                lines.append("     Error de investigacion: no se obtuvo una respuesta valida; consulte las limitaciones. Evidencias previas conservadas.")
            if not investigation.evidence:
                lines.append("     No se recuperaron evidencias actuales; esto NO significa que el problema este resuelto.")
            for reference in investigation.evidence:
                location = reference.path
                if reference.start_line is not None:
                    location += f":{reference.start_line}-{reference.end_line}"
                lines.extend([f"     - {location} ({reference.kind})", f"       Evidencia: {reference.id}",
                    f"       Consulta: {reference.tool_call_id}"])
                if reference.symbol_ids:
                    lines.append(f"       Simbolos: {', '.join(reference.symbol_ids)}")
            for response in investigation.tool_results:
                lines.append(f"     Herramienta: {response.tool_name} | {response.status} | {response.tool_call_id}")
                query = next((event for event in traces if event.get("transition") == "tool_result"
                    and event.get("tool_call_id") == response.tool_call_id), None)
                if query:
                    lines.append("       Argumentos ejecutados: " + json.dumps(query["arguments"]))
                if response.error:
                    lines.append(f"       Error: {response.error.code}")
            lines.extend(f"     Limitacion: {failure_text(item, errors)}" for item in investigation.limitations)
            lines.append(f"     Consumo de este hallazgo: {investigation.consumption.model_calls} llamadas LLM, "
                f"{investigation.consumption.tool_calls} herramientas, {investigation.consumption.accounted_tokens} tokens")
    if state["limitations"]:
        lines.append("\nLimitaciones de la ejecucion:")
        lines.extend(f"  - {failure_text(item, diagnostics)}" for item in state["limitations"])
    complete = state["termination_reason"] in {"no_findings", "investigations_completed", "investigations_completed_with_errors"}
    lines.extend(["", "RESUMEN DE EJECUCION",
        (f"  Evaluaciones: {len(results)} | Resolved: {sum(item.status == 'resolved' for item in results.values())} | "
            f"Persists: {sum(item.status == 'persists' for item in results.values())} | Inconclusive: {sum(item.status == 'inconclusive' for item in results.values())}"),
        f"  Investigaciones registradas: {len(investigations)} | Sin investigacion registrada: {len(request.findings) - len(investigations)}",
        f"  Hallazgos con error de investigacion: {sum(item.stop_reason == 'model_or_schema_error' for item in investigations.values())}",
        f"  Interrupcion global: {'ninguna' if complete else state['termination_reason']}"])
    lines.extend(["", "CONSUMO", f"  Llamadas LLM: {usage.model_calls} | Herramientas ejecutadas: {usage.tool_calls}",
        f"  Tokens contabilizados: {usage.accounted_tokens} | Tokens estimados: {usage.estimated_tokens}"])
    return "\n".join(lines)


async def run(repository_path: str, findings_path: str, agent_config: str, output: str | None = "readable"):
    request = FindingResolutionRequest(repository_path=repository_path, findings=load_findings(findings_path))
    config = FindingResolutionConfig()
    root = Path(repository_path).resolve()
    snapshot = await RepositoryAnalysisService().analyze(RepositoryAnalysisInput(root_path=str(root)))
    budget = ExecutionBudget(max_model_calls=config.max_model_calls, max_tool_calls=config.max_tool_calls,
        max_total_tokens=config.max_total_tokens, max_tokens_per_objective=config.max_total_tokens,
        max_input_tokens_per_call=config.max_context_characters // 2,
        max_output_tokens_per_call=config.max_output_tokens, max_elapsed_seconds=config.timeout_seconds)
    tools = RepositoryToolset(RepositoryContext(snapshot, RepositoryInput(
        snapshot_hash=snapshot.repository.snapshot_hash, budget=budget)), workspace_root=root.parent)
    model, _ = load_test_model(agent_config)
    capture = DiagnosticCapture()
    logger = get_logger("finding-resolution")
    logger.addHandler(capture)
    try:
        state = await FindingResolutionAgent(model, config).run(request, tools=tools)
        if output == "json":
            print(json.dumps({"plans": [plan.model_dump(mode="json") for plan in state["plans"]],
                "final_result": state["final_result"].model_dump(mode="json"),
                "results": [item.model_dump(mode="json") for item in state["final_result"].results],
                "investigations": [item.model_dump(mode="json") for item in state["investigations"]],
                "termination_reason": state["termination_reason"], "limitations": state["limitations"],
                "consumption": state["consumption"].model_dump(),
                "diagnostics": capture.diagnostics, "traces": capture.traces}, indent=2))
        elif output == "readable":
            print(render_verification_plan(request, state, capture.diagnostics, capture.traces))
        return request, state, capture
    finally:
        logger.removeHandler(capture)
        await close_model_clients(SimpleNamespace(llm=model))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository_path", nargs="?", default=str(DEFAULT_REPOSITORY),
        help="Current repository (default: example_repos/A/fixture_A)")
    parser.add_argument("--findings", default=str(DEFAULT_FINDINGS),
        help="Previous findings list or audit result (default: example_repos/A/findings.json)")
    parser.add_argument("--agent-config", default="dummy")
    parser.add_argument("--output", choices=("readable", "json"), default="readable",
        help="Readable summary (default) or structured JSON")
    args = parser.parse_args()
    asyncio.run(run(args.repository_path, args.findings, args.agent_config, args.output))
