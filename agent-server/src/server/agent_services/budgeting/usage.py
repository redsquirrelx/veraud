"""Resource metrics remain available independently of budget enforcement."""

from pydantic import Field

from config.agents.base import RepositoryContract


class BudgetUsage(RepositoryContract):
    model_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    retrieved_characters: int = Field(default=0, ge=0)
    elapsed_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    reported_input_tokens: int = Field(default=0, ge=0)
    reported_output_tokens: int = Field(default=0, ge=0)
    unknown_usage_attempts: int = Field(default=0, ge=0)
    provider_attempts: int = Field(default=0, ge=0)
    provider_retries: int = Field(default=0, ge=0)
    provider_wait_seconds: float = Field(default=0, ge=0)
    accounted_tokens: int = Field(default=0, ge=0)
    estimated_tokens: int = Field(default=0, ge=0)
    token_budget_exhausted: bool = False
