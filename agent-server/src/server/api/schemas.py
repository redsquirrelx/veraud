"""HTTP wire contract (api package).

These are the shapes the backend sends. Every override field is optional:
None means "use the server default". The service merges them over
dev_agents_config to produce the resolved ModelSettings.

The contract is agent agnostic on purpose. It never mentions a specific agent,
so adding one does not change this file. The input and output shapes belong to
each agent; `GET /api/agents/{agent_type}/schema` publishes them.
"""

from typing import Any

from pydantic import BaseModel, Field


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
    config: ExecutionConfig = Field(default_factory=ExecutionConfig)
    input: dict[str, Any] = Field(
        default_factory=dict,
        description="Agent input. Validated against that agent's input schema.",
    )
    execution_id: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Row the backend created for this run. When present the server reports "
            "progress back to it over HTTP; absent means nobody is listening."
        ),
    )


class ExecutionResponse(BaseModel):
    agent_type: str
    result: dict[str, Any] = Field(
        description="Agent output. Matches that agent's output schema.",
    )


class AgentSchemaResponse(BaseModel):
    """What one agent accepts and returns, so callers can build a valid request."""

    agent_type: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]