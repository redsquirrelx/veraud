"""Developer-owned scope limits; execution budgets remain shared."""

from pydantic import Field

from config.agents import InvestigationConfig


class CodeComprehensionConfig(InvestigationConfig):
    max_components: int = Field(default=8, ge=1, le=40)
    max_related_components_per_assessment: int = Field(default=6, ge=1, le=20)
