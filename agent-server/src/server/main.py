from fastapi import APIRouter, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .api.executions import router as executions_router
from .api.schemas import StatusResponse

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
    responses={200: {
        "description": "Agent-server is responding.",
        "content": {"application/json": {"example": {
            "status": "ok", "service": "agent-server",
        }}},
    }},
)
def get_status():
    return {
        "status": "ok",
        "service": "agent-server"
    }

app = FastAPI(
    title="Veraud Agent Server API",
    description=(
        "HTTP API for discovering agents, inspecting their input and output "
        "schemas, and executing agents. Execution requests wait for the result; "
        "optional lifecycle callbacks report progress to the Veraud backend."
    ),
    version="0.0.0",
    openapi_tags=[
        {"name": "Status", "description": "Agent-server service health."},
        {
            "name": "Agents",
            "description": (
                "Discover registered agents, inspect their contracts, "
                "and execute them with optional configuration overrides."
            ),
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


@app.exception_handler(RequestValidationError)
async def validation_error_without_secrets(request, error: RequestValidationError):
    # FastAPI's default `input` may echo the complete config, including API keys.
    details = [{key: value for key, value in item.items() if key not in {"input", "ctx"}} for item in error.errors()]
    return JSONResponse(status_code=422, content={"detail": details})