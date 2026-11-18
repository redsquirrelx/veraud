"""CLI for the TestabilityProbeAgent.

Subcommands:
  generate  Read a testability investigation export and produce a portable suite ZIP.
  validate  Execute an existing suite ZIP against a checkout (no LLM involved).
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .agent import TestabilityProbeAgent
from .config import TestabilityProbeConfig
from .llm_client import ProviderProbeLLMClient
from .schemas import ProbeRequest


def _enable_tracing() -> None:
    """Opt-in LangSmith tracing for local runs; never block the CLI on bad config."""
    try:
        from server.config import tracing as tracing_config
        tracing_config.setup()
    except Exception as error:  # noqa: BLE001 - CLI is still usable without tracing
        print(f"warning: tracing disabled ({error})", file=sys.stderr)


def _print_json(payload: dict) -> None:
    sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--no-install", action="store_true", help="Disable Node dependency downloads.")
    parser.add_argument("--agent-config", default="dummy",
                        help="Entry in config/dev-agents.yaml to use (default: dummy).")
    parser.add_argument("--allow-local-unsafe-execution", action="store_true",
                        help="Run generated tests in a disposable copy of the audited repo. NOT a sandbox; trusted fixtures only.")
    parser.add_argument("--green-control-dir", default=None,
                        help="Checkout with the denounced condition removed (counter-example) for RED+GREEN validation.")
    parser.add_argument("--temperature", type=float, default=None,
                        help="Override the dev-agents.yaml temperature for this run.")
    parser.add_argument("--json", action="store_true", help="Print the result as JSON to stdout.")


def _generate(args) -> int:
    config_kwargs = {"allow_local_unsafe_execution": args.allow_local_unsafe_execution,
                     "auto_install_node_dependencies": not args.no_install}
    if args.green_control_dir:
        config_kwargs["green_control_dir"] = args.green_control_dir
    if args.temperature is not None:
        config_kwargs["provider_temperature_override"] = args.temperature
    config = TestabilityProbeConfig(**config_kwargs)
    try:
        llm = ProviderProbeLLMClient(config, args.agent_config)
    except ValueError as error:
        message = f"LLM unavailable: {error}"
        _print_json({"ok": False, "termination_reason": "llm_unavailable", "errors": [message]}) if args.json else print(message)
        return 2
    request = ProbeRequest(
        findings_path=args.findings,
        repo_path=args.repo,
        architecture_context_path=args.architecture_context,
        output_path=args.output,
        audit_id=args.audit_id,
        green_control_dir=args.green_control_dir,
    )
    agent = TestabilityProbeAgent(config, llm)
    result = asyncio.run(agent.run(request))
    payload = result.model_dump(mode="json")
    if args.json:
        _print_json(payload)
    else:
        print(f"[testability-probe] termination={result.termination_reason} findings={result.total_findings} "
              f"verifications={len(result.verifications)} validation={result.validation_status}")
        print(f"  ZIP: {result.output_zip}")
        for item in result.verifications:
            print(f"  {item.verification_id} -> {item.finding_id}: {item.outcome}")
        if result.limitations:
            print(f"  limitations: {len(result.limitations)} (see result JSON)")
    return 0 if result.ok else 1


def _validate(args) -> int:
    from .validate import SuiteValidationError, validate_zip

    config = TestabilityProbeConfig(auto_install_node_dependencies=not args.no_install)
    try:
        report = validate_zip(Path(args.zip), Path(args.repo), Path(args.green_control_dir) if args.green_control_dir else None,
                              config, target_commit=args.target_commit)
    except SuiteValidationError as error:
        message = f"Validation failed: {error}"
        _print_json({"action": "execute", "ok": False, "error": message}) if args.json else print(message)
        return 2
    report["ok"] = True
    if args.json:
        _print_json(report)
    else:
        print(f"[testability-probe] suite={report.get('suite_id')} baseline={report.get('baseline_commit')} "
              f"validated_red_green={sum(1 for item in report.get('verifications', []) if item.get('validated_red_green'))}")
    return 0


def main() -> int:
    _enable_tracing()
    parser = argparse.ArgumentParser(prog="testability-probe", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser("generate", help="Generate a portable verification suite from testability findings.")
    generate.add_argument("--findings", required=True, help="Testability investigation result JSON (artifacts/test-*.json).")
    generate.add_argument("--repo", required=True, help="Checkout of the audited repository (read-only; never modified).")
    generate.add_argument("--architecture-context", default=None, help="Optional architecture_context.json for complementary context.")
    generate.add_argument("--output", required=True, help="Output directory (or target .zip path).")
    generate.add_argument("--audit-id", default=None, help="Identifier recorded in the manifest (default: repository_id).")
    _add_common(generate)
    generate.set_defaults(func=_generate)

    validate = sub.add_parser("validate", help="Execute a previously exported suite ZIP against a checkout (no LLM).")
    validate.add_argument("--zip", required=True, help="Path to the exported suite ZIP.")
    validate.add_argument("--repo", required=True, help="Checkout to run the suite against.")
    validate.add_argument("--green-control-dir", default=None, help="Optional corrected checkout for RED/GREEN validation.")
    validate.add_argument("--target-commit", default=None, help="Execute an immutable snapshot of this commit instead of the working tree.")
    validate.add_argument("--json", action="store_true")
    validate.add_argument("--no-install", action="store_true")
    validate.set_defaults(func=_validate)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
