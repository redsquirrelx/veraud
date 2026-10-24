import asyncio
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Path

from ..app.agent_catalog import (
    AgentCatalog,
    AgentDetail,
    describe_catalog_agent,
    list_agent_catalog,
)
from ..app.agent_registry import UnknownAgentError
from ..app.execution_service import (
    AgentExecutionService,
    InvalidConfigError,
    InvalidInputError,
    build_model,
    get_execution_service,
)
from ..app.model_access import access_failure
from ..config.logs import get_logger
from ..config.schemas import ModelCredentials, ModelSettings
from .dependencies import BlackboardDep
from .schemas import (
    AgentSchemaResponse,
    DomainError,
    ExecutionRequest,
    ExecutionResponse,
    RequestValidationErrorResponse,
    VerifyAccessRequest,
    VerifyAccessResponse,
)

logger = get_logger("api")


router = APIRouter(prefix="/api/agents", tags=["Agents"])

ServiceDep = Annotated[AgentExecutionService, Depends(get_execution_service)]


@router.post(
    "/verify-access", response_model=VerifyAccessResponse,
    summary="Verify credential access to a model",
    description="Performs a minimal generation request against the explicit provider and model. May incur provider usage. No agent, callbacks or server credential fallback. Timeout: 25 seconds. Provider error bodies and API keys are never returned.",
    responses={
        422: {"model": DomainError | RequestValidationErrorResponse, "description": "Invalid verification configuration."},
        403: {"model": DomainError, "description": "Credential or permissions rejected."},
        404: {"model": DomainError, "description": "Model not found or unavailable for the credential."},
        429: {"model": DomainError, "description": "Provider rate limit or quota exceeded."},
        502: {"model": DomainError, "description": "Verification could not be completed."},
        503: {"model": DomainError, "description": "Provider temporarily unavailable."},
        504: {"model": DomainError, "description": "Provider verification timed out."},
    },
)
async def verify_access(body: VerifyAccessRequest) -> VerifyAccessResponse:
    if not body.model.provider or not body.model.name or not body.api_key.strip():
        raise HTTPException(status_code=422, detail="Explicit provider, model and credential are required")
    try:
        model = build_model(ModelSettings(
            provider=body.model.provider, name=body.model.name,
            temperature=body.model.temperature if body.model.temperature is not None else 0.2, max_tokens=64,
        ), ModelCredentials(api_key=body.api_key))
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid provider or model configuration") from None
    except Exception as error:  # noqa: BLE001 - classify SDK initialization failures without exposing payloads
        status, detail = access_failure(error)
        raise HTTPException(status_code=status, detail=detail) from None
    try:
        await asyncio.wait_for(model.generate("Reply with OK."), timeout=25)
    except Exception as error:  # noqa: BLE001 - SDK errors must not expose provider bodies or credentials.
        status, detail = access_failure(error)
        logger.warning("Model access verification failed status=%d exception_type=%s", status, type(error).__name__)
        raise HTTPException(status_code=status, detail=detail) from None
    return VerifyAccessResponse(verified=True)

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


@router.get(
    "",
    response_model=list[str],
    summary="List registered agents",
    description=(
        "Returns registered agent names in alphabetical order. Use a name from "
        "this list to inspect its schema or execute it. Entries in the server's "
        "configuration are not necessarily registered agents."
    ),
    responses={200: {
        "description": "Alphabetically sorted registered agent names.",
        "content": {"application/json": {"example": ["dummy"]}},
    }},
)
def list_agents(service: ServiceDep) -> list[str]:
    return service.list_agents()


@router.get(
    "/catalog", response_model=AgentCatalog,
    summary="Discover all agents and workflow participants",
    description="Versioned backend catalog of direct agents, pipeline stages and internal participants. "
        "Includes hierarchy, execution modes and model configuration groups. Discovery does not execute agents. "
        "GET /api/agents continues to list only directly executable agents.",
)
def agent_catalog(service: ServiceDep) -> AgentCatalog:
    return list_agent_catalog(service)


@router.get(
    "/catalog/{agent_id}", response_model=AgentDetail,
    summary="Inspect a catalog agent and its public configuration",
    description="Returns typed schemas when available, plus user-level operating settings derived from the "
        "effective configuration. No credentials or developer controls are published. Null schemas mean "
        "the participant has no standalone Pydantic input/output contract published here. Aliases resolve "
        "to the canonical agent_id.",
    responses={404: {"model": DomainError, "description": "Unknown catalog agent."}},
)
def catalog_agent(agent_id: str, service: ServiceDep) -> AgentDetail:
    try:
        return describe_catalog_agent(service, agent_id)
    except UnknownAgentError as error:
        raise _http_error(error, NOT_FOUND, agent_id) from None


