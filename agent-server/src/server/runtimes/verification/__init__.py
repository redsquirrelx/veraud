"""Shared verification-suite infrastructure.

Runtime support for agents that generate portable ``.tallercito/`` verification
suites. Nothing in this package imports concrete agents; agents import this.
"""

from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent / "templates"
SUITE_ROOT_NAME = ".tallercito"

__all__ = ["SUITE_ROOT_NAME", "TEMPLATES_DIR"]
