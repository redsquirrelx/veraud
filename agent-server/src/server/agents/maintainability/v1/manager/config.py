"""Hierarchy-level limits and the coordinator-child envelope."""

from typing import ClassVar

from pydantic import Field

from config.agents import CoordinatorConfig


class MaintainabilityConfig(CoordinatorConfig[CoordinatorConfig]):
    prompt_nodes: ClassVar[tuple[str, ...]] = ("synthesize_assessments",)
    defaults: ClassVar = {
        "max_model_calls": 300,
        "max_total_tokens": 1_000_000,
        "max_tool_calls": 400,
        "timeout_seconds": 1200,
        "max_invocations": 4,
        "max_parallel": 2,
        "invocation_limits": CoordinatorConfig(),
    }
    bounds: ClassVar = {
        "max_model_calls": {"le": 1000},
        "max_tool_calls": {"le": 2000},
        "max_invocations": {"ge": 1, "le": 12},
        "max_parallel": {"le": 2},
    }
    max_attempts_per_dimension: int = Field(default=2, ge=1, le=4,
        description="Maximum coordinator attempts for a requested maintainability dimension.")
