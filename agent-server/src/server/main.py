from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .api.audits import router as audits_router
from .api.executions import router as executions_router
from .api.pipelines import router as pipelines_router
from .api.schemas import StatusResponse
from .app.audit_service import AuditService
from .blackboard.impls.memory import MemoryBlackboard
from .config.token_budget import token_budget_policy
from .web.router import router as web_router
from .web.router import static_files

router = APIRouter(prefix="/api")


@router.get(
    "/status",
    tags=["Status"],
    response_model=StatusResponse,
    summary="Get agent-server status",
    description=(
        "Returns the agent-server health indicator and service name. "
        "Does not probe model providers or backend callback connectivity."
    ),
    responses={
        200: {
            "description": "Agent-server is responding.",
            "content": {
                "application/json": {
                    "example": {
                        "status": "ok",
                        "service": "agent-server",
                    }
                }
            },
        }
    },
)
def get_status():
    return {"status": "ok", "service": "agent-server"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    token_budget_policy()
    app.state.blackboard = MemoryBlackboard()
    app.state.audit_service = AuditService(app.state.blackboard)
    try:
        yield
    finally:
        await app.state.audit_service.aclose()
        del app.state.audit_service
        del app.state.blackboard


app = FastAPI(
    lifespan=lifespan,
    title="Veraud Agent Server API",
    description=(
        "HTTP API for discovering agents, inspecting their input and output "
        "schemas, and executing agents. Execution requests wait for the result; "
        "optional lifecycle callbacks report progress to the Veraud backend."
        " Maintainability audits can also run asynchronously through /api/audits."
    ),
    version="0.0.0",
    openapi_tags=[
        {"name": "Status", "description": "Agent-server service health."},
        {"name": "Audits", "description": "Asynchronous maintainability audits sharing the server Blackboard."},
        {
            "name": "Agents",
            "description": (
                "Discover registered agents, inspect their contracts, "
                "and execute them with optional configuration overrides."
            ),
        },
        {
            "name": "Pipelines",
            "description": "Repository audit pipelines with explicit per-stage configuration and lifecycle callbacks.",
        },
    ],
    swagger_ui_parameters={
        "docExpansion": "none",
        "deepLinking": True,
        "filter": True,
        "displayRequestDuration": True,
        "operationsSorter": "alpha",
    },
)
app.include_router(router)
app.include_router(executions_router)
app.include_router(pipelines_router)
app.include_router(audits_router)
app.include_router(web_router)
app.mount("/static", static_files, name="web_static")


@app.exception_handler(RequestValidationError)
async def validation_error_without_secrets(request, error: RequestValidationError):
    # FastAPI's default `input` may echo the complete config, including API keys.
    details = [
        {key: value for key, value in item.items() if key not in {"input", "ctx"}}
        for item in error.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": details})
