"""HTTP wire contract (api package).

These are the shapes the backend sends. Every override field is optional:
None means "use the server default". The service merges them over
dev_agents_config to produce the resolved ModelSettings.
"""

from pydantic import BaseModel, Field

from ..agents.dummy.schemas import DummyInput, DummyOutput


class ModelConfig(BaseModel):
    """Per-request model overrides. Partial on purpose, unlike ModelSettings."""

    provider: str | None = None
    name: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


class ExecutionConfig(BaseModel):
    """Basic execution config sent by the backend with each run request."""

    model: ModelConfig = Field(default_factory=ModelConfig)
    timeout_seconds: int | None = None
    api_key: str | None = None


class ExecutionRequest(BaseModel):
    agent_type: str
    config: ExecutionConfig = ExecutionConfig()
    input: DummyInput


class ExecutionResponse(BaseModel):
    agent_type: str
    result: DummyOutput
