"""Run static repository structure extraction without starting the agent server."""

import argparse
import asyncio
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.services.graphify import GraphifyAdapter, GraphifyError
from server.services.repository_structure import RepositoryStructureService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", type=Path, help="Local repository directory to analyze.")
    parser.add_argument(
        "--out", type=Path, required=True,
        help="New output directory outside the repository (must not exist).",
    )
    parser.add_argument("--timeout", type=float, help="Timeout in seconds; uses the adapter default.")
    parser.add_argument(
        "--max-workers", type=int, help="AST worker count; uses the adapter default."
    )
    arguments = parser.parse_args(argv)
    options = {}
    if arguments.timeout is not None:
        options["timeout_seconds"] = arguments.timeout
    if arguments.max_workers is not None:
        options["max_workers"] = arguments.max_workers
    try:
        adapter = GraphifyAdapter(**options)
    except ValueError as error:
        parser.error(str(error))
    service = RepositoryStructureService(adapter=adapter)
    try:
        result = asyncio.run(service.extract_structure(arguments.repository, arguments.out))
    except GraphifyError as error:
        print(str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Graphify extraction cancelled.", file=sys.stderr)
        return 130
    print(f"Graph: {result.graph_file}")
    print(f"Duration: {result.elapsed_seconds:.2f} seconds (static analysis, no LLM).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
