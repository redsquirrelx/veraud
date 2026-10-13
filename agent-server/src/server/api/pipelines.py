from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..app.execution_service import InvalidConfigError
from ..app.pipeline_service import (
    ArchitectureAuditService,
    PipelineExecutionIds,
    PipelineInput,
    PipelineStageConfigs,
    get_pipeline_service,
)
from ..config.logs import get_logger
from .schemas import DomainError, ExecutionConfig, RequestValidationErrorResponse

logger = get_logger("api.pipelines")


router = APIRouter(prefix="/api/pipelines", tags=["Pipelines"])

ServiceDep = Annotated[ArchitectureAuditService, Depends(get_pipeline_service)]

NOT_FOUND = 404
UNPROCESSABLE = 422
TIMED_OUT = 504

TIMEOUT_DETAIL = "Pipeline execution timed out"


class PipelineRequest(BaseModel):
    """Run the analyzer then the architect as one pipeline.

    `execution_ids` are rows the backend created for this run. When present
    each stage reports its own progress back to its row over HTTP; absent
    means nobody is listening and nothing is reported, like the dev runners.
    """

    input: PipelineInput
    config: ExecutionConfig = Field(default_factory=ExecutionConfig)
    stage_configs: PipelineStageConfigs | None = Field(
        default=None,
        description="Per-stage model and credential overrides supplied by the backend. When present, these replace the shared config for each stage.",
    )
    execution_ids: PipelineExecutionIds | None = Field(default=None)
    timeout_seconds: int = Field(
        default=600,
        gt=0,
        description="Seconds before giving up on the whole pipeline",
    )


class PipelineResponse(BaseModel):
    analysis: dict[str, Any] = Field(description="Analyzer output")
    description: dict[str, Any] = Field(description="Architect output")


@router.post(
    "/architecture-audit/run",
    response_model=PipelineResponse,
    summary="Run an analyzer and architect audit",
    description="Runs analyzer then architect over the repository root under a shared deadline. The architect input is derived from analysis. stage_configs supplies independent backend model, credential and generation parameters; config is the shared fallback for callers that omit stage_configs. Optional execution_ids receive per-stage lifecycle callbacks. Returns both opaque agent outputs.",
    responses={
        200: {
            "description": "Analyzer and architect results, preserving each agent's output fields."
        },
        422: {
            "model": DomainError | RequestValidationErrorResponse,
            "description": "Invalid input/configuration or unreadable repository root.",
        },
        504: {
            "model": DomainError,
            "description": "The shared pipeline deadline expired.",
        },
    },
)
async def run_architecture_audit(
    body: PipelineRequest, service: ServiceDep
) -> PipelineResponse:
    """Audit a repository: what kind of project it is, then how it is built."""
    logger.info(
        "POST /api/pipelines/architecture-audit/run root=%r executions=%s",
        body.input.root_path,
        body.execution_ids is not None,
    )

    try:
        result = await service.run(
            body.input,
            body.config,
            body.execution_ids,
            timeout_seconds=body.timeout_seconds,
            stage_configs=body.stage_configs,
        )
    except InvalidConfigError as error:
        raise _http_error(UNPROCESSABLE, str(error)) from None
    except FileNotFoundError as error:
        # A repository path that cannot be read is a bad request, same as on
        # the single-agent endpoint.
        raise _http_error(UNPROCESSABLE, str(error)) from None
    except TimeoutError:
        raise _http_error(TIMED_OUT, TIMEOUT_DETAIL) from None

    logger.info("POST /api/pipelines/architecture-audit/run done")

    return PipelineResponse(
        analysis=result.get("analysis", {}),
        description=result.get("description", {}),
    )


def _http_error(status: int, detail: str) -> HTTPException:
    logger.warning("Pipeline request failed status=%d error=%s", status, detail)
    return HTTPException(status_code=status, detail=detail)
