"""Developer-only bounds for responsibility planning."""

from typing import ClassVar

from pydantic import Field, model_validator

from config.agents import InvestigationConfig


class ResponsibilityConfig(InvestigationConfig):
    defaults: ClassVar = {"max_iterations": 2, "max_output_tokens": 40_000}
    max_planned_investigations: int = Field(default=16, ge=1, le=20,
        description="Bounded cohesion investigations proposed by plan_investigation.")

    @model_validator(mode="after")
    def internal_prompts_only(self):
        if self.prompts:
            raise ValueError("Responsibility uses only its internal prompts; external prompt overrides are unsupported.")
        return self
