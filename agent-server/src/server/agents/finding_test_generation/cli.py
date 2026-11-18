"""Standalone CLI for the finding-test generation prototype.

    uv run python -m server.agents.finding_test_generation.cli generate \
        --findings fixtures/audit_140/findings.json \
        --repo ../appdata/workspace/1454248654-redsquirrelx-urban-mesh \
        --output ./artifacts/audit-140

Paths are never hardcoded; every input is an argument.
"""

import argparse
import asyncio
import sys

from .agent import FindingTestGenerationAgent
from .config import FindingTestConfig
from .schemas import FindingTestGenerationRequest


def _enable_tracing() -> None:
    """Opt-in LangSmith tracing for local runs; never block the CLI on bad config."""
    try:
        from server.config import tracing as tracing_config
        tracing_config.setup()
    except Exception as error:  # noqa: BLE001 - CLI is still usable without tracing
        print(f"warning: tracing disabled ({error})", file=sys.stderr)


async def _generate(args: argparse.Namespace) -> int:
    if args.green_control and not args.allow_local_unsafe_execution:
        print("[finding-test-generation] --green-control requires --allow-local-unsafe-execution", file=sys.stderr)
        return 2

    config = FindingTestConfig(allow_local_unsafe_execution=args.allow_local_unsafe_execution,
                               green_control_dir=args.green_control,
                               provider_temperature_override=args.temperature)
    llm_client = None
    if args.llm == "provider":
        try:
            from .llm_client import ProviderFindingLLMClient

            llm_client = ProviderFindingLLMClient(config, args.agent_config)
        except (ValueError, RuntimeError) as error:
            print(f"[finding-test-generation] Cannot build the LLM client: {error}", file=sys.stderr)
            return 2
    request = FindingTestGenerationRequest(
        findings_path=args.findings,
        repo_path=args.repo,
        output_path=args.output,
    )
    agent = FindingTestGenerationAgent(config=config, llm_client=llm_client)
    if args.execution_id is not None:
        from server.agent_services.execution_tracking.events import (
            execution_event_scope,
        )

        with execution_event_scope(args.execution_id):
            result = await agent.run(request)
    else:
        result = await agent.run(request)

    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        print(f"[finding-test-generation] status={'ok' if result.ok else 'failed'} reason={result.termination_reason} validation={result.validation_status}")
        if result.output_zip:
            print(f"  suite: {result.output_zip}")
            print(f"  suite_id: {result.suite_id}")
        print(f"  baseline available: {result.baseline_available}")
        if result.llm_tokens is not None:
            print(f"  llm tokens used: {result.llm_tokens}")
        if result.verification_results:
            print("  verifications:")
            for item in result.verification_results:
                print(f"    - {item.verification_id}: {item.status}")
        for spec in result.specs:
            print(f"  - {spec.verification_id} [{spec.strategy}] {spec.finding_id} -> {spec.test_path}")
        if result.limitations:
            print("  limitations:")
            for limitation in result.limitations:
                print(f"    - {limitation}")
        if result.errors:
            print("  errors:")
            for error in result.errors:
                print(f"    - {error}")
    return 0 if result.ok else 2


def main(argv: list[str] | None = None) -> int:
    _enable_tracing()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subcommands = parser.add_subparsers(dest="command", required=True)
    generate = subcommands.add_parser("generate", help="Generate the verification suite ZIP from an audit export.")
    generate.add_argument("--findings", required=True, help="Path to the audit export JSON (e.g. fixtures/audit_140/findings.json).")
    generate.add_argument("--repo", default=None, help="Optional checkout of the audited repository (enables baseline metadata).")
    generate.add_argument("--output", required=True, help="Output directory, or a .zip file path.")
    generate.add_argument("--execution-id", type=int, default=None, help="Backend execution id; enables execution event capture.")
    generate.add_argument("--json", action="store_true", help="Print the full result as JSON instead of a human summary.")
    generate.add_argument("--llm", choices=("none", "provider"), default="none",
                          help="'provider' uses config/dev-agents.yaml (dummy) to SELECT the rule per verification; "
                               "the LLM never writes or repairs test code. Needs LLM_API_KEY.")
    generate.add_argument("--agent-config", default="dummy", help="Entry in config/dev-agents.yaml when --llm=provider (default: dummy).")
    generate.add_argument("--allow-local-unsafe-execution", action="store_true",
                          help="DANGER: run the generated suite in a disposable copy of the repo on THIS machine. "
                               "Not a security sandbox; trusted fixtures only.")
    generate.add_argument("--green-control", default=None,
                          help="Path to a checkout with the violation fixed (counter-example). "
                               "Used to reject vacuous/overfitting tests: must fail at audited baseline and pass here. "
                               "Requires --allow-local-unsafe-execution.")
    generate.add_argument("--temperature", type=float, default=None,
                          help="Override dev-agents.yaml temperature for this run (0.0 = deterministic).")

    generate.set_defaults(handler=_generate)
    args = parser.parse_args(argv)
    return asyncio.run(args.handler(args))


if __name__ == "__main__":
    sys.exit(main())
