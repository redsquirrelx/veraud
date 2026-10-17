import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from config.agents.audit import AuditAgentDefaults, AuditCallLimits
from config.agents.budgets import TokenBudgetConfig

from ..agents.audit_report import SoftwareAuditReport
from ..agents.maintainability.manager import MaintainabilityRequest
from ..app.audit_service import AuditService, AuditSnapshot, AuditState
from ..app.execution_service import InvalidConfigError
from ..services.audit_report_docx import DOCX_MEDIA_TYPE, render_audit_report_docx
from .schemas import DomainError, ExecutionConfig, RequestValidationErrorResponse

router = APIRouter(prefix="/api/audits", tags=["Audits"])


class StartAuditRequest(BaseModel):
    """Repository scope and model selection for a background maintainability audit."""

    repository_path: str = Field(min_length=1, pattern=r"\S")
    request: MaintainabilityRequest = Field(default_factory=MaintainabilityRequest)
    config: ExecutionConfig = Field(default_factory=ExecutionConfig)
    agent_configs: dict[str, ExecutionConfig] | None = Field(default=None,
        description="Explicit model and API key for every maintainability manager, coordinator and investigator. When supplied, all nine agent IDs are required. Keys are never included in audit results.")
    agent_config: str = Field(default="dummy", min_length=1, description="Server YAML entry supplying model defaults.")
    agent_defaults: AuditAgentDefaults | None = Field(default=None,
        description="Developer defaults: context and personal token allowance at all levels; max_model_calls and max_tool_calls apply only to investigators. Aggregate manager/coordinator call budgets retain their defaults unless call_limits overrides them. Omitted fields retain existing defaults.",
        json_schema_extra={"x-config-level": "developer"})
    audit_budget: TokenBudgetConfig | None = Field(default=None,
        description="Shared token cap across all agents, enforced per provider attempt. When omitted, uses the manager's server-default token budget, independently of agent_defaults.")
    call_limits: AuditCallLimits | None = Field(default=None,
        description="Developer call envelopes by hierarchy level: manager, coordinator and investigator. Each object accepts max_model_calls and max_tool_calls. Overrides take precedence over common investigator defaults; parent budgets must cover the initial child wave and model synthesis. Tool consumption by descendants counts against parent limits.",
        json_schema_extra={"x-config-level": "developer"})


def get_audit_service(request: Request) -> AuditService:
    return request.app.state.audit_service


ServiceDep = Annotated[AuditService, Depends(get_audit_service)]


@router.post("", status_code=202, response_model=AuditState,
    summary="Start a maintainability audit",
    description="Schedules the manager in this server process and returns its run_id immediately. Model defaults come from agent_config; the audit shares the application's in-memory Blackboard. The audit timeout measures active time: quota and provider recovery waits pause execution and resume automatically without consuming that timeout.",
    responses={202: {"description": "Audit accepted for asynchronous execution."},
               422: {"model": DomainError | RequestValidationErrorResponse, "description": "Invalid repository, configuration or request."}})
async def start_audit(body: StartAuditRequest, response: Response, service: ServiceDep) -> AuditState:
    try:
        state = service.start(body.repository_path, body.request, body.config, body.agent_config,
            body.agent_defaults, body.audit_budget, body.call_limits, agent_configs=body.agent_configs)
    except (InvalidConfigError, FileNotFoundError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    response.headers["Location"] = f"/api/audits/{state.run_id}"
    return state


@router.get("/{run_id}", response_model=AuditSnapshot,
    summary="Get audit execution status",
    description="Returns the lifecycle state, active per-invocation waits (reason, remaining delay and source), and all currently published evidence, findings and assessments for this run_id. Partial records are available while the audit is running and remain visible after failure.",
    responses={200: {"description": "Current audit state and published Blackboard records."},
               404: {"model": DomainError, "description": "No audit with this run_id in this process."}})
async def get_audit(run_id: str, response: Response, service: ServiceDep) -> AuditSnapshot:
    state = service.snapshot(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Audit not found.")
    response.headers["Cache-Control"] = "no-store"
    return state


@router.get("/{run_id}/report", response_model=SoftwareAuditReport,
    summary="Build the software quality audit report from Blackboard records",
    description="Returns a versioned JSON document with ten report sections. Uses only this audit's published Blackboard knowledge; partial and unevaluated attributes remain explicit. No model calls or repository reads are performed.",
    responses={200: {"description": "Source-linked audit report."},
        404: {"model": DomainError, "description": "Audit not found."}})
async def get_audit_report(run_id: str, response: Response, service: ServiceDep) -> SoftwareAuditReport:
    report = await service.report(run_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Audit not found.")
    response.headers["Cache-Control"] = "no-store"
    return report


@router.get("/{run_id}/report.docx", response_class=Response,
    summary="Download the audit report as a Word document",
    description="Deterministically renders the Blackboard-derived JSON report as DOCX. Includes partial and unevaluated results without additional model calls.",
    responses={200: {"description": "Word document download.", "content": {
        DOCX_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}}},
        404: {"model": DomainError, "description": "Audit not found."}})
async def download_audit_report_docx(run_id: str, service: ServiceDep) -> Response:
    report = await service.report(run_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Audit not found.")
    content = await asyncio.to_thread(render_audit_report_docx, report)
    return Response(content=content, media_type=DOCX_MEDIA_TYPE, headers={
        "Content-Disposition": 'attachment; filename="informe-auditoria.docx"',
        "Cache-Control": "no-store"})
