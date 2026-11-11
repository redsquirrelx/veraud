r"""Ejecutar desde agent-server (PowerShell):

    uv run python src/test-agents/run_responsibility_doc_driven.py C:\repos\proyecto

Requiere LLM_API_KEY en el .env y un modelo en config/dev-agents.yaml.
Por defecto usa agents.dummy. El runner ejecuta el grafo completo:
plan_investigation, bucles de investigate, synthesis y finalize.
Opcionales: --request, --config, --max-files, --max-output-tokens, --architecture-context,
--output json/readable, --output-file.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from langchain.chat_models import init_chat_model
from langgraph.graph import END, START, StateGraph
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from server.agent_services.budgeting.policy import (
    token_budget_policy,
    using_token_budget_policy,
)
from server.agents.architecture_context import ArchitectureContextResult
from server.agents.maintainability.v2.modularity.responsibility_doc_driven import (
    AuditRequest,
    ResponsibilityAgent,
    ResponsibilityConfig,
)
from server.agents.maintainability.v2.modularity.responsibility_doc_driven.execution import (
    ResponsibilityExecution,
)
from server.agents.maintainability.v2.modularity.responsibility_doc_driven.state import (
    ResponsibilityState,
)
from server.config.dev_agents_config import load_dev_agents_config
from server.config.settings import ENV_FILE
from server.infrastructure.tracing import LangSmithTracingBackend
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


class InvestigationOnlyExecution(ResponsibilityExecution):
    """Runner-only full graph; normal graph unchanged."""

    def _build_graph(self):
        graph = StateGraph(ResponsibilityState)
        graph.add_node("plan_investigation", phase_node("plan_investigation", self.plan_investigation))
        graph.add_node("investigate", phase_node("investigate", self.investigate))
        graph.add_node("tools", phase_node("tools", self.execute_investigation_tools))
        graph.add_node("synthesis", phase_node("synthesis", self.synthesis))
        graph.add_node("finalize", phase_node("finalize", self.finalize))
        graph.add_edge(START, "plan_investigation")
        graph.add_edge("plan_investigation", "investigate")
        graph.add_conditional_edges("investigate", self.route_investigation,
            {"tools": "tools", "investigate": "investigate", "synthesis": "synthesis"})
        graph.add_edge("tools", "investigate")
        graph.add_edge("synthesis", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()

    async def provider_request(self, model, messages, overhead, node, schema, reserved_calls):
        response = await super().provider_request(model, messages, overhead, node, schema, reserved_calls)
        if response is not None:
            raw = response.get("raw") if isinstance(response, dict) else response
            print(f"[DEBUG_LLM_RAW {node}] {getattr(raw, 'content', raw)}", file=sys.stderr)
        return response


class InvestigationOnlyResponsibilityAgent(ResponsibilityAgent):
    execution_type = InvestigationOnlyExecution


async def run(args):
    root = Path(args.repository).resolve()
    request = AuditRequest.model_validate_json(Path(args.request).read_text(encoding="utf-8")) if args.request else AuditRequest()
    if args.architecture_context is not None:
        path = Path(args.architecture_context).expanduser()
        request = request.model_copy(update={"documented_architecture":
            ArchitectureContextResult.model_validate_json(path.read_text(encoding="utf-8"))})
    config = ResponsibilityConfig.model_validate_json(
        Path(args.config).read_text(encoding="utf-8")) if args.config else ResponsibilityConfig()
    if args.max_output_tokens is not None:
        config = ResponsibilityConfig.model_validate({**config.model_dump(), "max_output_tokens": args.max_output_tokens})
    model, settings = load_test_model(args.agent_config)
    try:
        snapshot = await RepositoryAnalysisService().analyze(RepositoryAnalysisInput(
            root_path=str(root), max_files=args.max_files, max_total_bytes=16_000_000))
        budget = ExecutionBudget(
            max_model_calls=config.max_model_calls, max_tool_calls=max(1, config.max_tool_calls),
            max_total_tokens=config.max_total_tokens, max_tokens_per_objective=config.max_total_tokens,
            max_input_tokens_per_call=max(500, config.max_context_characters // 2),
            max_output_tokens_per_call=config.max_output_tokens, max_elapsed_seconds=config.timeout_seconds)
        tools = RepositoryToolset(RepositoryContext(snapshot, RepositoryInput(
            snapshot_hash=snapshot.repository.snapshot_hash, budget=budget)),
            workspace_root=root.parent, limits=ToolLimits(compact=True))
        with using_token_budget_policy(token_budget_policy()):
            result = await LangSmithTracingBackend().wrap_stage(
                InvestigationOnlyResponsibilityAgent(model, config).run(tools, request),
                name="responsibility", agent_type="responsibility",
                repository_id=snapshot.repository.name, commit=snapshot.repository.commit,
                snapshot_hash=snapshot.repository.snapshot_hash,
                provider=settings.provider, model=settings.name)
        serialized = json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2)
        if args.output_file:
            Path(args.output_file).write_text(serialized + "\n", encoding="utf-8")
        if args.output == "json" or getattr(args, "json", False):
            print(serialized)
        else:
            header = (f"Responsibility synthesis: {result.termination_reason} candidates={len(result.candidates)} "
                f"investigations={len(result.investigation_results)}")
            lines = [header]
            for item in result.investigation_results:
                lines.append(f"- {item.investigation_id}: {item.status} evidence={len(item.evidence_ids)} "
                    f"candidates={len(item.candidates)}")
                lines.append(f"  summary={item.summary}")
            lines.extend(f"limit: {item}" for item in result.limitations)
            print("\n".join(lines))
    finally:
        await close_model_clients(SimpleNamespace(llm=model))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository")
    parser.add_argument("--agent-config", default="dummy")
    parser.add_argument("--request")
    parser.add_argument("--config")
    parser.add_argument("--architecture-context", type=Path)
    parser.add_argument("--max-files", type=int, default=2000)
    parser.add_argument("--max-output-tokens", type=int)
    parser.add_argument("--output", choices=("readable", "json"), default="readable")
    parser.add_argument("--json", action="store_true", help="Return the full result as JSON (alias of --output json)")
    parser.add_argument("--output-file")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
