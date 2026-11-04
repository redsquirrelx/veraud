"""Compatibility alias: both auditors use the same typed investigation state."""

from .....runtimes.investigation.state import InvestigationState as BoundaryState

__all__ = ["BoundaryState"]
