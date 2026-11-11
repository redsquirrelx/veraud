r"""Run ReuseOpportunityDocDrivenAgent V2 through planning and investigate/tools.

    uv run python src/test-agents/run_reuse_opportunity_doc_driven.py C:\repos\project \
      --architecture-context architecture-context.json --output json

This runner stops before synthesis or finding finalization; investigation evidence is returned.
"""

import argparse
import asyncio
import json
from pathlib import Path

from run_architecture_boundary_doc_driven import load_test_model

from server.agent_services.budgeting.policy import (
    token_budget_policy,
    using_token_budget_policy,
)
from server.agents.architecture_context import ArchitectureContextResult
from server.agents.maintainability.v2.reusability.reuse_opportunity_doc_driven import (
    ReuseOpportunityDocDrivenAgent,
    ReuseOpportunityDocDrivenRequest,
)
from server.config.runner import load_runner_config
from server.infrastructure.tracing import LangSmithTracingBackend
from server.runtimes.repository.context import RepositoryContext
from server.runtimes.repository.model_runtime import close_model_clients
from server.runtimes.repository.schemas import ExecutionBudget, RepositoryInput
from server.runtimes.repository.tools import RepositoryToolset, ToolLimits
from server.services.repository_analysis import (
    RepositoryAnalysisInput,
    RepositoryAnalysisService,
)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("repository")
    result.add_argument("--architecture-context", type=Path, required=True)
    result.add_argument("--agent-config", default="dummy")
    result.add_argument("--config")
    result.add_argument("--max-files", type=int, default=2000)
    result.add_argument("--output", choices=("readable", "json"), default="readable")
    result.add_argument("--output-file")
    return result


async def run(args):
    root = Path(args.repository).expanduser().resolve()
    config, _ = load_runner_config(ReuseOpportunityDocDrivenAgent.config_type, args.config)
    architecture = ArchitectureContextResult.model_validate_json(
        args.architecture_context.expanduser().read_text(encoding="utf-8"))
    request = ReuseOpportunityDocDrivenRequest(documented_architecture=architecture)
    snapshot = await RepositoryAnalysisService().analyze(RepositoryAnalysisInput(
        root_path=str(root), max_files=args.max_files, max_total_bytes=16_000_000))
    budget = ExecutionBudget(
        max_model_calls=config.max_model_calls,
        max_tool_calls=max(1, config.max_tool_calls),
        max_total_tokens=config.max_total_tokens,
        max_tokens_per_objective=config.max_total_tokens,
        max_input_tokens_per_call=max(500, config.max_context_characters // 2),
        max_output_tokens_per_call=config.max_output_tokens,
        max_elapsed_seconds=config.timeout_seconds,
    )
    tools = RepositoryToolset(
        RepositoryContext(snapshot, RepositoryInput(
            snapshot_hash=snapshot.repository.snapshot_hash, budget=budget)),
        workspace_root=root.parent,
        limits=ToolLimits(compact=True),
    )
    model, settings = load_test_model(args.agent_config)
    agent = ReuseOpportunityDocDrivenAgent(model, config)
    try:
        with using_token_budget_policy(token_budget_policy()):
            output = await LangSmithTracingBackend().wrap_stage(
                agent.run(tools, request),
                name=agent.trace_name,
                agent_type=agent.agent_type,
                repository_id=snapshot.repository.name,
                commit=snapshot.repository.commit,
                snapshot_hash=snapshot.repository.snapshot_hash,
                provider=settings.provider,
                model=settings.name,
            )
    finally:
        from types import SimpleNamespace
        await close_model_clients(SimpleNamespace(llm=model))
    serialized = json.dumps(output.model_dump(mode="json"), ensure_ascii=False, indent=2)
    if args.output_file:
        Path(args.output_file).expanduser().write_text(serialized + "\n", encoding="utf-8")
    if args.output == "json":
        print(serialized)
    else:
        print(f"Reuse opportunity investigator: {output.status} ({output.termination_reason})")
        print(f"Investigations: {len(output.investigation_results)}  Candidates: {len(output.candidates)}")
        for result in output.investigation_results:
            print(f"- [{result.status}] {result.summary}")
        for limitation in output.limitations:
            print(f"limitation: {limitation}")
    return output


if __name__ == "__main__":
    asyncio.run(run(parser().parse_args()))
