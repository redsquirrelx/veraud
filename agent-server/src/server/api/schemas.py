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

    provider: str | None = Field(
        default=None,
        description=(
            "Model provider override. Supported names are gemini/google and "
            "openrouter/openai, groq and anthropic (case-insensitive). Null or an empty string uses "
            "the agent's base provider, or gemini when no base is configured."
        ),
        examples=["openrouter"],
    )
    name: str | None = Field(
        default=None,
        description=(
            "Model name override. Null or an empty string uses the agent's base "
            "model name. The resolved name must be present."
        ),
        examples=["openai/gpt-oss-120b"],
    )
    temperature: float | None = Field(
        default=None,
        description=(
            "Sampling temperature override. Null uses the base value, or 0.2 "
            "when no base is configured. Zero is an explicit override."
        ),
        examples=[0.2],
    )
    max_tokens: int | None = Field(
        default=None,
        description=(
            "Token limit override. Null uses the base value, or 1000 when no "
            "base is configured. Provider-specific limits are not validated "
            "by this HTTP model."
        ),
        examples=[1000],
    )


class ExecutionConfig(BaseModel):
    """Basic execution config sent by the backend with each run request."""

    model: ModelConfig = Field(
        default_factory=ModelConfig,
        description="Partial model overrides. Omission creates an empty override object.",
        examples=[{"provider": "openrouter", "name": "openai/gpt-oss-120b"}],
    )
    timeout_seconds: int | None = Field(
        default=None,
        description=(
            "Agent-run timeout in seconds, excluding configuration and callbacks. "
            "Null uses the base timeout, or 60 when no base is configured. "
            "The service rejects resolved values less than or equal to zero."
        ),
        examples=[60],
    )
    api_key: str | None = Field(
        default=None,
        description=(
            "Provider API key override. Null or an empty string uses the server "
            "key; invalid server settings trigger the development-key fallback. "
            "This value is not included in execution responses."
        ),
        examples=["YOUR_PROVIDER_API_KEY"],
    )


class ExecutionRequest(BaseModel):
    agent_type: str = Field(
        description="Registered agent name, discovered through GET /api/agents.",
        examples=["dummy"],
    )
    config: ExecutionConfig = Field(
        default_factory=ExecutionConfig,
        description="Execution overrides. Omission uses the server's agent configuration.",
        examples=[{"model": {"provider": "openrouter", "name": "openai/gpt-oss-120b"}}],
    )
    input: dict[str, Any] = Field(
        default_factory=dict,
        description="Agent input. Validated against that agent's input schema.",
        examples=[{"code": "def add(a, b): return a + b"}],
    )
    execution_id: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Row the backend created for this run. When present the server reports "
            "progress back to it over HTTP when backend settings are available. "
            "Omission or null disables callbacks."
        ),
        examples=[1],
    )


class ExecutionResponse(BaseModel):
    """Completed agent output returned after the execution finishes."""

    agent_type: str = Field(
        description="Name of the agent that produced the result.",
        examples=["dummy"],
    )
    result: dict[str, Any] = Field(
        description="Agent output. Matches that agent's output schema.",
        examples=[{
            "evaluated_attribute": "maintainability",
            "score": 90.0,
            "findings": [],
            "recommendations": [],
        }],
    )


class AgentSchemaResponse(BaseModel):
    """What one agent accepts and returns, so callers can build a valid request."""

    agent_type: str = Field(
        description="Registered agent whose contracts are being described.",
        examples=["dummy"],
    )
    input_schema: dict[str, Any] = Field(
        description=(
            "JSON Schema generated from the agent's input model. Nested references "
            "resolve within this document, including its own $defs when present."
        ),
        examples=[{
            "title": "DummyInput",
            "type": "object",
            "properties": {
                "code": {"type": "string", "title": "Code", "description": "Code snippet to audit"},
                "evaluated_attribute": {
                    "type": "string", "title": "Evaluated Attribute",
                    "default": "maintainability",
                    "description": "Quality attribute under evaluation (dummy)",
                },
            },
            "required": ["code"],
        }],
    )
    output_schema: dict[str, Any] = Field(
        description=(
            "JSON Schema generated from the agent's output model. It describes "
            "the result object returned by POST /api/agents/run."
        ),
    )


class VerifyAccessRequest(BaseModel):
    """Explicit access check; never falls back to a server API key."""

    model: ModelConfig
    api_key: str = Field(min_length=1, repr=False, description="Credential to verify; never returned.")


class VerifyAccessResponse(BaseModel):
    verified: bool


class StatusResponse(BaseModel):
    """Agent-server health response."""

    status: str = Field(description="Service health indicator.", examples=["ok"])
    service: str = Field(description="Name of the responding service.", examples=["agent-server"])


class DomainError(BaseModel):
    """String-detail HTTP error, distinct from FastAPI validation error lists."""

    detail: str = Field(
        description="Domain failure message; request-validation failures use a list instead.",
        examples=["Agent execution timed out"],
    )


class RequestValidationErrorResponse(BaseModel):
    """Documentation of FastAPI's existing request-validation response."""

    detail: list[dict[str, Any]] = Field(
        description=(
            "Request validation errors. Items contain loc, msg and type, and "
            "may also contain input, ctx or other framework-provided details."
        ),
        examples=[[{
            "type": "missing",
            "loc": ["body", "agent_type"],
            "msg": "Field required",
            "input": {},
        }]],
    )
