"""Orientation-specific caps for the repository-agent protocol."""

from typing import ClassVar

from config.agents.repository import RepositoryAgentLimits


class OrientationLimits(RepositoryAgentLimits):
    """Uses shared repository-stage limits without redeclaring common fields."""
    bounds: ClassVar = {"max_model_calls": {"le": 4}, "max_tool_calls": {"le": 6}}
