r"""From agent-server (real provider calls):

    uv run python src/test-agents/run_maintainability_manager.py C:\repos\project

Uses YAML model settings, .env credentials and optional existing LangSmith tracing.
--request and --config accept JSON. The audited repository remains read-only.
"""

import argparse
import asyncio
from pathlib import Path
from types import SimpleNamespace

from run_architecture_boundary import load_test_model, run_audit

from server.agents.maintainability.manager import (
    MaintainabilityConfig,
    MaintainabilityManagerAgent,
    MaintainabilityRequest,
)
from server.config.runner import load_runner_config
from server.runtimes.repository.model_runtime import close_model_clients


async def run(args):
    request = MaintainabilityRequest.model_validate_json(Path(args.request).read_text(encoding="utf-8")) if args.request else MaintainabilityRequest()
    config, token_policy = load_runner_config(MaintainabilityConfig, args.config)
    model, settings = load_test_model(args.agent_config)
    try:
        await run_audit(args, Path(args.repository).resolve(), request, config, model, settings, agent_class=MaintainabilityManagerAgent, token_policy=token_policy)
    finally:
        await close_model_clients(SimpleNamespace(llm=model))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository")
    parser.add_argument("--agent-config", default="dummy")
    parser.add_argument("--request")
    parser.add_argument("--config")
    parser.add_argument("--max-files", type=int, default=2000)
    asyncio.run(run(parser.parse_args()))
