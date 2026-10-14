r"""From agent-server (real provider calls incur possible cost; read-only audit):

    uv run python src/test-agents/run_reusability.py C:\repos\project

Uses config/dev-agents.yaml (--agent-config dummy), root .env LLM_API_KEY and optional
LangSmith tracing. --request and --config accept JSON. Set LANGSMITH_HIDE_INPUTS=true
and LANGSMITH_HIDE_OUTPUTS=true to hide source/results from tracing.
"""

import argparse
import asyncio
from pathlib import Path
from types import SimpleNamespace

from run_architecture_boundary import load_test_model, run_audit

from server.agents.maintainability.reusability import (
    ReusabilityAgent,
    ReusabilityConfig,
    ReusabilityRequest,
)
from server.agents.repository_runtime.model_runtime import close_model_clients


async def run(args):
    request = ReusabilityRequest.model_validate_json(Path(args.request).read_text(encoding="utf-8")) if args.request else ReusabilityRequest()
    config = ReusabilityConfig.model_validate_json(Path(args.config).read_text(encoding="utf-8")) if args.config else ReusabilityConfig()
    model, settings = load_test_model(args.agent_config)
    try:
        await run_audit(args, Path(args.repository).resolve(), request, config, model, settings, agent_class=ReusabilityAgent)
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
