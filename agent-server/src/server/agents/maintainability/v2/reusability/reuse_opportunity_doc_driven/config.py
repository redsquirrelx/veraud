"""Exclusive investigation policy; inherited budgets keep their shared owners."""

from typing import ClassVar

from pydantic import Field

from config.agents import InvestigationConfig


class ReuseOpportunityConfig(InvestigationConfig):
    prompt_nodes: ClassVar = ("plan_investigation", "investigate")
    max_tool_query_retries: int = Field(default=1, ge=0, le=3,
        description="Additional attempts for the same failed repository-tool query, independent of provider/schema retries.")
