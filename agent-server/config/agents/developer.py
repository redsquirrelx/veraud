"""Low-level execution policy maintained by developers, outside the user panel."""

from typing import ClassVar

from pydantic import Field, model_validator

from .budgets import CallBudgetConfig
from .provider import ProviderRetryConfig

REPOSITORY_TOOLS = (
    "list_files", "find_symbols", "list_relationships", "get_source_excerpt",
    "search_repository_text", "get_evidence", "get_infrastructure",
)
INVESTIGATION_NODES = ("plan_investigation", "investigate", "evaluate_evidence", "review_findings")


class AgentDeveloperConfig(CallBudgetConfig, ProviderRetryConfig):
    """Implementation bounds, transport tuning, enabled tools and cognitive prompts."""

    prompt_nodes: ClassVar[tuple[str, ...]] = ()
    bounds: ClassVar = {"max_model_calls": {"ge": 4, "le": 100}, "max_tool_calls": {"le": 200}}
    max_schema_retries: int = Field(default=1, ge=0, le=2, description="Additional structured-output correction attempts.")
    max_context_characters: int = Field(default=100_000, ge=4000,
        description="Serialized messages plus schema/tool overhead per model call, measured in characters.")
    max_output_tokens: int = Field(default=4000, ge=256,
        description="Per-call output cap, also bounded by the supplied model and repository budget.")
    tools: list[str] = Field(default_factory=lambda: list(REPOSITORY_TOOLS),
        description="Enabled read-only repository tools; coordinators disable direct tools.",
        json_schema_extra={"items": {"type": "string", "enum": list(REPOSITORY_TOOLS)}, "uniqueItems": True})
    prompts: dict[str, str] = Field(default_factory=dict,
        description="Node prompt overrides. Omitted nodes use the agent's local prompts/ files.")

    @model_validator(mode="after")
    def valid_controls(self):
        if len(self.tools) != len(set(self.tools)) or set(self.tools) - set(REPOSITORY_TOOLS):
            raise ValueError("Tools must be unique known repository tool names.")
        if self.prompt_nodes and set(self.prompts) - set(self.prompt_nodes):
            raise ValueError(f"Prompt overrides must name one of {self.prompt_nodes}.")
        return self
