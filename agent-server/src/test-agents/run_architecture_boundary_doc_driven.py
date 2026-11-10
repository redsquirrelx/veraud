r"""Ejecutar desde agent-server (PowerShell):

    uv run python src/test-agents/run_architecture_boundary_doc_driven.py C:\repos\proyecto

Requisitos: LLM_API_KEY en el .env de la raíz del repositorio y un modelo con
tool calling en config/dev-agents.yaml. Por defecto usa agents.dummy.
Para otra entrada del YAML: --agent-config NOMBRE.
Opcionales: --request solicitud.json --config limites.json --max-files 2000 --max-output-tokens 4000.
Tracing opcional: LANGSMITH_API_KEY y LANGSMITH_PROJECT en el mismo .env.
Con clave, LangSmithTracingBackend registra el agente, grafo, nodos y llamadas LLM.
Sin clave, ejecuta normalmente sin tracing. Para ocultar código/prompts en las
trazas: LANGSMITH_HIDE_INPUTS=true y LANGSMITH_HIDE_OUTPUTS=true en el .env.
Realiza llamadas reales al proveedor (pueden generar costes). Muestra el plan y los resultados provisionales
legible; --output json muestra la salida JSON completa y --output-file RUTA
guarda el resultado completo en un archivo UTF-8, independientemente del formato de consola. No
escribe en el repositorio auditado. Ver --help para todas las opciones.

Carga --architecture-context RUTA como ArchitectureContextResult, si se proporciona.
Ejecuta hasta síntesis y finalización determinísticas; no confirma findings.
"""

import argparse
import asyncio
import json
from pathlib import Path

from langchain.chat_models import init_chat_model
from langgraph.graph import END, START, StateGraph
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from server.agent_services.budgeting.policy import (
    token_budget_policy,
    using_token_budget_policy,
)
from server.agents.architecture_context import ArchitectureContextResult
from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven import (
    ArchitectureBoundaryAgent,
    AuditRequest,
    BoundaryConfig,
)
from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.execution import (
    BoundaryExecution,
)
from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.state import (
    BoundaryState,
)
from server.config.dev_agents_config import load_dev_agents_config
from server.config.settings import ENV_FILE
from server.infrastructure.tracing import LangSmithTracingBackend, TracingBackend
from server.runtimes.invocation_reporting import phase_node
from server.runtimes.repository.context import RepositoryContext
from server.runtimes.repository.model_runtime import close_model_clients
from server.runtimes.repository.schemas import ExecutionBudget, RepositoryInput
from server.runtimes.repository.tools import RepositoryToolset, ToolLimits
from server.services.repository_analysis import (
    RepositoryAnalysisInput,
    RepositoryAnalysisService,
)


