"""Single developer policy for provider retries and request spacing."""

from pydantic import Field

from .base import ConfigContract


class ProviderRetryConfig(ConfigContract):
    max_provider_retries: int = Field(default=2, ge=0, le=4,
        description="Additional transient-provider retries.")
    provider_request_interval_seconds: float = Field(default=0, ge=0, le=120, allow_inf_nan=False,
        description="Minimum spacing between locally admitted provider attempts.")
    provider_retry_backoff_seconds: float = Field(default=2, ge=0, le=120, allow_inf_nan=False,
        description="Base provider retry backoff in seconds; waits consume the deadline.")
