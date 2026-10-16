"""Common resolved client/settings contracts, shared by existing execution protocols."""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict
from pydantic_core import PydanticUndefined

from .budgets import TimeoutConfig


class ModelSettings(BaseModel):
    """Resolved model settings; partial HTTP overrides are a separate wire contract."""

    provider: str
    name: str
    temperature: float
    max_tokens: int


class AgentSettings(TimeoutConfig):
    model_config = ConfigDict(extra="ignore", frozen=False)
    defaults: ClassVar = {"timeout_seconds": PydanticUndefined}
    agent_id: str


class ModelCredentials(BaseModel):
    api_key: str
