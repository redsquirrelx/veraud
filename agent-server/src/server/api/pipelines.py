from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field

from ..app.execution_service import InvalidConfigError
from ..app.pipeline_service import (
    GenericPipelineService,
    UnknownPipelineError,
    get_generic_pipeline_service,
)
from ..config.logs import get_logger
from .dependencies import BlackboardDep
from .schemas import DomainError, ExecutionConfig, RequestValidationErrorResponse

logger = get_logger("api.pipelines")


router = APIRouter(prefix="/api/pipelines", tags=["Pipelines"])

ServiceDep = Annotated[GenericPipelineService, Depends(get_generic_pipeline_service)]

NOT_FOUND = 404
UNPROCESSABLE = 422
TIMED_OUT = 504

TIMEOUT_DETAIL = "Pipeline execution timed out"


class GenericPipelineRequest(BaseModel):
    """Run any registered pipeline by name.

    `stage_configs` and `execution_ids` are keyed by stage name. When
    `execution_ids` is present each stage reports back to its own backend
    row; absent means nobody is listening and nothing is reported.
    """

    input: dict[str, Any] = Field(
        default_factory=dict,
        description="Pipeline input. Validated against that pipeline's input schema.",
    )
    config: ExecutionConfig = Field(default_factory=ExecutionConfig)
    stage_configs: dict[str, ExecutionConfig] | None = Field(
        default=None,
        description="Per-stage model overrides; quality-audit requires explicit entries for all nine maintainability agents, including coordinators and investigators, when supplied.",
    )
    execution_ids: dict[str, Annotated[int, Field(ge=1)]] | None = Field(default=None)
    timeout_seconds: int = Field(
        default=600,
        gt=0,
        description="Seconds before giving up on the whole pipeline",
    )


@router.get(
    "",
    response_model=list[str],
    summary="List registered pipelines",
    description="Returns registered pipeline names in alphabetical order. Use a name from this list with POST /api/pipelines/{name}/run.",
    responses={200: {"description": "Alphabetically sorted registered pipeline names."}},
)
def list_pipelines(service: ServiceDep) -> list[str]:
    return service.list_pipelines()


@router.post(
    "/{name}/run",
    response_model=dict[str, Any],
    summary="Run a registered pipeline",
    description="Runs the named pipeline over the given input under a shared deadline. stage_configs supplies independent per-stage model and credential overrides; config is the shared fallback. Optional execution_ids receive per-stage lifecycle callbacks. Returns each stage's opaque outputs keyed by stage artifact name.",
    responses={
        404: {
            "model": DomainError,
            "description": "The requested pipeline is not registered.",
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
async def run_pipeline(
    request: Request,
    name: Annotated[str, Path(description="Registered pipeline name from GET /api/pipelines.")],
    body: GenericPipelineRequest,
    service: ServiceDep,
    blackboard: BlackboardDep,
) -> dict[str, Any]:
    """Run one registered pipeline and return its stage outputs."""
    logger.info(
        "POST /api/pipelines/%s/run executions=%s",
        name,
        body.execution_ids is not None,
    )

    try:
        result = await service.run(
            name,
            body.input,
            body.config,
            stage_configs=body.stage_configs,
            execution_ids=body.execution_ids,
            timeout_seconds=body.timeout_seconds,
            blackboard=blackboard,
            audit_service=request.app.state.audit_service,
        )
    except UnknownPipelineError as error:
        raise _http_error(NOT_FOUND, str(error)) from None
    except InvalidConfigError as error:
        raise _http_error(UNPROCESSABLE, str(error)) from None
    except FileNotFoundError as error:
        raise _http_error(UNPROCESSABLE, str(error)) from None
    except TimeoutError:
        raise _http_error(TIMED_OUT, TIMEOUT_DETAIL) from None

    logger.info("POST /api/pipelines/%s/run done", name)

    return result


def _http_error(status: int, detail: str) -> HTTPException:
    logger.warning("Pipeline request failed status=%d error=%s", status, detail)
    return HTTPException(status_code=status, detail=detail)
