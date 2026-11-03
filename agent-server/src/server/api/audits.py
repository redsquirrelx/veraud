import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field, ValidationError

from server.api.schemas import DomainError, RequestValidationErrorResponse
from server.app.execution_config import ExecutionConfig
from server.reporting import SoftwareAuditReport
from server.reporting.docx import DOCX_MEDIA_TYPE, render_audit_report_docx
from server.reporting.schemas import ReportGenerationSummary
from server.reporting.snapshot import BlackboardSnapshot, report_from_snapshot

from ..agents.functional_adequacy.schemas import FunctionalRequirement
from ..agents.maintainability.manager import MaintainabilityRequest
from ..agents.security.audit import SecurityAuditRequest
from ..app.audit_attributes import QualityAttributes
from ..app.audit_configuration import category_type, validate_category
from ..app.audit_options import AuditExecutionOptions
from ..app.audit_service import AuditService, AuditSnapshot, AuditState
from ..app.errors import InvalidConfigError
from ..contracts.public_errors import public_error_fields, public_error_text

router = APIRouter(prefix="/api/audits", tags=["Audits"])


@router.get("/configuration/{attribute}")
async def audit_configuration_schema(attribute: str):
    """Describe the category's developer controls using runtime-owned configuration contracts."""
    try:
        return {"schema": category_type(attribute).model_json_schema(), "level": "developer"}
    except ValueError as error:
        raise HTTPException(status_code=422, detail=public_error_text(str(error))) from None


@router.post("/configuration/{attribute}/validate")
async def validate_audit_configuration(attribute: str, body: dict):
    """Validate category operating overrides, including output capacity, without starting an audit."""
    try:
        return {"values": validate_category(attribute, body)}
    except (ValidationError, ValueError) as error:
        raise HTTPException(status_code=422, detail=public_error_text(str(error))) from None


class StartAuditRequest(AuditExecutionOptions):
    """Repository scope and model selection for a background quality audit."""

    repository_path: str = Field(min_length=1, pattern=r"\S")
    request: MaintainabilityRequest = Field(default_factory=MaintainabilityRequest)
    attributes: QualityAttributes | None = None
    functional_requirements: list[FunctionalRequirement] | None = Field(default=None, min_length=1, max_length=100)
    security_request: SecurityAuditRequest | None = Field(default=None,
        description="Security scope. With attributes, participates only when security is selected; without attributes, selects security for compatibility.")
    config: ExecutionConfig = Field(default_factory=ExecutionConfig)
    agent_configs: dict[str, ExecutionConfig] | None = Field(default=None,
        description="Explicit model and API key for all selected participants: nine maintainability agent IDs, security, or all ten for a joint audit. Keys are never included in audit results.")
    agent_config: str = Field(default="dummy", min_length=1, description="Server YAML entry supplying model defaults.")


def get_audit_service(request: Request) -> AuditService:
    return request.app.state.audit_service


ServiceDep = Annotated[AuditService, Depends(get_audit_service)]


@router.post("/reports/from-snapshot", response_model=SoftwareAuditReport,
    summary="Build report JSON from an exported Blackboard snapshot",
    description="Uses an isolated Blackboard, without a live run, repository access or model calls.")
async def build_snapshot_report(body: BlackboardSnapshot, response: Response, service: ServiceDep) -> SoftwareAuditReport:
    response.headers["Cache-Control"] = "no-store"
    report = await report_from_snapshot(body)
    service.retain_report(report)
    response.headers["X-Report-Generation-ID"] = report.annexes_and_traceability.generation.generation_id
    return report


@router.post("/reports/from-snapshot.docx", response_class=Response,
    summary="Build a Word report from an exported Blackboard snapshot",
    description="Builds and retains a canonical report from an isolated snapshot, then renders Word without repository access or model calls.",
    responses={200: {"content": {DOCX_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}}}})