class RunnerCredentials(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", env_file_encoding="utf-8")
    llm_api_key: SecretStr = SecretStr("")


class PlanningOnlyExecution(BoundaryExecution):
    """Runner-only stopping point; the variant's normal graph is unchanged."""

    def _build_graph(self):
        graph = StateGraph(BoundaryState)
        graph.add_node("plan_investigation", phase_node("plan_investigation", self.plan_investigation))
        graph.add_edge(START, "plan_investigation")
        graph.add_edge("plan_investigation", END)
        return graph.compile()


class PlanningOnlyBoundaryAgent(ArchitectureBoundaryAgent):
    execution_type = PlanningOnlyExecution


class InvestigationOnlyExecution(BoundaryExecution):
    """Reuse production investigation/tools routes, stopping before synthesis."""

    def _build_graph(self):
        graph = StateGraph(BoundaryState)
        graph.add_node("plan_investigation", phase_node("plan_investigation", self.plan_investigation))
        graph.add_node("investigate", phase_node("investigate", self.investigate))
        graph.add_node("tools", phase_node("tools", self.execute_investigation_tools))
        graph.add_edge(START, "plan_investigation")
        graph.add_edge("plan_investigation", "investigate")
        graph.add_conditional_edges("investigate", self.route_investigation,
            {"tools": "tools", "investigate": "investigate", "synthesis": END})
        graph.add_edge("tools", "investigate")
        return graph.compile()


class InvestigationOnlyBoundaryAgent(ArchitectureBoundaryAgent):
    execution_type = InvestigationOnlyExecution


def load_test_model(agent_config="dummy"):
    configurations = load_dev_agents_config()
    if agent_config not in configurations:
        raise ValueError(f"No agent configuration {agent_config!r} in config/dev-agents.yaml.")
    _, settings = configurations[agent_config]
    key = RunnerCredentials(_env_file=ENV_FILE).llm_api_key.get_secret_value()
    if not key.strip():
        raise ValueError("Set LLM_API_KEY in the repository .env or environment.")
    provider = settings.provider.lower()
    kwargs = {"api_key": key, "temperature": settings.temperature,
              "max_tokens": settings.max_tokens, "max_retries": 0}
    if provider == "openrouter":
        provider = "openai"
        kwargs["base_url"] = "https://openrouter.ai/api/v1"
    if provider in ("gemini", "google"):
        provider = "google_genai"
    return init_chat_model(settings.name, model_provider=provider, **kwargs), settings


async def run(args):
    root = Path(args.repository).resolve()
    request = AuditRequest.model_validate_json(Path(args.request).read_text(encoding="utf-8")) if args.request else AuditRequest()
    if args.architecture_context is not None:
        context_path = Path(args.architecture_context).expanduser()
        documented_architecture = ArchitectureContextResult.model_validate_json(context_path.read_text(encoding="utf-8"))
        request = request.model_copy(update={"documented_architecture": documented_architecture})
    config = BoundaryConfig.model_validate_json(Path(args.config).read_text(encoding="utf-8")) if args.config else BoundaryConfig()
    if getattr(args, "max_output_tokens", None) is not None:
        config = BoundaryConfig.model_validate({
            **config.model_dump(), "max_output_tokens": args.max_output_tokens})
    token_policy = token_budget_policy()
    # Validate settings before repository analysis; credentials never enter graph state.
    model, settings = load_test_model(args.agent_config)
    try:
        await run_audit(args, root, request, config, model, settings, token_policy=token_policy)
    finally:
        # Reuse existing cleanup for LangChain-backed wrappers; the caller owns clients.
        from types import SimpleNamespace
        await close_model_clients(SimpleNamespace(llm=model))


async def run_audit(args, root, request, config, model, settings, *, tracing_backend: TracingBackend | None = None,
                    agent_class=None, token_policy=None):
    agent_class = agent_class if agent_class is not None else (
        PlanningOnlyBoundaryAgent if getattr(args, "plan_only", False) else ArchitectureBoundaryAgent)
    config = config.model_copy(update={"max_output_tokens": min(config.max_output_tokens, settings.max_tokens)})
    snapshot = await RepositoryAnalysisService().analyze(RepositoryAnalysisInput(
        root_path=str(root), max_files=args.max_files, max_total_bytes=16_000_000,
    ))
    budget = ExecutionBudget(
        max_model_calls=config.max_model_calls, max_tool_calls=max(1, config.max_tool_calls),
        max_total_tokens=config.max_total_tokens, max_tokens_per_objective=config.max_total_tokens,
        max_input_tokens_per_call=max(500, config.max_context_characters // 2),
        max_output_tokens_per_call=config.max_output_tokens, max_elapsed_seconds=config.timeout_seconds,
    )
    tools = RepositoryToolset(RepositoryContext(snapshot, RepositoryInput(
        snapshot_hash=snapshot.repository.snapshot_hash, budget=budget,
    )), workspace_root=root.parent, limits=ToolLimits(compact=True))
    tracing = tracing_backend if tracing_backend is not None else LangSmithTracingBackend()
    with using_token_budget_policy(token_policy):
        result = await tracing.wrap_stage(
            agent_class(model, config).run(tools, request),
            name=getattr(agent_class, "trace_name", "architecture-boundary"),
            agent_type=getattr(agent_class, "agent_type", "architecture_boundary"),
            repository_id=snapshot.repository.name,
            commit=snapshot.repository.commit,
            snapshot_hash=snapshot.repository.snapshot_hash,
            provider=settings.provider,
            model=settings.name,
        )
    serialized = json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2)
    if getattr(args, "output_file", None):
        Path(args.output_file).write_text(serialized + "\n", encoding="utf-8")
    if getattr(args, "output", "json") == "readable":
        print(render_boundary_plan(result))
    else:
        print(serialized)


def render_boundary_plan(result):
    """Human-facing planning summary; canonical JSON remains available."""
    tasks = getattr(result.plan, "investigations", [])
    lines = ["PLAN DE INVESTIGACIÓN · LÍMITES ARQUITECTÓNICOS",
        f"Repositorio: {result.repository_id}", f"Objetivo: {result.objective}",
        f"Estado: {result.termination_reason}", f"Snapshot: {result.snapshot_hash}",
        f"Investigaciones: {len(tasks)} · Hallazgos: {len(result.findings)} provisionales, no evaluados",
        (f"Recursos: {result.model_calls} llamadas al modelo, {result.tool_calls} herramientas, "
        f"{result.accounted_tokens} tokens contabilizados ({result.estimated_tokens} estimados)")]
    coverage = result.investigation_coverage
    if coverage.get("by_project"):
        lines.append("\nCobertura de producción por proyecto:")
        for project in coverage["by_project"]:
            lines.append(f"  {project['root']}: archivos elegibles={project['eligible_files']}, "
                f"excluidos no producción={project['excluded_nonproduction_files']}, "
                f"relaciones elegibles={project['eligible_relationships']} "
                f"(type_only={project['type_only_relationships']}, sin resolver={project['unresolved_relationships']}), "
                f"candidatos generados={project['candidates_generated']}, "
                f"deduplicados={project['candidates_deduplicated']}, "
                f"omitidos del menú={project['candidates_omitted']}, "
                f"seleccionados={project['selected']} (modelo={project['model_selected']}); "
                f"internos={project.get('internal_selected', 0)}, integraciones={project.get('integration_selected', 0)}; "
                f"índice={project['index_status']}, selección={project['selection_status']}")
        lines.append(f"  Sesgo de selección del modelo detectado: {coverage['selection_bias_detected']}; "
            f"candidatos sustituidos/ampliados: {coverage['selection_rebalanced']}; "
            f"solo reordenados: {coverage.get('selection_reordered', False)}")
        if coverage.get("integrations"):
            lines.append("  Descubrimiento de integraciones: " + json.dumps(coverage["integrations"], ensure_ascii=False))
            lines.append("  Oportunidades y descartes: " + json.dumps(coverage.get("opportunities", {}), ensure_ascii=False))
    for number, task in enumerate(tasks, 1):
        signal = task.structural_signal
        lines.extend(["", f"{number}. [{task.priority.upper()}] {task.id}",
            f"   Alcance: {', '.join(task.scope)}", f"   Pregunta: {task.question}",
            f"   Indicio ({signal.kind}):"])
        lines.extend(f"     Hecho indexado: {fact}" for fact in signal.observed)
        lines.append(f"     Inferencia por comprobar: {signal.inference}")
        lines.extend(f"     {ref.source_path} → {ref.target_path} ({ref.kind}; {ref.id}; "
            f"{ref.source_id} → {ref.target_id})" for ref in signal.relationships)
        for link in signal.integration_links:
            lines.append(f"     Integración {link.client.mechanism}: {link.client.project_id} → "
                f"{link.target_project_id or 'destino no resuelto'}; {link.match_basis}; {link.status}")
            for point in [link.client, *link.endpoints, *link.binding_points]:
                lines.append(f"       {point.path}:{point.start_line}-{point.end_line} · "
                    f"{point.method or ''} {point.authority or ''}{point.route or ''} · {point.id}")
        lines.append("   Evidencias necesarias:")
        lines.extend(f"     - {item}" for item in task.evidence_needed)
        lines.append("   Estrategia inicial:")
        lines.extend(f"     - {query.tool}({json.dumps(query.arguments, ensure_ascii=False)})"
            for query in task.investigation_strategy)
        lines.append(f"   Condición de cierre: {task.completion_condition}")
        if task.document_claim_ids:
            lines.append(f"   Claims documentales: {', '.join(task.document_claim_ids)}")
            for claim_id in task.document_claim_ids:
                record = result.plan.document_claims[claim_id]
                lines.append(f"     [{record.claim.constraint}] {record.claim.statement}")
    if not tasks:
        lines.append("\nNo se seleccionaron investigaciones. Esto no demuestra cumplimiento ni ausencia de dependencias.")
    conclusions = getattr(result, "investigation_results", [])
    if conclusions:
        lines.append("\nRESULTADOS PROVISIONALES · sin revisión crítica")
        for conclusion in conclusions:
            lines.extend([f"  {conclusion.investigation_id}: {conclusion.status} · {conclusion.summary}",
                f"    Justificación: {conclusion.justification}",
                f"    Evidencias: {', '.join(conclusion.evidence_ids) or 'no recuperadas'}"])
            lines.extend(f"    Candidato {candidate.id}: {candidate.title} · {candidate.technical_basis}"
                for candidate in conclusion.candidates)
            for assessment in conclusion.claim_assessments:
                lines.extend([f"    Claim {assessment.claim_id}: {assessment.status} · {assessment.rationale}",
                    f"      Código: {', '.join(assessment.code_evidence_ids) or 'no verificado'}",
                    f"      Alcance local: {', '.join(assessment.scope_paths) or 'no establecido'}"])
                lines.extend(f"      Excepción examinada: {item}" for item in assessment.exceptions_examined)
                lines.extend(f"      Limitación: {item}" for item in assessment.limitations)
            lines.extend(f"    Limitación: {item}" for item in conclusion.limitations)
    if result.candidates:
        lines.append("\nCANDIDATOS CONSOLIDADOS · sin aceptación ni rechazo")
        for candidate in result.candidates:
            origins = result.candidate_origins.get(candidate.id, [])
            lines.extend([f"  {candidate.id}: {candidate.title}",
                f"    Evidencias: {', '.join(candidate.evidence_ids)}",
                "    Orígenes: " + ", ".join(f"{origin.investigation_id}/{origin.candidate_id}" for origin in origins)])
    documentary = getattr(result, "documentary_synthesis", None)
    if documentary is not None:
        synthesis_coverage = documentary.coverage
        lines.extend(["\nSÍNTESIS DOCUMENTAL · evaluaciones locales, sin conformidad global",
            (f"  Claims seleccionados={len(synthesis_coverage.selected_claim_ids)}, evaluados={len(synthesis_coverage.evaluated_claim_ids)}, "
            f"con contradicción={len(synthesis_coverage.contradicted_claim_ids)}, compatibles locales={len(synthesis_coverage.locally_supported_claim_ids)}, "
            f"sin evaluar={len(synthesis_coverage.selected_not_evaluated_claim_ids)}"),
            f"  Entrega registrada={len(synthesis_coverage.delivered_claim_ids)}, entrega desconocida={len(synthesis_coverage.delivery_unknown_claim_ids)}"])
        for key, group in documentary.claims.items():
            lines.append(f"  {key}: cobertura={group.coverage_status}, contradicción localizada={group.has_contradiction}")
            for row in group.assessments:
                lines.append(f"    {row.investigation_id}: {row.assessment.status}; efectiva={row.effective}; "
                    f"alcance={', '.join(row.assessment.scope_paths) or 'no establecido'}")
            lines.extend(f"    Alcances: {comparison.scope_relation} · {comparison.limitation}" for comparison in group.comparisons)
        lines.extend(f"  Integridad: {issue.code} · {issue.message}" for issue in documentary.integrity_issues)
    lines.append("\nLimitaciones y trabajo pendiente:")
    if coverage.get("documentation"):
        lines.append("  Cobertura de planificación documental (no investigada): " +
            json.dumps(coverage["documentation"], ensure_ascii=False))
    if coverage.get("documentary_investigation"):
        lines.append("  Cobertura documental investigada (local, no conformidad global): " +
            json.dumps(coverage["documentary_investigation"], ensure_ascii=False))
    lines.extend(f"  - {item}" for item in dict.fromkeys([*result.limitations, *result.missing_information]))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository")
    parser.add_argument("--plan-only", action="store_true", help="Stop after planning; default also runs investigate")
    parser.add_argument("--architecture-context", type=Path,
        help="Canonical ArchitectureContextResult JSON file; overrides documented_architecture from --request")
    parser.add_argument("--agent-config", default="dummy", help="Agent entry in config/dev-agents.yaml (default: dummy)")
    parser.add_argument("--request", help="Data-only JSON: documented_architecture, targets, constraints and optional continuation; no external prompts")
    parser.add_argument("--config", help="JSON operating limits; this investigator does not accept prompt overrides")
    parser.add_argument("--max-files", type=int, default=2000)
    parser.add_argument("--max-output-tokens", type=int,
        help="Per-call output cap for this run; overrides BoundaryConfig.max_output_tokens (default 4000) while still bounded by the model settings")
    parser.add_argument("--output", choices=("readable", "json"), default="readable",
        help="Readable result (default) or complete canonical JSON")
    parser.add_argument("--output-file", help="Save the complete audit result as UTF-8 JSON at this path")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
