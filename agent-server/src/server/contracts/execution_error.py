"""Safe, source-attributed incident metadata shared by all execution transports."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .public_errors import EXCEPTIONS, MESSAGES, public_error_code, public_identifier


class ExecutionErrorDetail(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    agent_id: str | None = Field(default=None, alias="agentId", max_length=128)
    invocation_id: str | None = Field(default=None, alias="invocationId", max_length=128)
    occurred_at: datetime | None = Field(default=None, alias="occurredAt")
    code: str = Field(min_length=1, max_length=128)
    exception_type: str | None = Field(default=None, alias="exceptionType", max_length=128)
    message: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="before")
    @classmethod
    def public_values(cls, value):
        if not isinstance(value, dict):
            return value
        data = dict(value)
        code = public_error_code(data.get("code"))
        data.update(code=code, message=MESSAGES[code])
        for name, alias in (("agent_id", "agentId"), ("invocation_id", "invocationId")):
            if alias in data:
                data[alias] = public_identifier(data[alias])
            elif name in data:
                data[name] = public_identifier(data[name])
        key = "exceptionType" if "exceptionType" in data else "exception_type"
        if not isinstance(data.get(key), str) or data.get(key) not in EXCEPTIONS:
            data[key] = None
        return data