async def build_snapshot_report_docx(body: BlackboardSnapshot, service: ServiceDep) -> Response:
    report = await report_from_snapshot(body)
    service.retain_report(report)
    content = await asyncio.to_thread(render_audit_report_docx, report)
    return Response(content=content, media_type=DOCX_MEDIA_TYPE, headers={
        "Content-Disposition": 'attachment; filename="informe-auditoria.docx"',
        "X-Report-Generation-ID": report.annexes_and_traceability.generation.generation_id,
        "Cache-Control": "no-store"})


@router.post("", status_code=202, response_model=AuditState,
    summary="Start a quality audit with the selected quality attributes",
    description="Schedules the manager in this server process and returns its run_id immediately. Model defaults come from agent_config; the audit shares the application's in-memory Blackboard. The audit timeout measures active time: quota and provider recovery waits pause execution and resume automatically without consuming that timeout.",
    responses={202: {"description": "Audit accepted for asynchronous execution."},
               422: {"model": DomainError | RequestValidationErrorResponse, "description": "Invalid repository, configuration or request."}})
async def start_audit(body: StartAuditRequest, response: Response, service: ServiceDep) -> AuditState:
    try:
        security_only = body.attributes == ["security"] or body.attributes is None and body.security_request is not None
        state = service.start(body.repository_path,
            (body.security_request or SecurityAuditRequest()) if security_only else body.request, body.config, body.agent_config,
            body.agent_defaults, body.audit_budget, body.call_limits, agent_configs=body.agent_configs,
            attributes=body.attributes, security_request=body.security_request, security_config=body.security_config,
            functional_requirements=body.functional_requirements, attribute_options=body.attribute_options,
            functional_config=body.functional_config)
    except (InvalidConfigError, FileNotFoundError) as error:
        raise HTTPException(status_code=422, detail=public_error_text(str(error))) from None
    response.headers["Location"] = f"/api/audits/{state.run_id}"
    return state


@router.post("/{run_id}/cancel", status_code=202, response_model=AuditState,
    summary="Request cancellation of one audit",
    description="Idempotently stops admission of new work and requests cancellation of active tasks. "
        "The state remains cancelling until owned tasks and cleanup finish. Published records are retained.",
    responses={404: {"model": DomainError, "description": "Audit not found in this process."}})
async def cancel_audit(run_id: str, response: Response, service: ServiceDep) -> AuditState:
    if service.get(run_id) is None:
        raise HTTPException(status_code=404, detail="Audit not found.")
    await service.cancel(run_id)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = f"/api/audits/{run_id}"
    return service.get(run_id)


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
    return AuditSnapshot.model_validate(public_error_fields(state.model_dump(mode="json")))


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
    response.headers["X-Report-Generation-ID"] = report.annexes_and_traceability.generation.generation_id
    return SoftwareAuditReport.model_validate(public_error_fields(report.model_dump(mode="json")))


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
        "X-Report-Generation-ID": report.annexes_and_traceability.generation.generation_id,
        "Cache-Control": "no-store"})


@router.get("/{run_id}/report-generations", response_model=list[ReportGenerationSummary],
    summary="List retained report generations for a live or imported audit",
    description="Returns metadata for generations retained in this server process, without building a new report.")
async def list_report_generations(run_id: str, response: Response, service: ServiceDep) -> list[ReportGenerationSummary]:
    response.headers["Cache-Control"] = "no-store"
    return service.report_generations(run_id)


@router.get("/{run_id}/report-generations/{generation_id}", response_model=SoftwareAuditReport,
    summary="Retrieve an original report and its construction trace without regenerating it",
    description="Returns the exact retained canonical report and construction trace. Returns 404 when the generation is unavailable.")
async def get_report_generation(run_id: str, generation_id: str, response: Response, service: ServiceDep) -> SoftwareAuditReport:
    report = service.saved_report(run_id, generation_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report generation not found.")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Report-Generation-ID"] = generation_id
    return report
