from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from ..app.agent_registry import UnknownAgentError
from ..app.execution_service import (
    AgentExecutionService,
    InvalidConfigError,
    InvalidInputError,
    get_execution_service,
)
from ..config.logs import get_logger
from .schemas import AgentSchemaResponse, ExecutionRequest, ExecutionResponse

logger = get_logger("api")


router = APIRouter(prefix="/api/agents", tags=["agents"])

ServiceDep = Annotated[AgentExecutionService, Depends(get_execution_service)]

# Domain error -> HTTP status. Every clause of the except chains below picks a
# status from here, so the error contract is readable in one place.
NOT_FOUND = 404
UNPROCESSABLE = 422
TIMED_OUT = 504

TIMEOUT_DETAIL = "Agent execution timed out"


def _http_error(
    error: Exception,
    status: int,
    agent_type: str,
    detail: str | None = None,
) -> HTTPException:
    """Build the HTTP error for a domain failure, and log it.

    Returns the exception instead of raising it so each handler stays a single
    line. `from None` is applied at the call site to drop the domain traceback.
    """
    text = detail or str(error) or type(error).__name__

    logger.warning(
        "Agent request failed agent_type=%r status=%d error=%s",
        agent_type, status, text,
    )

    return HTTPException(status_code=status, detail=text)


@router.get("", response_model=list[str])
def list_agents(service: ServiceDep) -> list[str]:
    return service.list_agents()


@router.get("/{agent_type}/schema", response_model=AgentSchemaResponse)
def get_agent_schema(agent_type: str, service: ServiceDep) -> AgentSchemaResponse:
    """Publish one agent's input and output shapes.

    The run endpoint is agent agnostic, so this is how a caller learns what to
    send without the contract having to know every agent.
    """
    try:
        described = service.describe_agent(agent_type)
    except UnknownAgentError as error:
        raise _http_error(error, NOT_FOUND, agent_type) from None

    return AgentSchemaResponse(**described)


@router.post("/run", response_model=ExecutionResponse)
async def run_agent(body: ExecutionRequest, service: ServiceDep) -> ExecutionResponse:
    """Run one agent and return its output.

    The service validates the payload against the agent's own schema, builds
    the model client and applies the timeout, so this only translates domain
    errors into HTTP.
    """
    logger.info(
        "POST /api/agents/run agent_type=%r input_keys=%d",
        body.agent_type, len(body.input),
    )

    try:
        result = await service.run(
            body.agent_type,
            body.config,
            body.input,
            execution_id=body.execution_id,
        )

    except UnknownAgentError as error:
        raise _http_error(error, NOT_FOUND, body.agent_type) from None
    except InvalidConfigError as error:
        raise _http_error(error, UNPROCESSABLE, body.agent_type) from None
    except InvalidInputError as error:
        raise _http_error(error, UNPROCESSABLE, body.agent_type) from None
    except FileNotFoundError as error:
        # An agent that reads from disk raises this when the path is wrong,
        # which is a bad request rather than a server fault.
        raise _http_error(error, UNPROCESSABLE, body.agent_type) from None
    except TimeoutError as error:
        raise _http_error(
            error, TIMED_OUT, body.agent_type, detail=TIMEOUT_DETAIL
        ) from None

    logger.info(
        "POST /api/agents/run done agent_type=%r output=%s",
        body.agent_type, type(result).__name__,
    )

    return ExecutionResponse(
        agent_type=body.agent_type,
        result=result.model_dump(),
    )