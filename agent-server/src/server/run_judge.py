"""DEV-ONLY runner for the judge agent.

Grades a past architecture description against the source it cites:

    uv run --no-sync python -m server.run_judge <root> <description.json>

The judge uses the architect's own model instance: same provider, same name,
same temperature, by construction. There is no judge entry in
dev-agents.yaml to drift out of sync; the model is resolved exactly the way
the architect resolves it and handed over.

Needs a model credential: LLM_API_KEY from .env, or --api-key.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from pydantic import ValidationError

if __package__ in (None, ""):
    # Launched by path: no package context, so make `server` importable.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.agents.architect.agent import ArchitectureAgent
from server.agents.architect.schemas import ArchitectureDescription
from server.agents.judge.agent import JudgeAgent
from server.agents.judge.schemas import JudgeInput
from server.api.schemas import ExecutionConfig
from server.app.agent_registry import AgentRegistry
from server.app.execution_service import (
    AgentExecutionService,
    InvalidConfigError,
)
from server.config.schemas import AgentSettings

logger = logging.getLogger("run-judge")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_judge",
        description=(
            "Grade an architecture description against its cited source: "
            "whether each responsibility and quality note is supported, "
            "contradicted, or unverifiable."
        ),
    )
    parser.add_argument("root", help="Repository root the description was written from")
    parser.add_argument("description", help="ArchitectureDescription JSON file to grade")
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds before giving up on the whole grading (default: 300)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the report as JSON (implies --quiet)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Silence logging",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.quiet or args.json:
        logging.disable(logging.CRITICAL)
    else:
        from server.config.logs import setup_logging

        setup_logging()

    try:
        description = ArchitectureDescription.model_validate_json(
            Path(args.description).read_text(encoding="utf-8")
        )
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except ValidationError as error:
        print(f"error: invalid description\n{error}", file=sys.stderr)
        return 2

    try:
        report = asyncio.run(_grade(args, description))
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except InvalidConfigError as error:
        print(f"error: invalid config\n{error}", file=sys.stderr)
        return 2
    except TimeoutError:
        print("error: the judge timed out", file=sys.stderr)
        return 1

    if args.json:
        print(report.model_dump_json(indent=2))
        return 0

    _print_report(report)
    return 0


async def _grade(args, description: ArchitectureDescription):
    # The judge borrows the architect model, resolved the same way, but the
    # architect is a CLI-only agent: the HTTP registry stays dummy-only.
    registry = AgentRegistry()
    registry.register(ArchitectureAgent.agent_type, ArchitectureAgent)
    service = AgentExecutionService(registry=registry)
    architect, _ = service.build_agent("architect", ExecutionConfig())

    logger.info(
        "judge borrows the architect model: provider=%r name=%r",
        architect.model.settings.provider, architect.model.settings.name,
    )
    judge = JudgeAgent(
        settings=AgentSettings(agent_id="judge", timeout_seconds=args.timeout),
        model=architect.model,
    )

    return await asyncio.wait_for(
        judge.run(JudgeInput(root_path=args.root, description=description)),
        timeout=args.timeout,
    )


def _print_report(report) -> None:
    total = len(report.grades)
    print(f"grades: {total} (supported={report.supported} contradicted={report.contradicted} unverifiable={report.unverifiable})")
    print(f"contradiction_rate: {report.contradiction_rate:.2f}")
    print()

    for grade in report.grades:
        mark = {"supported": "+", "contradicted": "!", "unverifiable": "?"}[grade.verdict]
        print(f"  [{mark}] [{grade.kind}] {grade.subject}: {grade.verdict}")
        for path in grade.evidence:
            print(f"      evidence: {path}")
        if grade.reason:
            print(f"      {grade.reason}")


if __name__ == "__main__":
    raise SystemExit(main())
