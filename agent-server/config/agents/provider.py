"""Single developer policy for provider retries and request spacing."""

from pydantic import Field

from .base import ConfigContract


class ProviderRetryConfig(ConfigContract):
    provider_request_timeout_seconds: float = Field(default=90, gt=0, allow_inf_nan=False,
        description="Maximum duration of one provider attempt, independent of the agent's total active time.")
    max_provider_retries: int = Field(default=4, ge=0, le=8,
        description="Additional transient transport/server retries. HTTP 429 recovery waits resume separately within execution call/token budgets.")
    provider_request_interval_seconds: float = Field(default=0, ge=0, le=120, allow_inf_nan=False,
        description="Minimum spacing between locally admitted provider attempts.")
    provider_retry_backoff_seconds: float = Field(default=2, ge=0, le=120, allow_inf_nan=False,
        description="Base provider retry backoff in seconds; quota/recovery waits do not consume active execution time. An explicitly supplied wall deadline still applies.")
    provider_max_retry_wait_seconds: float = Field(default=120, ge=0, le=3600, allow_inf_nan=False,
        description="Maximum automatic wait per provider recovery. Longer delays defer the affected stage with preserved partial results; never retry before the provider permits it.")
    provider_recovery_budget_seconds: float = Field(default=60, ge=0, le=600, allow_inf_nan=False,
        description="Cumulative automatic provider-recovery sleep allowance per invocation. Includes quota recovery and transient retries; independent of active execution time and bounded by any wall deadline.")
