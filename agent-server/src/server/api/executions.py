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
        logger.warning("Unknown agent: %s", error)
        raise HTTPException(status_code=404, detail=str(error)) from None

    return AgentSchemaResponse(**described)


@router.post("/run", response_model=ExecutionResponse)
async def run_agent(body: ExecutionRequest, service: ServiceDep) -> ExecutionResponse:
    logger.info(
        "POST /api/agents/run agent_type=%r input_keys=%d",
        body.agent_type, len(body.input),
    )

    try:
        result = await service.run(body.agent_type, body.config, body.input)

    except UnknownAgentError as error:
        logger.warning("Unknown agent: %s", error)
        raise HTTPException(status_code=404, detail=str(error)) from None
    except InvalidConfigError as error:
        logger.warning("Invalid config: %s", error)
        raise HTTPException(status_code=422, detail=str(error)) from None
    except InvalidInputError as error:
        logger.warning("Invalid input: %s", error)
        raise HTTPException(status_code=422, detail=str(error)) from None
    except TimeoutError:
        logger.error("Agent %r timed out", body.agent_type)
        raise HTTPException(status_code=504, detail="Agent execution timed out") from None

    logger.info(
        "POST /api/agents/run done agent_type=%r output=%s",
        body.agent_type, type(result).__name__,
    )

    return ExecutionResponse(
        agent_type=body.agent_type,
        result=result.model_dump(),
    )