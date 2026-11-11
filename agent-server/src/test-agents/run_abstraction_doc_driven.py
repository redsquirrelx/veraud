r"""Run the AbstractionAgent V2 end to end.

    uv run python src/test-agents/run_abstraction_doc_driven.py C:\repos\project

Executes plan_investigation, the investigate/tools loop, synthesis and finalize.
Pass --plan-only to stop after plan_investigation (skips the investigation loop).
Pass --through-investigate to stop after all investigate/tools loops finish (skips synthesis and finalize).
Mutually exclusive.
The global budget switch is read from launch.json and is not overridden by this runner.
"""

import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from langchain.chat_models import init_chat_model
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from server.agent_services.budgeting.policy import (
    token_budget_policy,
    using_token_budget_policy,
)
from server.agents.architecture_context import ArchitectureContextResult
from server.agents.maintainability.v2.reusability.abstraction_doc_driven import (
    AbstractionAgent,
    AbstractionConfig,
    AbstractionRequest,
)
from server.agents.maintainability.v2.reusability.abstraction_doc_driven.execution import (
    AbstractionExecution,
)
from server.config.dev_agents_config import load_dev_agents_config
from server.config.runner import load_runner_config
from server.config.settings import ENV_FILE
from server.infrastructure.tracing import LangSmithTracingBackend
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


def load_model(agent_config):
    configurations = load_dev_agents_config()
    if agent_config not in configurations:
        raise ValueError(f"No agent configuration {agent_config!r} in config/dev-agents.yaml.")
    _, settings = configurations[agent_config]
    key = RunnerCredentials(_env_file=ENV_FILE).llm_api_key.get_secret_value()
    if not key.strip():
        raise ValueError("Set LLM_API_KEY in the repository .env or environment.")
    provider = settings.provider.lower()
    kwargs = {"api_key": key, "temperature": settings.temperature, "max_tokens": 40_000, "max_retries": 0}
    if provider == "openrouter":
        provider = "openai"
        kwargs["base_url"] = "https://openrouter.ai/api/v1"
    if provider in ("gemini", "google"):
        provider = "google_genai"
    return init_chat_model(settings.name, model_provider=provider, **kwargs), settings


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("repository")
    result.add_argument("--target", action="append", default=[])
    result.add_argument("--constraint", action="append", default=[])
    result.add_argument("--architecture-context", type=Path)
    result.add_argument("--agent-config", default="dummy")
    result.add_argument("--config")
    result.add_argument("--max-files", type=int, default=2000)
    stop_after = result.add_mutually_exclusive_group()
    stop_after.add_argument("--plan-only", action="store_true",
        help="Stop after plan_investigation; skips the investigate/tools loop, synthesis and finalize.")
    stop_after.add_argument("--through-investigate", action="store_true",
        help="Stop after all investigate/tools loops close; skips synthesis and finalize.")
    result.add_argument("--output", choices=("readable", "json"), default="readable")
    result.add_argument("--output-file")
    return result


def print_readable(result):
    plan = result.plan
    print(f"Abstraction synthesis: {result.termination_reason}")
    print(f"Hypotheses: {len(result.hypotheses)}  Candidates: {len(result.candidates)}  "
        f"Findings: {len(result.findings)}  Investigations: {len(result.investigation_results)}")
    if plan:
        print(f"Plan candidates: {len(plan.candidates)}")
        for item in plan.candidates:
            print(f"- {item.abstraction_name} ({item.abstraction_kind}) primary={item.primary_component}")
            print(f"    question: {item.question}")
    for item in result.investigation_results:
        print()
        print(f"- {item.investigation_id}: {item.status}")
        print(f"    summary:   {item.summary}")
        print(f"    components: {', '.join(item.components)}")
    for finding in result.findings:
        print()
        print(f"- {finding.title} ({finding.kind}, {finding.severity}, confidence={finding.confidence})")
        print(f"    criterion: {finding.criterion_id}")
        print(f"    components: {', '.join(finding.components)}")
    print()
    for limitation in result.limitations:
        print(f"limitation: {limitation}")


async def run(args):
    root = Path(args.repository).expanduser().resolve()
    config, _policy = load_runner_config(AbstractionConfig, args.config)
    # Keep this developer control fixed, even if a runner config asks for less.
    config = config.model_copy(update={"max_output_tokens": 40_000})
    architecture = (ArchitectureContextResult.model_validate_json(
        args.architecture_context.read_text(encoding="utf-8")) if args.architecture_context else None)
    request = AbstractionRequest(targets=args.target, constraints=args.constraint,
        documented_architecture=architecture)
    model, settings = load_model(args.agent_config)
    try:
        snapshot = await RepositoryAnalysisService().analyze(RepositoryAnalysisInput(
            root_path=str(root), max_files=args.max_files, max_total_bytes=16_000_000))
        budget = ExecutionBudget(
            max_model_calls=config.max_model_calls, max_tool_calls=max(1, config.max_tool_calls),
            max_total_tokens=config.max_total_tokens, max_tokens_per_objective=config.max_total_tokens,
            max_input_tokens_per_call=max(500, config.max_context_characters // 2),
            max_output_tokens_per_call=40_000, max_elapsed_seconds=config.timeout_seconds)
        tools = RepositoryToolset(RepositoryContext(snapshot, RepositoryInput(
            snapshot_hash=snapshot.repository.snapshot_hash, budget=budget)),
            workspace_root=root.parent, limits=ToolLimits(compact=True))
        with using_token_budget_policy(token_budget_policy()):
            wrap = {"agent_type": "abstraction",
                "repository_id": snapshot.repository.name, "commit": snapshot.repository.commit,
                "snapshot_hash": snapshot.repository.snapshot_hash,
                "provider": settings.provider, "model": settings.name}
            if args.plan_only:
                async def plan_only():
                    execution = AbstractionExecution(model, config, tools, request)
                    state = execution.initial_state()
                    state = {**state, **await execution.plan_investigation(state)}
                    return state["result"]

                result = await LangSmithTracingBackend().wrap_stage(
                    plan_only(), name="abstraction-v2-planning", **wrap)
            elif args.through_investigate:
                async def investigate_only():
                    execution = AbstractionExecution(model, config, tools, request)
                    state = execution.initial_state()
                    state = {**state, **await execution.plan_investigation(state)}
                    while True:
                        route = execution.route_investigation(state)
                        if route == "tools":
                            state = {**state, **await execution.execute_investigation_tools(state)}
                        elif route == "investigate":
                            state = {**state, **await execution.investigate(state)}
                        else:
                            return state["result"]

                result = await LangSmithTracingBackend().wrap_stage(
                    investigate_only(), name="abstraction-v2-investigate", **wrap)
            else:
                result = await LangSmithTracingBackend().wrap_stage(
                    AbstractionAgent(model, config).run(tools, request),
                    name="abstraction-v2-investigator", **wrap)
        serialized = json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2)
        if args.output_file:
            Path(args.output_file).write_text(serialized + "\n", encoding="utf-8")
        if args.output == "json":
            print(serialized)
        else:
            print_readable(result)
        return result
    finally:
        await close_model_clients(SimpleNamespace(llm=model))


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
