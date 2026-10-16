"""Single declarations for operating budgets shared by agent execution protocols."""

from pydantic import Field

from .base import ConfigContract


class TokenBudgetConfig(ConfigContract):
    max_total_tokens: int = Field(default=100_000, ge=1000,
        description="Execution-wide token budget. Repository and parent budgets may be stricter.")


class CallBudgetConfig(ConfigContract):
    max_model_calls: int = Field(default=16, ge=1,
        description="Maximum model attempts across this execution.")
    max_tool_calls: int = Field(default=24, ge=0,
        description="Maximum repository tool calls, including failures.")


class TimeoutConfig(ConfigContract):
    timeout_seconds: float = Field(default=300, gt=0, allow_inf_nan=False,
        description="Execution deadline in seconds, including quota waits and retries.")


class SourceReadConfig(ConfigContract):
    max_source_characters: int = Field(default=4000, ge=1,
        description="Maximum characters per source excerpt; toolset limits may be stricter.")


class SourceLineConfig(ConfigContract):
    max_source_lines: int = Field(default=80, ge=1,
        description="Maximum lines per source excerpt; toolset limits may be stricter.")
