r"""Ejecutar desde agent-server (PowerShell):

    uv run python src/test-agents/run_architecture_boundary.py C:\repos\proyecto

Requisitos: LLM_API_KEY en el .env de la raíz del repositorio y un modelo con
tool calling en config/dev-agents.yaml. Por defecto usa agents.dummy.
Para otra entrada del YAML: --agent-config NOMBRE.
Opcionales: --request solicitud.json --config limites.json --max-files 2000.
Tracing opcional: LANGSMITH_API_KEY y LANGSMITH_PROJECT en el mismo .env.
Con clave, LangSmithTracingBackend registra el agente, grafo, nodos y llamadas LLM.
Sin clave, ejecuta normalmente sin tracing. Para ocultar código/prompts en las
trazas: LANGSMITH_HIDE_INPUTS=true y LANGSMITH_HIDE_OUTPUTS=true en el .env.
Realiza llamadas reales al proveedor (pueden generar costes). Imprime JSON y no
escribe en el repositorio auditado. Ver --help para todas las opciones.
"""

import argparse
import asyncio
import json
from pathlib import Path

from langchain.chat_models import init_chat_model
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from server.agents.maintainability.modularity.architecture_boundary import (
    ArchitectureBoundaryAgent,
    AuditRequest,
    BoundaryConfig,
)
from server.app.tracing_port import LangSmithTracingBackend, TracingBackend
from server.config.dev_agents_config import load_dev_agents_config
from server.config.runner import load_runner_config
from server.config.settings import ENV_FILE
from server.config.token_budget import using_token_budget_policy
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
    config, token_policy = load_runner_config(BoundaryConfig, args.config)
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
    # This standalone harness is also reused by the responsibility test runner.
    agent_class = agent_class if agent_class is not None else ArchitectureBoundaryAgent
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
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository")
    parser.add_argument("--agent-config", default="dummy", help="Agent entry in config/dev-agents.yaml (default: dummy)")
    parser.add_argument("--request", help="JSON AuditRequest, including context and criteria")
    parser.add_argument("--config", help="JSON BoundaryConfig, including limits and prompt overrides")
    parser.add_argument("--max-files", type=int, default=2000)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
