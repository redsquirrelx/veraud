"""Immutable audit/execution identity, independent of agents and HTTP requests."""

from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .models import NonEmptyString


class AuditIdentity(BaseModel):
    """Reuse for publication retries; derive children from existing assignment IDs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: NonEmptyString = Field(default_factory=lambda: uuid4().hex)
    invocation_id: NonEmptyString = Field(default_factory=lambda: uuid4().hex)

    def child(self, invocation_id: str) -> "AuditIdentity":
        return AuditIdentity(run_id=self.run_id, invocation_id=invocation_id)
