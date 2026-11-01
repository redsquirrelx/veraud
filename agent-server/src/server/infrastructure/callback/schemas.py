from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from server.contracts.execution_error import ExecutionErrorDetail
from server.contracts.public_errors import public_error_result, public_error_text


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


class ExecutionProgress(BaseModel):
    """Cumulative reported usage; null means the provider supplied no count."""

    input_tokens: int | None = Field(default=None, ge=0, le=2147483647, alias="inputTokens")
    output_tokens: int | None = Field(default=None, ge=0, le=2147483647, alias="outputTokens")
    estimated_tokens: int = Field(default=0, ge=0, le=2147483647, alias="estimatedTokens")

    model_config = ConfigDict(populate_by_name=True)


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
    error_detail: ExecutionErrorDetail | None = Field(default=None, alias="errorDetail")
    input_tokens: int | None = Field(default=None, ge=0, alias="inputTokens")
    output_tokens: int | None = Field(default=None, ge=0, alias="outputTokens")
    estimated_tokens: int | None = Field(default=None, ge=0, alias="estimatedTokens")
    interruption_reason: str | None = Field(default=None, alias="interruptionReason")

    model_config = ConfigDict(populate_by_name=True)

    _public_error = field_validator("error", mode="before")(public_error_text)
    _public_result = field_validator("result", mode="before")(public_error_result)


class InvocationReceipt(BaseModel):
    """Compact internal lifecycle; never contains prompts, evidence or credentials."""

    invocation_id: str = Field(min_length=1, max_length=128)
    parent_invocation_id: str | None = Field(default=None, min_length=1, max_length=128)
    agent_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    status: Literal["running", "completed", "partial", "failed", "cancelled", "timeout"]
    started_at: datetime
    finished_at: datetime | None = None
    input_tokens: int | None = Field(default=None, ge=0, le=2147483647)
    output_tokens: int | None = Field(default=None, ge=0, le=2147483647)
    error: str | None = Field(default=None, max_length=2000)
    error_detail: ExecutionErrorDetail | None = None
    phase: str | None = Field(default=None, min_length=1, max_length=128)
    phase_sequence: int = Field(default=0, ge=0, le=2147483647)

    _public_error = field_validator("error", mode="before")(public_error_text)


class CallbackResult(BaseModel):
    """What the backend answered. Useful for logging and for tests."""

    acknowledged: bool
    status_code: int | None = None
    body: str | None = None
    error: str | None = Field(default=None, description="Transport failure, not an HTTP error")
