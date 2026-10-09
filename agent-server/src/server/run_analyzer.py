"""DEV-ONLY runner for the analyzer agent.

Any of these works, from anywhere:

    uv run --no-sync python -m server.run_analyzer ../appdata/workspace/123-owner-repo
    python src/server/run_analyzer.py ../appdata/workspace/123-owner-repo
    uv run --no-sync analyzer ../appdata/workspace/123-owner-repo

Needs no .env and no particular cwd: the analyzer never reaches settings
unless it has to build a model client, and --no-model skips that entirely.
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

from server.agents.analyzer import facts as fact_tools
from server.agents.analyzer.agent import MAX_FACTS_CHARS, ProjectAnalyzerAgent
from server.agents.analyzer.evidence import (
    MAX_CHARS_PER_RUN,
    read_excerpts,
    render_excerpts,
)
from server.agents.analyzer.schemas import ProjectDescription
from server.api.schemas import ExecutionConfig
from server.app.agent_registry import AgentRegistry
from server.app.execution_service import (
    AgentExecutionService,
    InvalidConfigError,
    InvalidInputError,
)

logger = logging.getLogger("run-analyzer")


class _BadArguments(Exception):
    """The arguments on the command line do not make sense."""


class _NoSuchRepository(Exception):
    """The path given is not a repository the analyzer can read."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_analyzer",
        description=(
            "Describe a repository with the analyzer agent: what kind of "
            "project it is, its entry points and its key components."
        ),
    )
    parser.add_argument("root", help="Repository root to describe")
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
        help="How many times the agent may read more files (default: 2)",
    )
    parser.add_argument(
        "--files-per-round",
        type=int,
        default=8,
        help="Files the model may pick per round (default: 8)",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Model provider. Defaults to dev-agents.yaml.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name. Defaults to dev-agents.yaml.",
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
        help="Sampling temperature. Defaults to dev-agents.yaml.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Seconds before giving up. Defaults to dev-agents.yaml.",
    )
    parser.add_argument(
        "--facts",
        action="store_true",
        help="Print the collected facts instead of the description",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the ProjectDescription as JSON",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Collect and print the prompt without calling a model",
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
        if args.dry_run:
            return _dry_run(args)
        if args.facts:
            return _facts(args)
        return _describe(args)
    except _BadArguments as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except _NoSuchRepository as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


# -- modes -----------------------------------------------------------------


def _describe(args) -> int:
    """Full run: describe the repository with the analyzer agent."""
    payload = {
        "root_path": args.root,
        "max_files": args.max_files,
        "max_depth": args.max_depth,
        "max_read_rounds": args.rounds,
        "max_files_per_round": args.files_per_round,
    }

    config = ExecutionConfig(
        model={
            "provider": args.provider,
            "name": args.model,
            "temperature": args.temperature,
        },
        timeout_seconds=args.timeout,
        api_key=args.api_key,
    )

    registry = AgentRegistry()
    registry.register(ProjectAnalyzerAgent.agent_type, ProjectAnalyzerAgent)
    service = AgentExecutionService(registry=registry)

    try:
        result = asyncio.run(service.run(
            ProjectAnalyzerAgent.agent_type,
            config,
            payload,
        ))
    except InvalidInputError as error:
        print(f"error: invalid input\n{error}", file=sys.stderr)
        return 2
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except InvalidConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except TimeoutError:
        print("error: the analyzer timed out", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))
        return 0

    _print_description(result)
    return 0


def _facts(args) -> int:
    """Just the collected facts, no model involved."""
    facts, trimmed, _root, _files = _collected_facts(args)

    print(facts)
    print()
    print(f"prompt chars: {len(facts)} | trimmed: {trimmed}")
    return 0


def _dry_run(args) -> int:
    """Render every prompt the graph will send, without calling a model.

    Reads what the analyzer would read, so the prompts can be checked against
    the repository without spending a single call.
    """
    from server.config.prompts import load_prompt, render_prompt

    facts, trimmed, root, files = _collected_facts(args)
    entrypoints = fact_tools.entrypoint_candidates(files)[: args.files_per_round]
    excerpts = render_excerpts(read_excerpts(root, entrypoints, MAX_CHARS_PER_RUN))

    values = {
        "hypothesize": {"facts": facts},
        "select": {
            "max_paths": args.files_per_round,
            "read_paths": _bullets(entrypoints),
            "excerpts": excerpts,
        },
        "verify": {
            "hypothesis": json.dumps({"kind": "library", "reasoning": "..."}, indent=2),
            "excerpts": excerpts,
        },
        "synthesize": {
            "facts": facts,
            "excerpts": excerpts,
            "read_paths": _bullets(entrypoints),
            "rounds": 1,
            "files_read": len(entrypoints),
            "verdict": "not confirmed",
        },
    }

    for name, filled in values.items():
        print("=" * 70)
        print(f"prompts/analyzer/{name}.md")
        print("=" * 70)

        try:
            print(render_prompt(load_prompt("analyzer", name), **filled))
        except KeyError as error:
            print(
                f"error: prompt {name!r} declares a placeholder nothing fills: {error}",
                file=sys.stderr,
            )
            return 1

        print()

    print("=" * 70)
    print(f"facts chars: {len(facts)} | trimmed: {trimmed} | files: {len(files)}")
    print(f"would read {len(entrypoints)} entry point candidate(s)")
    print("no model was called")
    return 0


def _collected_facts(args) -> tuple[str, bool, Path, list[dict]]:
    """Collect, condense, and hand back what the prompts are built from."""
    collection = _collect(args)
    data = collection.model_dump()
    facts, trimmed = fact_tools.build_facts(data, MAX_FACTS_CHARS)

    return facts, trimmed, Path(collection.root), data.get("repo_map", {}).get("files", [])


def _bullets(paths: list[str]) -> str:
    return "\n".join(f"- {path}" for path in paths) or "(none)"


def _collect(args):
    """Collect the representations, or raise with the message to show."""
    from server.services.collection.schemas import CollectionInput
    from server.services.collection.service import CollectionService

    try:
        payload = CollectionInput(
            root_path=args.root,
            max_files=args.max_files,
            max_depth=args.max_depth,
        )
    except ValidationError as error:
        raise _BadArguments(f"invalid arguments\n{error}") from error

    try:
        return asyncio.run(CollectionService().collect(payload))
    except FileNotFoundError as error:
        raise _NoSuchRepository(str(error)) from error
    except ValidationError as error:
        raise _BadArguments(f"invalid arguments\n{error}") from error


# -- output ----------------------------------------------------------------


def _print_description(description: ProjectDescription) -> None:
    print(f"kind              : {description.kind}")
    print(f"primary_language  : {description.primary_language}")
    print(f"confidence        : {description.confidence}")
    print(f"evidence          : {description.files_read} file(s) read "
          f"in {description.read_rounds} round(s), "
          f"hypothesis {'confirmed' if description.hypothesis_confirmed else 'not confirmed'}")
    print()
    print("summary:")
    for line in _wrap(description.summary, 76):
        print(f"  {line}")
    print()

    print(f"entrypoints ({len(description.entrypoints)}):")
    for item in description.entrypoints or ["(none reported)"]:
        print(f"  {item}")

    print()
    print(f"key_components ({len(description.key_components)}):")
    for item in description.key_components or ["(none reported)"]:
        print(f"  {item}")


def _wrap(text: str, width: int) -> list[str]:
    return textwrap.wrap(text, width=width) or [""]


if __name__ == "__main__":
    raise SystemExit(main())