r"""From agent-server (real provider calls may incur costs; audited source is read-only):

    uv run python src/test-agents/run_component_adaptability.py C:\repos\project

Uses config/dev-agents.yaml (--agent-config dummy by default), root .env credentials
and existing LangSmith tracing. --request accepts targets/component_ids/target_context;
--config accepts shared budgets, provider quotas and agent-specific discovery bounds.
Use LANGSMITH_HIDE_INPUTS=true/LANGSMITH_HIDE_OUTPUTS=true to hide source/results.
"""

import argparse
import asyncio
from pathlib import Path
from types import SimpleNamespace

from run_architecture_boundary import load_test_model, run_audit

from server.agents.maintainability.reusability.component_adaptability import (
    ComponentAdaptabilityAgent,
    ComponentAdaptabilityConfig,
    ComponentAdaptabilityRequest,
)
from server.config.runner import load_runner_config
from server.runtimes.repository.model_runtime import close_model_clients


async def run(args):
    request = ComponentAdaptabilityRequest.model_validate_json(Path(args.request).read_text(encoding="utf-8")) if args.request else ComponentAdaptabilityRequest()
    config, token_policy = load_runner_config(ComponentAdaptabilityConfig, args.config)
    model, settings = load_test_model(args.agent_config)
    try:
        await run_audit(args, Path(args.repository).resolve(), request, config, model, settings, agent_class=ComponentAdaptabilityAgent, token_policy=token_policy)
    finally:
        await close_model_clients(SimpleNamespace(llm=model))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repository")
    parser.add_argument("--agent-config", default="dummy")
    parser.add_argument("--request")
    parser.add_argument("--config")
    parser.add_argument("--max-files", type=int, default=2000)
    asyncio.run(run(parser.parse_args()))
