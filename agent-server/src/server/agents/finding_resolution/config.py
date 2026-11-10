"""Specialized prompts; calls, queries and iteration limits remain shared."""

from typing import ClassVar

from pydantic import Field

from config.agents import InvestigationConfig


class FindingResolutionConfig(InvestigationConfig):
    prompt_nodes: ClassVar[tuple[str, ...]] = ("plan_verification", "investigate", "evaluate_resolution")
    max_evaluation_returns: int = Field(default=1, ge=0, le=3,
        description="Maximum evaluation-directed returns to investigation per finding; shared iteration/resource limits also apply.")
