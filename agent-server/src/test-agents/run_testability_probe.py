"""Shim: `uv run python src/test-agents/run_testability_probe.py generate ...`."""

import sys

from server.agents.testability_probe.cli import main

if __name__ == "__main__":
    sys.exit(main())
