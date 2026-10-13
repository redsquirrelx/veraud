"""Dedicated runner for the focused architecture agent and orientation handoff."""

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.run_project_analysis import main as run_analysis


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else list(argv)
    return run_analysis(["--architecture", *arguments])


if __name__ == "__main__":
    raise SystemExit(main())
