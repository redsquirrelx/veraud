"""Specialized prompts; calls, queries and iteration limits remain shared."""

from typing import ClassVar

from config.agents import InvestigationConfig


class FindingResolutionConfig(InvestigationConfig):
    prompt_nodes: ClassVar[tuple[str, ...]] = ("plan_verification", "investigate")
