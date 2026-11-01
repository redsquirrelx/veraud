"""Content-free execution history shared by runtimes and delivery adapters."""

import math
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from .public_errors import public_identifier

EventKind = Literal[
    "execution.started", "execution.finished", "invocation.started", "invocation.finished", "phase.changed",
    "node.started", "node.finished", "tool.started", "tool.finished", "model.started", "model.finished",
    "provider.request", "provider.retry", "provider.wait", "provider.error", "provider.retry_skipped",
    "activity.started", "activity.finished", "wait.started", "wait.finished", "publication.created", "audit.state_changed",
]
EventStatus = Literal["running", "completed", "partial", "failed", "cancelling", "cancelled", "timeout", "rejected", "waiting"]
METRICS = frozenset({"seconds", "wait_seconds", "attempt", "attempts", "retry", "delay_seconds", "http_status",
    "input_tokens", "output_tokens", "estimated_tokens", "cache_hit", "phase_sequence"})


class ExecutionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, alias_generator=to_camel)

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    stream_id: str
    sequence: int = Field(ge=1, le=2147483647)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    run_id: str | None = None
    invocation_id: str | None = None
    parent_invocation_id: str | None = None
    agent_id: str | None = None
    action_id: str
    parent_action_id: str | None = None
    source_id: str | None = None
    kind: EventKind
    name: str | None = None
    status: EventStatus | None = None
    metadata: dict[str, int | float | bool] = Field(default_factory=dict)

    @field_validator("run_id", "invocation_id", "parent_invocation_id", "agent_id", "parent_action_id", "source_id", "name", mode="before")
    @classmethod
    def safe_identifier(cls, value):
        return public_identifier(value) if isinstance(value, str) else None

    @field_validator("action_id", mode="before")
    @classmethod
    def safe_action(cls, value):
        return public_identifier(value) if isinstance(value, str) and public_identifier(value) else "unknown"

    @field_validator("metadata", mode="before")
    @classmethod
    def safe_metrics(cls, value):
        return {key: item for key, item in value.items() if key in METRICS
            and (isinstance(item, bool) if key == "cache_hit" else isinstance(item, (int, float))
                and not isinstance(item, bool) and math.isfinite(item) and 0 <= item <= 9007199254740991)}
