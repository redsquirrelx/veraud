r"""Prueba independiente: ejecuta ModularityCoordinator V2 hasta finalize_assessment.

    uv run python -X utf8 src/test-agents/run_modularity_coordinator_v2.py C:\repos\ShopLab --prompt "Investiga problemas arquitectónicos en Checkout"

Usa config/dev-agents.yaml, LLM_API_KEY y tracing opcional como los otros runners.
--investigator selecciona un subconjunto del registro real; --no-investigators
permite probar un catálogo vacío. --plan-only conserva el corte tras plan_assessment.
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
from server.agents.maintainability.v2.modularity.coordinator import (
    AssessmentRequest,
    ModularityConfig,
    ModularityCoordinator,
)
from server.agents.maintainability.v2.modularity.coordinator.registry import (
    investigator_catalog,
)
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
    result.add_argument("repository")
    result.add_argument("--prompt", required=True, help="Objetivo delegado o solicitud independiente")
    result.add_argument("--original-prompt", help="Objetivo original del Manager, si difiere del delegado")
    result.add_argument("--target", action="append", default=[])
    result.add_argument("--constraint", action="append", default=[])
    result.add_argument("--repository-context", default="")
    subset = result.add_mutually_exclusive_group()
    subset.add_argument("--investigator", action="append", help="ID registrado; repetible")
    subset.add_argument("--no-investigators", action="store_true")
    result.add_argument("--agent-config", default="dummy")
    result.add_argument("--config")
    result.add_argument("--max-files", type=int, default=2000)
    result.add_argument("--output", choices=("readable", "json"), default="readable")
    result.add_argument("--output-file")
    result.add_argument("--plan-only", action="store_true", help="Planificar sin ejecutar investigadores")
    result.add_argument("--architecture-context", help="ArchitectureContextResult canónico en JSON")
    return result


async def run(args):
    from server.agents.architecture_context import ArchitectureContextResult

    request = AssessmentRequest(objective=args.prompt, original_objective=args.original_prompt,
        targets=args.target, constraints=args.constraint, repository_context=args.repository_context,
        documented_architecture=ArchitectureContextResult.model_validate_json(Path(args.architecture_context).read_text(encoding="utf-8"))
            if args.architecture_context else None)
    catalog = investigator_catalog()
    if args.investigator and set(args.investigator) - catalog.keys():
        raise ValueError("Unknown investigator selection.")
    capabilities = [] if args.no_investigators else [value for key, value in catalog.items()
        if args.investigator is None or key in args.investigator]
    config, policy = load_runner_config(ModularityConfig, args.config)
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
        coordinator = ModularityCoordinator(model, config, tracing_backend=tracing)
        operation = coordinator.plan_assessment if args.plan_only else coordinator.run
        state = await operation(tools, request, capabilities=capabilities)
    serialized = json.dumps(TypeAdapter(Any).dump_python(state, mode="json"), ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).write_text(serialized + "\n", encoding="utf-8")
    print(serialized if args.output == "json" else render_plan(state) if args.plan_only else state.summary)
    return state


def render_plan(state):
    usage, plan = state["consumption"], state["plan"]
    lines = ["PLAN DE EVALUACIÓN DE MODULARIDAD V2", f"Repositorio: {state['repository_id']}",
        f"Objetivo: {state['request'].objective}", "Parada: plan_assessment · sin delegaciones ni investigaciones",
        f"Estado: {state['termination_reason'] or 'plan disponible'}",
        f"Consumo: {usage.model_calls} llamadas LLM, {usage.accounted_tokens} tokens contabilizados"]
    if plan is not None:
        for item in plan.assignments:
            lines.extend([f"\n[{item.investigator_id}] {item.objective}", f"  Motivo: {item.rationale}",
                f"  Targets: {', '.join(item.targets) or 'sin rutas explícitas; respetar alcance semántico de la solicitud'}"])
            lines.extend(f"  Restricción: {value}" for value in item.constraints)
        lines.extend(f"No cubierto: {value}" for value in plan.uncovered_requirements)
    lines.extend(f"Limitación: {value}" for value in state["limitations"])
    return "\n".join(lines)


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
