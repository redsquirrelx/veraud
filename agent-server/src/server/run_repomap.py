"""DEV-ONLY runner for RepoMapService.

Any of these works, from anywhere:

    uv run --no-sync python -m server.run_repomap ../appdata/workspace/123-owner-repo
    python src/server/run_repomap.py ../appdata/workspace/123-owner-repo
    uv run --no-sync repomap ../appdata/workspace/123-owner-repo

Needs no .env and no particular cwd: RepoMapService never reaches settings.
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from pydantic import ValidationError

if __package__ in (None, ""):
    # Launched by path (python src/server/run_repomap.py): there is no package
    # context, so make `server` importable from the src root ourselves.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.services.repo_map.schemas import RepoMapInput
from server.services.repo_map.service import RepoMapService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_repomap",
        description=(
            "Map a repository: a directory tree plus, for Python, the symbols "
            "defined in each file."
        ),
    )
    parser.add_argument("root", help="Directory to map")
    parser.add_argument(
        "--max-depth",
        type=int,
        default=4,
        help="Maximum directory depth to descend (default: 4)",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=300,
        help="Maximum files to include before truncating (default: 300)",
    )
    parser.add_argument(
        "--no-symbols",
        action="store_true",
        help="Skip symbol extraction, keep the tree",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the whole RepoMapOutput as JSON instead of the tree",
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
        payload = RepoMapInput(
            root_path=args.root,
            max_depth=args.max_depth,
            max_files=args.max_files,
            include_symbols=not args.no_symbols,
        )
        result = asyncio.run(RepoMapService().create(payload))

    except ValidationError as error:
        print(f"error: invalid arguments\n{error}", file=sys.stderr)
        return 2
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))
        return 0

    print(result.tree)
    print()
    print(result.stats.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())