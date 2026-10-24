"""Developer stage limits for the existing project-repository protocol."""

from typing import ClassVar

from pydantic import Field

from .base import RepositoryContract
from .budgets import CallBudgetConfig


class RepositoryAgentLimits(RepositoryContract, CallBudgetConfig):
    # User budgets/deadlines for this protocol are owned by the repository execution envelope.
    user_fields: ClassVar[frozenset[str]] = frozenset()
    defaults: ClassVar = {"max_model_calls": 4, "max_tool_calls": 6}
    bounds: ClassVar = {"max_tool_calls": {"ge": 1}}
    max_prompt_characters: int = Field(default=20000, ge=4000,
        description="Maximum prompt characters, using this protocol's prompt builder and repository budget.")
