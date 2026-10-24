r"""From agent-server (paid provider calls, read-only):

    uv run python src/test-agents/run_reuse_opportunity.py C:\repos\project

YAML: config/dev-agents.yaml (--agent-config dummy by default); credentials: root
.env LLM_API_KEY. Optional LangSmith tracing uses the shared investigator harness.
Set LANGSMITH_HIDE_INPUTS=true/LANGSMITH_HIDE_OUTPUTS=true to hide source/results.
"""

import argparse
import asyncio
from pathlib import Path
from types import SimpleNamespace

from run_architecture_boundary import load_test_model, run_audit

from server.agents.maintainability.reusability.reuse_opportunity import (
    ReuseOpportunityAgent,
    ReuseOpportunityConfig,
    ReuseOpportunityRequest,
)
from server.config.runner import load_runner_config
from server.runtimes.repository.model_runtime import close_model_clients


async def run(args):
    request = ReuseOpportunityRequest.model_validate_json(Path(args.request).read_text(encoding="utf-8")) if args.request else ReuseOpportunityRequest()
    config, token_policy = load_runner_config(ReuseOpportunityConfig, args.config)
    model, settings = load_test_model(args.agent_config)
    try:
        await run_audit(args, Path(args.repository).resolve(), request, config, model, settings, agent_class=ReuseOpportunityAgent, token_policy=token_policy)
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
