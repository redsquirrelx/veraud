"""Public process-local audit lifecycle and snapshot contracts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from server.blackboard.models import Assessment, Evidence, Finding
from server.services.audit_diagnostics import ExecutionDiagnostic

AuditStatus = Literal["queued", "running", "completed", "partial", "failed", "cancelled"]


class AuditState(BaseModel):
    """Public lifecycle state; credentials never enter this model."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    invocation_id: str
    status: AuditStatus
    view_url: str
    created_at: datetime
    error: str | None = None


class AuditWait(BaseModel):
    agent_id: str | None
    invocation_id: str | None
    reason: str
    source: str | None
    retry_after_seconds: float | None = Field(ge=0)


class AuditActivity(BaseModel):
    agent_id: str | None
    invocation_id: str | None
    stage: str
    started_at: datetime
    elapsed_seconds: float = Field(ge=0)
    status: Literal["running", "cancellation_pending"]


class AuditSnapshot(AuditState):
    """Lifecycle state and currently published audit knowledge."""

    findings: list[Finding] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    assessments: list[Assessment] = Field(default_factory=list)
    waiting: list[AuditWait] = Field(default_factory=list)
    execution_issues: list[ExecutionDiagnostic] = Field(default_factory=list)
    activity: list[AuditActivity] = Field(default_factory=list)
    last_progress_at: datetime | None = None
    active_seconds_remaining: float | None = None
    wall_seconds_remaining: float | None = None
