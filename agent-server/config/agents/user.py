"""High-level operating limits that an end user may change for an audit."""

from pydantic import Field

from .base import ConfigContract
from .budgets import TimeoutConfig, TokenBudgetConfig


class ProviderRateLimits(ConfigContract):
    requests_per_minute: int | None = Field(default=14, ge=1,
        description="Local rolling request admission per minute. Null disables this bound.")
    tokens_per_minute: int | None = Field(default=250_000, ge=1,
        description="Local rolling token reservation/accounting per minute. Null disables this bound.")


class AgentUserConfig(TokenBudgetConfig, TimeoutConfig):
    """Cost, duration and provider quota; independent of investigation implementation."""

    provider_rate_limits: ProviderRateLimits = Field(default_factory=ProviderRateLimits,
        description="Local provider admission limits; an injected parent pacer remains authoritative.")
