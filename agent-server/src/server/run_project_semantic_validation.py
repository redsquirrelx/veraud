"""Dedicated semantic review runner for an exported architectural result."""

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.repository_runner import main as run_repository


def main(argv=None):
    return run_repository(
        sys.argv[1:] if argv is None else argv, mode="semantic_validation"
    )


if __name__ == "__main__":
    raise SystemExit(main())
