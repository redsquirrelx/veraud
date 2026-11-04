"""Compose user limits with developer policy for the existing flat runtime contract."""

from typing import ClassVar

from pydantic import Field, model_validator

from .budgets import SourceLineConfig, SourceReadConfig
from .developer import INVESTIGATION_NODES, AgentDeveloperConfig
from .user import AgentUserConfig, ProviderRateLimits  # noqa: F401 - compatibility export


class AgentExecutionConfig(AgentUserConfig, AgentDeveloperConfig):
    """Resolved runtime configuration; only explicitly declared user fields are public."""

    user_fields: ClassVar[frozenset[str]] = frozenset(AgentUserConfig.model_fields)


class InvestigationConfig(AgentExecutionConfig):
    prompt_nodes: ClassVar[tuple[str, ...]] = INVESTIGATION_NODES
    max_iterations: int = Field(default=3, ge=1, le=20, description="Maximum evidence-evaluation rounds within an investigation.")


class SourceExcerptConfig(InvestigationConfig, SourceReadConfig, SourceLineConfig):
    """Developer source-reading policy shared by applicable investigators."""

    bounds: ClassVar = {"max_source_characters": {"ge": 256, "le": 12000}, "max_source_lines": {"le": 120}}


def default_invocation_limits():
    return InvestigationConfig(max_total_tokens=60_000, max_tool_calls=16,
        timeout_seconds=180, max_context_characters=100_000)


class CoordinatorConfig[ChildConfig: InvestigationConfig = InvestigationConfig](InvestigationConfig):
    """User operating limits plus developer delegation policy and child envelopes."""

    prompt_nodes: ClassVar[tuple[str, ...]] = ("synthesize_findings",)
    defaults: ClassVar = {"max_model_calls": 96, "max_total_tokens": 300_000,
        "max_tool_calls": 96, "timeout_seconds": 600, "tools": []}
    bounds: ClassVar = {"max_invocations": {"ge": 3}, "max_model_calls": {"le": 1000}}
    max_rounds: int = Field(default=2, ge=1, le=6, description="Maximum coordinator delegation/collection rounds.")
    max_invocations: int = Field(default=6, ge=1, le=18, description="Maximum subordinate invocations across all rounds.")
    max_parallel: int = Field(default=3, ge=1, le=3, description="Maximum concurrent subordinate investigations.")
    investigation_start_interval_seconds: float = Field(default=0, ge=0, le=120, allow_inf_nan=False,
        description="Minimum spacing between subordinate starts, separate from provider request spacing.")
    invocation_limits: ChildConfig = Field(default_factory=default_invocation_limits,
        description="Developer-owned per-child envelope. Parent/global limits still apply.")

    @model_validator(mode="after")
    def no_direct_tools(self):
        if self.tools:
            raise ValueError("Coordinators delegate repository work and cannot enable direct tools.")
        return self
