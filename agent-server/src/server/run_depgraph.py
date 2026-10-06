"""DEV-ONLY runner for DependencyGraphService.

Any of these works, from anywhere:

    uv run --no-sync python -m server.run_depgraph ../appdata/workspace/123-owner-repo
    python src/server/run_depgraph.py ../appdata/workspace/123-owner-repo
    uv run --no-sync depgraph ../appdata/workspace/123-owner-repo

Needs no .env and no particular cwd: it never reaches settings.
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

from server.services.dependency_graph.schemas import DependencyGraphInput
from server.services.dependency_graph.service import DependencyGraphService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_depgraph",
        description=(
            "Map which repo file depends on which. Python only: import "
            "statements resolved to real files."
        ),
    )
    parser.add_argument("root", help="Directory to map")
    parser.add_argument(
        "--max-depth",
        type=int,
        default=8,
        help="Maximum directory depth to walk (default: 8)",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=500,
        help="Maximum files to include before truncating (default: 500)",
    )
    parser.add_argument(
        "--include-external",
        action="store_true",
        help="Keep edges pointing outside the repo (third-party imports)",
    )
    parser.add_argument(
        "--no-cycles",
        action="store_true",
        help="Skip circular import detection",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the whole DependencyGraphOutput as JSON",
    )
    parser.add_argument(
        "--cycles-only",
        action="store_true",
        help="Print just the circular import groups",
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

    try:
        payload = DependencyGraphInput(
            root_path=args.root,
            max_depth=args.max_depth,
            max_files=args.max_files,
            include_external=args.include_external,
            detect_cycles=not args.no_cycles,
        )
        result = asyncio.run(DependencyGraphService().create(payload))

    except ValidationError as error:
        print(f"error: invalid arguments\n{error}", file=sys.stderr)
        return 2
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))
        return 0

    if args.cycles_only:
        _print_cycles(result)
        return 0

    _print_edges(result)
    print()
    print(result.stats.model_dump_json(indent=2))
    return 0


def _print_edges(result) -> None:
    """Group edges by source file, so each file reads as one dependency list."""
    by_source: dict[str, list] = {}
    for edge in result.edges:
        by_source.setdefault(edge.source, []).append(edge)

    indent = " " * 3

    for source in sorted(by_source):
        print(f"{source}")
        for edge in by_source[source]:
            if edge.target is not None:
                target = edge.target
            elif edge.reason == "external":
                target = f"({edge.specifier})"
            else:
                target = f"[{edge.reason}] {edge.specifier}"
            print(f"{indent}-> {target}  ({edge.kind}, line {edge.line})")
        print()


def _print_cycles(result) -> None:
    cycles = result.stats.cycles
    if not cycles:
        print("No circular imports found.")
        return

    print(f"{len(cycles)} circular import group(s):\n")
    for cycle in cycles:
        print("  " + " -> ".join(cycle) + f" -> {cycle[0]}")


if __name__ == "__main__":
    raise SystemExit(main())