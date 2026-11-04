"""Architecture-stage controls on top of shared repository-agent limits."""

from typing import ClassVar

from config.agents.budgets import SourceReadConfig
from config.agents.repository import RepositoryAgentLimits


class ArchitectureLimits(RepositoryAgentLimits, SourceReadConfig):
    soft_token_budgets: bool = True
    defaults: ClassVar = {"max_model_calls": 16, "max_tool_calls": 32,
        "max_prompt_characters": 36000, "max_source_characters": 2400}
    bounds: ClassVar = {"max_model_calls": {"le": 24}, "max_tool_calls": {"le": 48},
        "max_prompt_characters": {"ge": 6000}, "max_source_characters": {"ge": 400}}
