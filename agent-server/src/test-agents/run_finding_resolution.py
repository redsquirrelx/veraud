"""Run planning and investigation; defaults to fixture_A and finding_resolution/out.json.

    uv run python src/test-agents/run_finding_resolution.py
    uv run python src/test-agents/run_finding_resolution.py REPOSITORY --findings FILE

Output is readable by default; use --output json for structured output.
Planning and investigation use the configured LLM and may incur provider costs.
"""

import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from pydantic import TypeAdapter
from run_architecture_boundary import load_test_model

from server.agents.finding_resolution import (
    FindingResolutionAgent,
    FindingResolutionConfig,
    FindingResolutionRequest,
)
from server.agents.maintainability.modularity.architecture_boundary.schemas import (
    BoundaryFinding,
)
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
DEFAULT_REPOSITORY = FIXTURES / "architecture_boundary" / "fixture_A"
DEFAULT_FINDINGS = FIXTURES / "finding_resolution" / "out.json"


def load_findings(path: str | Path) -> list[Finding]:
    """Read only the findings into agent input, retaining specialized audit fields."""
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    rows = payload["findings"] if isinstance(payload, dict) else payload
    return TypeAdapter(list[Finding | BoundaryFinding]).validate_python(rows)


def render_verification_plan(request, state):
    """Present plans and collected evidence without implying a resolution decision."""
    statuses = {"planning_completed": "Planificacion completada", "no_findings": "Sin hallazgos recibidos",
        "investigations_completed": "Recopilacion de evidencias completada",
        "investigations_completed_with_errors": "Hallazgos procesados con errores de investigacion",
        "model_call_limit": "Limite de llamadas alcanzado", "token_limit": "Limite de tokens alcanzado",
        "time_limit": "Tiempo disponible agotado", "model_or_schema_error": "Error del modelo o de validacion; consulte la fase afectada"}
    plans = {plan.finding_id: plan for plan in state["plans"]}
    investigations = {item.finding_id: item for item in state.get("investigations", [])}
    usage = state["consumption"]
    lines = ["PLAN DE VERIFICACION DE HALLAZGOS", "=" * 50,
        f"Repositorio: {request.repository_path}",
        f"Estado: {statuses.get(state['termination_reason'], state['termination_reason'])}",
        f"Hallazgos recibidos: {len(request.findings)} | Planes generados: {len(plans)}",
        ("Solo recopilacion de evidencias: no hay decisiones de resolucion (evaluate_resolution no implementado)."
            if investigations else "Las consultas NO se han ejecutado y no hay decisiones de resolucion.")]
    if not request.findings:
        lines.append("\nNo hay hallazgos que planificar. Esto no demuestra ausencia de problemas.")
    for number, finding in enumerate(request.findings, 1):
        lines.extend(["", f"{number}. {finding.title}", f"   ID: {finding.id}",
            f"   Problema original: {finding.description}",
            f"   Elementos afectados: {', '.join(finding.components)}"])
        plan = plans.get(finding.id)
        if plan is None:
            current = state.get("finding")
            if current is not None and current.id == finding.id and state["termination_reason"] == "model_or_schema_error":
                lines.append("   Error de planificacion: no se obtuvo un plan valido para este hallazgo.")
            else:
                lines.append("   Sin plan generado; este hallazgo queda pendiente.")
            continue
        for index, check in enumerate(plan.checks, 1):
            lines.extend(["", f"   Comprobacion {index}: {check.question}", "     Evidencias que se necesitan:"])
            lines.extend(f"       - {item}" for item in check.evidence_needed)
            lines.append("     Consultas propuestas en el plan:")
            for query in check.queries:
                arguments = ", ".join(f"{key}={value!r}" for key, value in query.arguments.items())
                lines.append(f"       - {query.name}({arguments})")
            lines.extend([f"     Persiste si: {check.persists_if}", f"     Se considera resuelto si: {check.resolved_if}"])
        if plan.limitations:
            lines.append("   Limitaciones de este plan:")
            lines.extend(f"     - {item}" for item in plan.limitations)
        investigation = investigations.get(finding.id)
        if investigation:
            lines.extend(["", "   INVESTIGACION Y EVIDENCIAS RECOPILADAS",
                f"     Cierre de recopilacion: {investigation.stop_reason}", f"     Resumen: {investigation.summary}"])
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
                if response.error:
                    lines.append(f"       Error: {response.error.code}: {response.error.message}")
                content = (response.data or {}).get("content", "")
                if content:
                    snippet = content.splitlines()
                    lines.extend(f"       {line}" for line in snippet[:8])
                    if len(snippet) > 8:
                        lines.append("       ... (fragmento completo disponible con --output json)")
            lines.extend(f"     Limitacion: {item}" for item in investigation.limitations)
            lines.append(f"     Consumo de este hallazgo: {investigation.consumption.model_calls} llamadas LLM, "
                f"{investigation.consumption.tool_calls} herramientas, {investigation.consumption.accounted_tokens} tokens")
    if state["limitations"]:
        lines.append("\nLimitaciones de la ejecucion:")
        lines.extend(f"  - {item}" for item in state["limitations"])
    lines.extend(["", "CONSUMO", f"  Llamadas LLM: {usage.model_calls} | Herramientas ejecutadas: {usage.tool_calls}",
        f"  Tokens contabilizados: {usage.accounted_tokens} | Tokens estimados: {usage.estimated_tokens}"])
    return "\n".join(lines)


async def run(repository_path: str, findings_path: str, agent_config: str, output: str = "readable"):
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
    try:
        state = await FindingResolutionAgent(model, config).run(request, tools=tools)
        if output == "json":
            print(json.dumps({"plans": [plan.model_dump(mode="json") for plan in state["plans"]],
                "investigations": [item.model_dump(mode="json") for item in state["investigations"]],
                "termination_reason": state["termination_reason"], "limitations": state["limitations"],
                "consumption": state["consumption"].model_dump()}, indent=2))
        else:
            print(render_verification_plan(request, state))
    finally:
        await close_model_clients(SimpleNamespace(llm=model))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository_path", nargs="?", default=str(DEFAULT_REPOSITORY),
        help="Current repository (default: architecture_boundary/fixture_A)")
    parser.add_argument("--findings", default=str(DEFAULT_FINDINGS),
        help="Previous findings list or audit result (default: finding_resolution/out.json)")
    parser.add_argument("--agent-config", default="dummy")
    parser.add_argument("--output", choices=("readable", "json"), default="readable",
        help="Readable summary (default) or structured JSON")
    args = parser.parse_args()
    asyncio.run(run(args.repository_path, args.findings, args.agent_config, args.output))
