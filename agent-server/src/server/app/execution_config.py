"""Transport-neutral execution override contracts."""

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
            "Token limit override. Null uses the base value, or 40000 when no "
            "base is configured. Provider-specific limits are not validated "
            "by this HTTP model."
        ),
        examples=[40000],
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
