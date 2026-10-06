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
from pathlib import Path

from pydantic import ValidationError

if __package__ in (None, ""):
    # Launched by path: no package context, so make `server` importable.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.agents.analyzer.agent import ProjectAnalyzerAgent
from server.agents.analyzer.schemas import ProjectDescription, ProjectInput
from server.agents.models.base import Model
from server.agents.models.gemini import GeminiModel
from server.agents.models.openrouter import OpenRouterModel
from server.config.dev_agents_config import load_dev_agents_config
from server.config.schemas import AgentSettings, ModelCredentials, ModelSettings

logger = logging.getLogger("run-analyzer")

DEFAULT_MODEL = "gemini-3.1-flash-lite"
DEFAULT_MAX_TOKENS = 4000
DEFAULT_TIMEOUT = 120


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

    if args.dry_run:
        return _dry_run(args)
    if args.facts:
        return _facts(args)

    return _describe(args)


# -- modes -----------------------------------------------------------------


def _describe(args) -> int:
    """Full run: collect, call the model, print the description."""
    try:
        payload = ProjectInput(
            root_path=args.root,
            max_files=args.max_files,
            max_depth=args.max_depth,
        )
    except ValidationError as error:
        print(f"error: invalid arguments\n{error}", file=sys.stderr)
        return 2

    try:
        model, timeout = _build_model(args)
    except (ValueError, ValidationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    settings = AgentSettings(
        agent_id=ProjectAnalyzerAgent.agent_type,
        timeout_seconds=timeout,
    )

    agent = ProjectAnalyzerAgent(settings=settings, model=model)

    logger.info(
        "Describing %s with %s", payload.root_path,
        type(model).__name__,
    )

    try:
        result = asyncio.run(asyncio.wait_for(agent.run(payload), timeout))
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except ValidationError as error:
        print(f"error: invalid input\n{error}", file=sys.stderr)
        return 2
    except TimeoutError:
        print(f"error: the analyzer timed out after {timeout}s", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))
        return 0

    _print_description(result)
    return 0


def _build_model(args) -> tuple[Model, int]:
    """Build the model client for this run, and resolve the timeout with it.

    Resolves provider and name from, in order: the flags, then
    dev-agents.yaml, then a default. The credential comes from the flags, then
    LLM_API_KEY, and never falls back to a placeholder: a run that cannot
    authenticate should say so here rather than return kind=unknown later.
    """
    base_settings, base_model = _base_config().get(
        ProjectAnalyzerAgent.agent_type, (None, None)
    )

    provider = (args.provider or (base_model.provider if base_model else "gemini")).lower()
    name = args.model or (base_model.name if base_model else DEFAULT_MODEL)
    temperature = args.temperature if args.temperature is not None else (
        base_model.temperature if base_model else 0.2
    )
    max_tokens = (
        base_model.max_tokens if base_model else DEFAULT_MAX_TOKENS
    )
    timeout = args.timeout if args.timeout is not None else (
        base_settings.timeout_seconds if base_settings else DEFAULT_TIMEOUT
    )

    if timeout <= 0:
        raise ValueError("--timeout must be positive")

    api_key = args.api_key or _api_key()
    if not api_key:
        raise ValueError(
            "No API key. Pass --api-key or set LLM_API_KEY in .env"
        )

    logger.info(
        "Model provider=%r name=%r temperature=%s max_tokens=%s timeout=%ss",
        provider, name, temperature, max_tokens, timeout,
    )

    model_settings = ModelSettings(
        provider=provider,
        name=name,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    credentials = ModelCredentials(api_key=api_key)

    if provider in ("gemini", "google"):
        return GeminiModel(settings=model_settings, credentials=credentials), timeout

    if provider in ("openrouter", "openai"):
        return OpenRouterModel(settings=model_settings, credentials=credentials), timeout

    raise ValueError(f"Unsupported provider: {provider!r}")


def _base_config() -> dict:
    return load_dev_agents_config()


def _api_key() -> str | None:
    try:
        from server.config.settings import settings

        return settings.llm_api_key
    except ValidationError as error:
        logger.warning("No usable settings: %s", error)
        return None


def _facts(args) -> int:
    """Just the collected facts, no model involved."""
    from server.services.collection.schemas import CollectionInput
    from server.services.collection.service import CollectionService

    try:
        payload = CollectionInput(
            root_path=args.root,
            max_files=args.max_files,
            max_depth=args.max_depth,
        )
    except ValidationError as error:
        print(f"error: invalid arguments\n{error}", file=sys.stderr)
        return 2

    try:
        collection = asyncio.run(CollectionService().collect(payload))
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except ValidationError as error:
        print(f"error: invalid arguments\n{error}", file=sys.stderr)
        return 2

    facts, trimmed = ProjectAnalyzerAgent._build_facts(collection.model_dump())

    print(facts)
    print()
    print(f"prompt chars: {len(facts)} | trimmed: {trimmed}")
    print(f"stats: {json.dumps(collection.stats)}")
    return 0


def _dry_run(args) -> int:
    """Collect, build the prompt, print it, never call a model."""
    from server.services.collection.schemas import CollectionInput
    from server.services.collection.service import CollectionService

    try:
        collection_input = CollectionInput(
            root_path=args.root,
            max_files=args.max_files,
            max_depth=args.max_depth,
        )
    except ValidationError as error:
        print(f"error: invalid arguments\n{error}", file=sys.stderr)
        return 2

    try:
        collection = asyncio.run(CollectionService().collect(collection_input))
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except ValidationError as error:
        print(f"error: invalid arguments\n{error}", file=sys.stderr)
        return 2

    facts, trimmed = ProjectAnalyzerAgent._build_facts(collection.model_dump())

    system = ProjectAnalyzerAgent.system_prompt()
    user = ProjectAnalyzerAgent.user_prompt(facts=facts)

    print("=" * 70)
    print("SYSTEM PROMPT  (prompts/analyzer/system.md)")
    print("=" * 70)
    print(system)
    print()
    print("=" * 70)
    print("USER PROMPT  (prompts/analyzer/user.md + collected facts)")
    print("=" * 70)
    print(user)
    print()
    print("=" * 70)
    print(f"system chars: {len(system)} | facts chars: {len(facts)} | trimmed: {trimmed}")
    print("no model was called")
    return 0


# -- output ----------------------------------------------------------------


def _print_description(description: ProjectDescription) -> None:
    print(f"kind              : {description.kind}")
    print(f"primary_language  : {description.primary_language}")
    print(f"confidence        : {description.confidence}")
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
    import textwrap

    return textwrap.wrap(text, width=width) or [""]


if __name__ == "__main__":
    raise SystemExit(main())