"""DEV-ONLY runner for the analyzer + architect pipeline.

Any of these works, from anywhere:

    uv run --no-sync python -m server.run_pipeline ../appdata/workspace/123-owner-repo
    python src/server/run_pipeline.py ../appdata/workspace/123-owner-repo
    uv run pipeline ../appdata/workspace/123-owner-repo

Runs the analyzer first and feeds its output straight into the architect, so
one invocation shows the whole describe-then-frame flow. Needs a model
credential: LLM_API_KEY from .env, or --api-key.

Timeouts and model settings apply to both agents. Anything agent-specific
still belongs to run_analyzer.py.
"""

import argparse
import asyncio
import json
import logging
import sys
import textwrap
from pathlib import Path

from pydantic import ValidationError

if __package__ in (None, ""):
    # Launched by path: no package context, so make `server` importable.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.api.schemas import ExecutionConfig
from server.app.execution_service import (
    AgentExecutionService,
    InvalidConfigError,
    build_default_registry,
)
from server.pipelines.architecture_audit import ArchitectureAuditPipeline

logger = logging.getLogger("run-pipeline")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_pipeline",
        description=(
            "Audit a repository with the analyzer then the architect: what kind "
            "of project it is, then how it is put together."
        ),
    )
    parser.add_argument("root", help="Repository root to audit")
    parser.add_argument(
        "--max-files",
        type=int,
        default=500,
        help="Cap per representation when collecting (default: 500)",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=8,
        help="Maximum directory depth to walk (default: 8)",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=2,
        help="How many times the analyzer may read more files (default: 2)",
    )
    parser.add_argument(
        "--files-per-round",
        type=int,
        default=8,
        help="Files the analyzer may pick per round (default: 8)",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Model provider for both agents. Defaults to dev-agents.yaml.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name for both agents. Defaults to dev-agents.yaml.",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help=(
            "Model credential. Defaults to LLM_API_KEY from .env. "
            "Prefer the env var over passing it on the command line, "
            "where it lands in your shell history."
        ),
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="Sampling temperature for both agents. Defaults to dev-agents.yaml.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Seconds before giving up on the whole pipeline (default: 600)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the analysis and the description as JSON",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Silence logging",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.quiet:
        logging.disable(logging.CRITICAL)
    else:
        from server.config.logs import setup_logging

        setup_logging()

    try:
        return asyncio.run(_audit(args))
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except (InvalidConfigError, ValidationError) as error:
        print(f"error: invalid config\n{error}", file=sys.stderr)
        return 2
    except TimeoutError:
        print("error: the pipeline timed out", file=sys.stderr)
        return 1


async def _audit(args) -> int:
    config = ExecutionConfig(
        model={
            "provider": args.provider,
            "name": args.model,
            "temperature": args.temperature,
        },
        api_key=args.api_key,
    )

    service = AgentExecutionService(registry=build_default_registry())
    analyzer, _ = service.build_agent("analyzer", config)
    architect, _ = service.build_agent("architect", config)
    pipeline = ArchitectureAuditPipeline(analyzer, architect)

    try:
        result = await asyncio.wait_for(
            pipeline.run(
                args.root,
                max_files=args.max_files,
                max_depth=args.max_depth,
                max_read_rounds=args.rounds,
                max_files_per_round=args.files_per_round,
            ),
            timeout=args.timeout,
        )
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    _print_audit(result)
    return 0


def _print_audit(result: dict) -> None:
    analysis = result.get("analysis", {})

    print("analysis:")
    print(f"  kind              : {analysis.get('kind', 'unknown')}")
    print(f"  primary_language  : {analysis.get('primary_language', 'unknown')}")
    print(f"  confidence        : {analysis.get('confidence', 'low')}")
    print()
    print("  summary:")
    for line in _wrap(str(analysis.get("summary", "")), 76):
        print(f"    {line}")
    print()

    components = analysis.get("key_components") or ["(none reported)"]
    print(f"  key_components ({len(analysis.get('key_components') or [])}):")
    for item in components:
        print(f"    {item}")
    print()

    description = result.get("description", {})
    print("architecture:")
    print(f"  style             : {description.get('style', 'unknown')}")
    print(f"  intended          : {description.get('intended_style', 'unknown')}")
    print()

    deviations = description.get("deviations") or []
    print(f"  deviations ({len(deviations)}):")
    for deviation in deviations or ["(none reported)"]:
        if isinstance(deviation, dict):
            print(f"    - {deviation.get('observation', '')}")
            for path in deviation.get("evidence", []):
                print(f"      evidence: {path}")
        else:
            print(f"    {deviation}")
    print()

    described = description.get("components") or []
    print(f"  components ({len(described)}):")
    for item in described or ["(none reported)"]:
        if isinstance(item, dict):
            responsibility = item.get("responsibility") or "(not described)"
            print(f"    {item.get('path')}: {responsibility}")
        else:
            print(f"    {item}")
    print()

    print("  data_flow:")
    for line in _wrap(str(description.get("data_flow", "") or "(not traced)"), 76):
        print(f"    {line}")
    print()

    third_party = description.get("third_party") or []
    print(f"  third_party       : {', '.join(third_party) if third_party else '(none)'}")
    cycles = description.get("cycles") or []
    print(f"  cycles            : {len(cycles)} group(s)")
    for group in cycles:
        print(f"    {' ↔ '.join(group)}")
    print()

    notes = description.get("quality_notes") or []
    print(f"  quality_notes ({len(notes)}):")
    for note in notes or ["(none reported)"]:
        if isinstance(note, dict):
            print(f"    - [{note.get('characteristic', '?')}] {note.get('observation', '')}")
            for path in note.get("evidence", []):
                print(f"      evidence: {path}")
        else:
            print(f"    {note}")
    print()

    risks = description.get("risks") or []
    print(f"  risks ({len(risks)}):")
    for risk in risks or ["(none reported)"]:
        print(f"    - {risk}")


def _wrap(text: str, width: int) -> list[str]:
    return textwrap.wrap(text, width=width) or [""]


if __name__ == "__main__":
    raise SystemExit(main())
