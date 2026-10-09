from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CallbackConfig(BaseModel):
    """Where and how to report an agent run back to the backend."""

    backend_url: str = Field(
        description="Backend base URL, e.g. http://localhost:7501",
    )
    shared_secret: str | None = Field(
        default=None,
        description="Sent as X-Agent-Secret when set. The backend does not check it yet.",
    )
    timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        description="Per-request timeout. A callback is a small POST, so it stays short.",
    )


class ExecutionOutcome(BaseModel):
    """What an agent reports when it finishes.

    `result` stays opaque: every agent defines its own output shape, and the
    backend stores and forwards it without inspecting the fields.

    The wire format is camelCase to match the backend contract. Fastify
    validates against a schema and drops fields it does not know, so a
    snake_case body would silently lose the token counts.
    """

    status: Literal["Completed", "Failed"] = Field(
        description="Closing status. Matches the backend agent-execution contract.",
    )
    result: str | None = Field(default=None, description="Serialized agent output")
    error: str | None = Field(default=None, description="Required when status is Failed")
    input_tokens: int | None = Field(default=None, ge=0, alias="inputTokens")
    output_tokens: int | None = Field(default=None, ge=0, alias="outputTokens")

    model_config = ConfigDict(populate_by_name=True)


class CallbackResult(BaseModel):
    """What the backend answered. Useful for logging and for tests."""

    acknowledged: bool
    status_code: int | None = None
    body: str | None = None
    error: str | None = Field(default=None, description="Transport failure, not an HTTP error")