@router.get(
    "/{agent_type}/schema",
    response_model=AgentSchemaResponse,
    summary="Inspect an agent's input and output schemas",
    description=(
        "Returns JSON Schema documents generated from the registered agent's "
        "Pydantic input and output models. Use input_schema to construct the "
        "input object for POST /api/agents/run; output_schema describes its "
        "result. Start with GET /api/agents, inspect the chosen agent here, then "
        "submit its input to POST /api/agents/run. Nested references resolve "
        "within each schema document."
    ),
    responses={
        200: {"description": "Agent name and its input/output JSON Schema documents."},
        NOT_FOUND: {
            "model": DomainError,
            "description": "The requested agent is not registered.",
            "content": {"application/json": {"example": {
                "detail": "\"Unknown agent: 'missing'\"",
            }}},
        },
    },
)
def get_agent_schema(
    agent_type: Annotated[str, Path(
        description="Registered agent name from GET /api/agents.",
        examples=["dummy"],
    )],
    service: ServiceDep,
) -> AgentSchemaResponse:
    """Publish one agent's input and output shapes.

    The run endpoint is agent agnostic, so this is how a caller learns what to
    send without the contract having to know every agent.
    """
    try:
        described = service.describe_agent(agent_type)
    except UnknownAgentError as error:
        raise _http_error(error, NOT_FOUND, agent_type) from None

    return AgentSchemaResponse(**described)


@router.post(
    "/run",
    response_model=ExecutionResponse,
    summary="Execute an agent and return its result",
    description=(
        "Resolves model configuration, validates input against the selected "
        "agent's schema, and waits for execution to finish before returning "
        "the result. This is not a queued-job acknowledgement. Overrides are "
        "merged with server defaults; an unsupported resolved provider causes "
        "a configuration error. Optional execution_id enables lifecycle "
        "callbacks to the backend when its settings are available. The timeout "
        "covers the agent run, not configuration or callback delivery. Discover "
        "agent names with GET /api/agents and consult "
        "GET /api/agents/{agent_type}/schema for the input and result formats. "
        "Omitted configuration fields use server defaults; null numeric "
        "overrides also use defaults, while empty provider/name/key strings "
        "fall back to configured values. Without execution_id, no callbacks "
        "are sent. With it, the server reports running and Completed/Failed "
        "outcomes when backend settings are available; callback delivery "
        "failures do not discard the execution result."
    ),
    responses={
        200: {
            "description": "Completed execution with the agent's output as a nested result object.",
            "content": {"application/json": {"example": {
                "agent_type": "dummy",
                "result": {
                    "evaluated_attribute": "maintainability",
                    "score": 90.0,
                    "findings": [],
                    "recommendations": [],
                },
            }}},
        },
        NOT_FOUND: {
            "model": DomainError,
            "description": "The requested agent is not registered.",
            "content": {"application/json": {"example": {
                "detail": "\"Unknown agent: 'missing'\"",
            }}},
        },
        UNPROCESSABLE: {
            "model": DomainError | RequestValidationErrorResponse,
            "description": (
                "Invalid HTTP request (detail is a list), or invalid resolved "
                "configuration, agent input or missing file (detail is a string)."
            ),
            "content": {"application/json": {"examples": {
                "requestValidation": {
                    "summary": "Missing required request field",
                    "value": {"detail": [{
                        "type": "missing", "loc": ["body", "agent_type"],
                        "msg": "Field required", "input": {},
                    }]},
                },
                "invalidConfiguration": {
                    "summary": "Unsupported resolved model provider",
                    "value": {"detail": "Unsupported model provider: 'groq'"},
                },
            }}},
        },
        TIMED_OUT: {
            "model": DomainError,
            "description": "The agent run exceeded its resolved timeout.",
            "content": {"application/json": {"example": {"detail": TIMEOUT_DETAIL}}},
        },
    },
)
async def run_agent(
    body: Annotated[ExecutionRequest, Body(openapi_examples={
        "dummy": {
            "summary": "Audit a code snippet with the dummy agent",
            "description": (
                "Explicitly selects a supported provider. Requires a configured "
                "provider key or config.api_key; this is not an offline execution."
            ),
            "value": {
                "agent_type": "dummy",
                "config": {
                    "model": {"provider": "openrouter", "name": "openai/gpt-oss-120b"},
                    "timeout_seconds": 60,
                },
                "input": {"code": "def add(a, b): return a + b"},
            },
        },
    })],
    service: ServiceDep,
    blackboard: BlackboardDep,
) -> ExecutionResponse:
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
            blackboard=blackboard,
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
