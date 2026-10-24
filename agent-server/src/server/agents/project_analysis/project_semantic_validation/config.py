"""Semantic review-specific selection and batching controls."""

from typing import ClassVar

from pydantic import Field

from config.agents.repository import RepositoryAgentLimits


class ValidationLimits(RepositoryAgentLimits):
    defaults: ClassVar = {"max_model_calls": 24, "max_tool_calls": 32, "max_prompt_characters": 24000}
    bounds: ClassVar = {"max_model_calls": {"le": 32}, "max_tool_calls": {"le": 32},
        "max_prompt_characters": {"ge": 6000}}
    max_claims: int = Field(default=64, ge=1, le=64)
    batch_size: int = Field(default=4, ge=1, le=4)
