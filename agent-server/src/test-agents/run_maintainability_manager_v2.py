r"""Desde agent-server (llamadas reales al proveedor):

    uv run python src/test-agents/run_maintainability_manager_v2.py C:\repos\ShopLab --prompt "Analiza la mantenibilidad"

Ejecuta el Manager hasta finalize_audit; --plan-only conserva el corte en plan_audit. Reutiliza el modelo de
config/dev-agents.yaml (--agent-config, por defecto dummy), LLM_API_KEY del .env
y tracing opcional. --capabilities carga una lista JSON de capacidades públicas
de coordinadores disponibles; sin ella utiliza el registro interno de V2.
--output-file sobrescribe un resultado JSON UTF-8. El repositorio es de solo lectura.
--architecture-context carga el output canónico de Architecture Context para
transportarlo a investigadores compatibles; Manager y coordinadores no lo analizan.
"""

import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pydantic import TypeAdapter
from run_architecture_boundary import load_test_model

from server.agent_services.budgeting.policy import using_token_budget_policy
from server.agents.architecture_context import ArchitectureContextResult
from server.agents.maintainability.v2.manager import (
    CoordinatorCapability,
    MaintainabilityManager,
    MaintainabilityRequest,
)
from server.agents.maintainability.v2.manager.config import MaintainabilityConfig
from server.agents.maintainability.v2.manager.registry import coordinator_catalog
from server.config.runner import load_runner_config
from server.infrastructure.tracing import LangSmithTracingBackend
from server.runtimes.repository.context import RepositoryContext
from server.runtimes.repository.model_runtime import close_model_clients
from server.runtimes.repository.schemas import ExecutionBudget, RepositoryInput
from server.runtimes.repository.tools import RepositoryToolset
from server.services.repository_analysis import (
    RepositoryAnalysisInput,
    RepositoryAnalysisService,
)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("repository", help="Ruta del repositorio local")
    result.add_argument("--prompt", required=True, help="Solicitud original de mantenibilidad")
    result.add_argument("--target", action="append", default=[], help="Ruta relativa de alcance; repetible")
    result.add_argument("--constraint", action="append", default=[], help="Restricción explícita; repetible")
    result.add_argument("--repository-context", default="", help="Contexto adicional del repositorio")
    result.add_argument("--architecture-context", help="Archivo con ArchitectureContextResult canónico; solo para investigadores que lo declaren")
    result.add_argument("--capabilities", help="Lista JSON que sustituye al catálogo registrado de V2 (incluye [] para vaciarlo)")
    result.add_argument("--agent-config", default="dummy")
    result.add_argument("--config", help="Configuración operativa JSON")
    result.add_argument("--max-files", type=int, default=2000)
    result.add_argument("--output", choices=("readable", "json"), default="readable")
    result.add_argument("--output-file", help="Guardar/sobrescribir el resultado JSON completo")
    result.add_argument("--plan-only", action="store_true", help="Terminar después de plan_audit, sin delegar")
    return result


async def run(args):
    request = MaintainabilityRequest(objective=args.prompt, targets=args.target, constraints=args.constraint,
        repository_context=args.repository_context,
        documented_architecture=ArchitectureContextResult.model_validate_json(
            Path(args.architecture_context).read_text(encoding="utf-8")) if args.architecture_context else None)
    capabilities = TypeAdapter(list[CoordinatorCapability]).validate_json(
        Path(args.capabilities).read_text(encoding="utf-8")) if args.capabilities else None
    capabilities = list(coordinator_catalog(capabilities).values())
    config, policy = load_runner_config(MaintainabilityConfig, args.config)
    model, settings = load_test_model(args.agent_config)
    try:
        return await run_plan(args, request, capabilities, config, model, settings, token_policy=policy)
    finally:
        await close_model_clients(SimpleNamespace(llm=model))


async def run_plan(args, request, capabilities, config, model, settings, *, token_policy=None, tracing_backend=None):
    root = Path(args.repository).expanduser().resolve()
    config = config.model_copy(update={"max_output_tokens": min(config.max_output_tokens, settings.max_tokens)})
    snapshot = await RepositoryAnalysisService().analyze(RepositoryAnalysisInput(
        root_path=str(root), max_files=args.max_files, max_total_bytes=16_000_000))
    budget = ExecutionBudget(max_model_calls=config.max_model_calls, max_tool_calls=max(1, config.max_tool_calls),
        max_total_tokens=config.max_total_tokens, max_tokens_per_objective=config.max_total_tokens,
        max_input_tokens_per_call=max(500, config.max_context_characters // 2),
        max_output_tokens_per_call=config.max_output_tokens, max_elapsed_seconds=config.timeout_seconds)
    tools = RepositoryToolset(RepositoryContext(snapshot, RepositoryInput(
        snapshot_hash=snapshot.repository.snapshot_hash, budget=budget)), workspace_root=root.parent)
    tracing = tracing_backend if tracing_backend is not None else LangSmithTracingBackend()
    with using_token_budget_policy(token_policy):
        manager = MaintainabilityManager(model, config, tracing_backend=tracing)
        operation = manager.plan_audit if args.plan_only else manager.run
        state = await operation(tools, request, capabilities=capabilities)
    serialized = json.dumps(TypeAdapter(Any).dump_python(state, mode="json"), ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).write_text(serialized + "\n", encoding="utf-8")
    print(serialized if args.output == "json" else render_plan(state) if args.plan_only else render_result(state))
    return state


def render_plan(state):
    plan = state["plan"]
    usage = state["consumption"]
    lines = ["PLAN DE AUDITORÍA · MANTENIBILIDAD V2", f"Repositorio: {state['repository_id']}",
        f"Solicitud: {state['request'].objective}", "Parada: plan_audit · sin delegaciones ni investigaciones",
        f"Estado: {state['termination_reason'] or 'plan disponible'}",
        f"Catálogo: {len(state['coordinator_catalog'])} coordinadores",
        f"Consumo: {usage.model_calls} llamadas LLM, {usage.accounted_tokens} tokens contabilizados"]
    if not state["coordinator_catalog"]:
        lines.append("Catálogo vacío: proporciona --capabilities para seleccionar coordinadores disponibles.")
    if plan is not None:
        lines.append(f"Objetivo del plan: {plan.objective}")
        for assignment in plan.assignments:
            lines.extend([f"\n[{assignment.coordinator_id}] {assignment.objective}",
                f"  Alcance: {', '.join(assignment.scope) or 'repositorio (respetando el prompt original)'}",
                f"  Motivo: {assignment.rationale}"])
            lines.extend(f"  Restricción: {item}" for item in assignment.constraints)
        lines.extend(f"No cubierto: {item}" for item in plan.uncovered_requirements)
    lines.extend(f"Limitación: {item}" for item in state["limitations"])
    return "\n".join(lines)


def render_result(result):
    lines = ["AUDITORÍA DE MANTENIBILIDAD V2", f"Repositorio: {result.repository_id}",
        f"Solicitud: {result.objective}", f"Estado: {result.status}", result.summary,
        f"Consumo: {result.consumption.model_calls} llamadas LLM, {result.consumption.accounted_tokens} tokens contabilizados"]
    for reference, finding in result.findings.items():
        lines.append(f"{reference}: {finding.payload.get('title', finding.payload.get('concern', 'Observación'))}")
    lines.extend(f"Limitación: {item}" for item in result.limitations)
    return "\n".join(lines)


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
