"""Developer-only bounds for reuse-parametrization planning and investigate commands."""

from typing import ClassVar

from pydantic import Field, model_validator

from config.agents import InvestigationConfig


class ReuseParametrizationConfig(InvestigationConfig):
    prompt_nodes: ClassVar = ("plan_investigation", "investigate")
    defaults: ClassVar = {"max_iterations": 1, "max_output_tokens": 40_000}
    max_planned_investigations: int = Field(
        default=16,
        ge=1,
        le=20,
        description="Bounded parametrization investigations proposed by plan_investigation.",
    )
    max_documentary_claims_per_candidate: int = Field(
        default=6,
        ge=1,
        le=20,
        description="Maximum documented claims an eligible investigator may hold per task; covers binding by phase 1 or capability affinity.",
    )

    @model_validator(mode="after")
    def internal_prompts_only(self):
        if self.prompts:
            raise ValueError(
                "ReuseParametrization uses only its internal prompts; external prompt overrides are unsupported."
            )
        return self
