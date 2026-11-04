r"""Execute from agent-server (PowerShell):

    uv run python src/test-agents/run_abstraction.py C:\repos\project

Uses provider/model from config/dev-agents.yaml (agents.dummy by default) and
LLM_API_KEY from the root .env. Select another entry with --agent-config NAME.
Optional: --request request.json --config limits.json --max-files 2000.
Tracing: LANGSMITH_API_KEY/LANGSMITH_PROJECT; use LANGSMITH_HIDE_INPUTS=true and
LANGSMITH_HIDE_OUTPUTS=true to hide prompts/source/results. Real provider calls
may incur costs. The audited repository is never modified.
Offline: uv run pytest src/test-agents/test_abstraction.py -q
"""

import argparse
import asyncio
from pathlib import Path
from types import SimpleNamespace

from run_architecture_boundary import load_test_model, run_audit

from server.agents.maintainability.reusability.abstraction import (
    AbstractionAgent,
    AbstractionConfig,
    AbstractionRequest,
)
from server.config.runner import load_runner_config
from server.runtimes.repository.model_runtime import close_model_clients


async def run(args):
    request = AbstractionRequest.model_validate_json(Path(args.request).read_text(encoding="utf-8")) if args.request else AbstractionRequest()
    config, token_policy = load_runner_config(AbstractionConfig, args.config)
    model, settings = load_test_model(args.agent_config)
    try:
        await run_audit(args, Path(args.repository).resolve(), request, config, model, settings, agent_class=AbstractionAgent, token_policy=token_policy)
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
