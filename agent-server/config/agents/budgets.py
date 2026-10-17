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
        description="Execution time allowance in seconds. Hierarchical agents pause active time during quota waits and also enforce max_wall_time_seconds.")


class ExecutionTimingConfig(ConfigContract):
    max_wall_time_seconds: float = Field(default=1800, gt=0, allow_inf_nan=False,
        description="Absolute execution duration, including all quota waits. Never paused.")
    cancellation_grace_seconds: float = Field(default=2, ge=0, le=30, allow_inf_nan=False,
        description="Maximum wait for a cancelled asynchronous child to acknowledge cancellation.")


class SourceReadConfig(ConfigContract):
    max_source_characters: int = Field(default=4000, ge=1,
        description="Maximum characters per source excerpt; toolset limits may be stricter.")


class SourceLineConfig(ConfigContract):
    max_source_lines: int = Field(default=80, ge=1,
        description="Maximum lines per source excerpt; toolset limits may be stricter.")
