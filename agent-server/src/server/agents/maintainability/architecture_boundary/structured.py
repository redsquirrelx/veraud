"""Backward-compatible imports for shared structured-output handling."""

from ...modularity_runtime.structured import (
    finish_diagnostic,
    parse_structured,
    safe_diagnostic,
)

__all__ = ["finish_diagnostic", "parse_structured", "safe_diagnostic"]
