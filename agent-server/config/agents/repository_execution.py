"""Shared repository execution envelope; distinct from individual agent-stage policy."""

from typing import ClassVar

from pydantic import Field

from .base import RepositoryContract
from .budgets import CallBudgetConfig, RetrievalBudgetConfig, TokenBudgetConfig


class ExecutionBudget(RepositoryContract, CallBudgetConfig, TokenBudgetConfig, RetrievalBudgetConfig):
    defaults: ClassVar = {"max_model_calls": 8, "max_total_tokens": 60_000, "max_tool_calls": 20}
    bounds: ClassVar = {"max_tool_calls": {"ge": 1}}
    max_input_tokens_per_call: int = Field(default=6000, ge=500)
    max_tokens_per_objective: int = Field(default=20_000, ge=1000)
    max_output_tokens_per_call: int = Field(default=3000, ge=256)
    max_elapsed_seconds: float = Field(default=600, gt=0, allow_inf_nan=False)
