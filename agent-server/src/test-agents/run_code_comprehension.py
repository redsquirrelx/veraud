r"""Run from agent-server (PowerShell):

    uv run python src/test-agents/run_code_comprehension.py C:\repos\sample
    uv run python src/test-agents/run_code_comprehension.py src/test-agents/fixtures/code_comprehension

Uses the existing config/dev-agents.yaml model entry (--agent-config dummy by default).
LLM_API_KEY is required by the shared runner. Real provider calls may incur costs.
--request accepts a CodeComprehensionRequest, including optional existing typed
orientation/architecture/semantic_validation representations. --config sets limits.
--output readable (default) explains conclusions, findings, evidence and pending work.
--output raw prints the complete original result as JSON. Neither mode calls another LLM.
Does not execute or modify audited repository code. Offline tests need no API key.
"""

import argparse
import asyncio
from pathlib import Path
from types import SimpleNamespace

from code_comprehension_output import format_result
from run_architecture_boundary import load_test_model, run_audit

from server.agents.maintainability.analysability.code_comprehension import (
    CodeComprehensionAgent,
    CodeComprehensionConfig,
    CodeComprehensionRequest,
)
from server.config.runner import load_runner_config
from server.runtimes.repository.model_runtime import close_model_clients


async def run(args):
    root = Path(args.repository).resolve()
    request = CodeComprehensionRequest.model_validate_json(
        Path(args.request).read_text(encoding="utf-8"),
    ) if args.request else CodeComprehensionRequest()
    config, token_policy = load_runner_config(CodeComprehensionConfig, args.config)
    model, settings = load_test_model(args.agent_config)
    try:
        await run_audit(args, root, request, config, model, settings,
            agent_class=CodeComprehensionAgent, token_policy=token_policy,
            result_formatter=lambda result: format_result(result, getattr(args, "output", "readable")))
    finally:
        await close_model_clients(SimpleNamespace(llm=model))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repository")
    parser.add_argument("--agent-config", default="dummy")
    parser.add_argument("--request", help="CodeComprehensionRequest, with optional existing project representations")
    parser.add_argument("--config", help="Developer execution limits and prompt overrides")
    parser.add_argument("--max-files", type=int, default=2000)
    parser.add_argument("--output", choices=("readable", "raw"), default="readable",
        help="Console output: readable conclusions (default) or complete raw JSON")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
