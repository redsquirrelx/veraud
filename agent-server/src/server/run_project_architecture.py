"""Run orientation and architecture, with optional semantic review.

With --validate-semantics, the first semantic review uses advisory token budgets
throughout its investigation and provider retries. Revalidation after the single
architectural return retains strict token admission. The shared runner owns this
policy and the CLI lifecycle.
"""

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.repository_runner import main as run_repository


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else list(argv)
    return run_repository(arguments, mode="architecture")


if __name__ == "__main__":
    raise SystemExit(main())
