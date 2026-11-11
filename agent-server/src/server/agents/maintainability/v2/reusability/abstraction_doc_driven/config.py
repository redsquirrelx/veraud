"""Developer-only bounds for abstraction planning."""

from typing import ClassVar

from pydantic import Field, model_validator

from config.agents import InvestigationConfig


class AbstractionConfig(InvestigationConfig):
    prompt_nodes: ClassVar = ("plan_investigation", "investigate", "synthesize", "finalize")
    defaults: ClassVar = {"max_iterations": 5, "max_output_tokens": 40_000, "tools": [
        "list_files", "find_symbols", "list_relationships", "get_source_excerpt",
        "search_repository_text", "get_evidence", "get_infrastructure",
    ]}
    max_planned_investigations: int = Field(default=18, ge=1, le=18,
        description="Bounded abstraction-purpose investigations proposed by plan_investigation.")
    max_documentary_claims_per_candidate: int = Field(default=6, ge=1, le=20,
        description="Maximum documented claims an eligible investigator may hold per task; covers binding by phase 1 or capability affinity.")

    @model_validator(mode="after")
    def internal_prompts_only(self):
        if self.prompts:
            raise ValueError("Abstraction uses only its internal prompts; external prompt overrides are unsupported.")
        return self
