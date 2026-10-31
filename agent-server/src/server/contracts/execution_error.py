"""Safe, source-attributed incident metadata shared by all execution transports."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ExecutionErrorDetail(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    agent_id: str | None = Field(default=None, alias="agentId", max_length=128)
    invocation_id: str | None = Field(default=None, alias="invocationId", max_length=128)
    occurred_at: datetime | None = Field(default=None, alias="occurredAt")
    code: str = Field(min_length=1, max_length=128)
    exception_type: str | None = Field(default=None, alias="exceptionType", max_length=128)
    message: str = Field(min_length=1, max_length=2000)
