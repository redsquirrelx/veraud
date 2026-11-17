from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from server.infrastructure.tracing_sink import (
    reset_trace_context,
    set_trace_context,
    trace_event,
)

from .api.audits import router as audits_router
from .api.executions import router as executions_router
from .api.graphs import router as graphs_router
from .api.pipelines import router as pipelines_router
from .api.schemas import StatusResponse
from .app.audit_service import AuditService
from .app.graph_jobs import GraphJobs
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
    import asyncio

    from .agent_services.execution_tracking.buffer import (
        execution_event_delivery_worker,
    )
    from .agent_services.execution_tracking.observer import default_callback_sink

    token_budget_policy()
    app.state.blackboard = MemoryBlackboard()
    app.state.audit_service = AuditService(app.state.blackboard)
    app.state.graph_jobs = GraphJobs()
    stop_events = asyncio.Event()
    event_delivery = asyncio.create_task(execution_event_delivery_worker(stop_events, default_callback_sink))
    try:
        yield
    finally:
        await app.state.graph_jobs.aclose()
        await app.state.audit_service.aclose()
        stop_events.set()
        try:
            await asyncio.wait_for(event_delivery, 3)
        except TimeoutError:
            pass  # Unacknowledged events exist only in memory and cannot survive shutdown.
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
app.include_router(graphs_router)
app.include_router(web_router)
app.mount("/static", static_files, name="web_static")


@app.middleware("http")
async def execution_trace(request, call_next):
    trace_id = request.headers.get("x-veraud-trace-id")
    if not trace_id:
        return await call_next(request)
    try:
        execution_id = int(request.headers.get("x-veraud-execution-id") or "0")
    except ValueError:
        execution_id = None
    agent_type = request.headers.get("x-veraud-agent-type") or "architecture_context"
    token = set_trace_context(trace_id, execution_id, agent_type)
    from time import monotonic
    started = monotonic()
    trace_event("http.request.started", span_id=trace_id, message=f"{request.method} {request.url.path}")
    try:
        response = await call_next(request)
        trace_event("http.request.completed", span_id=trace_id, status="ok" if response.status_code < 400 else "error",
                    error_code=f"http_{response.status_code}" if response.status_code >= 400 else None,
                    duration_ms=round((monotonic() - started) * 1000, 3), message=f"{request.method} {request.url.path}",
                    details={"httpStatus": response.status_code})
        response.headers["x-veraud-trace-id"] = trace_id
        return response
    except Exception as error:
        trace_event("http.request.unhandled_error", span_id=trace_id, status="error",
                    error_code=type(error).__name__, duration_ms=round((monotonic() - started) * 1000, 3),
                    message="Unhandled agent-server request failure",
                    details={"errorType": type(error).__name__, "message": str(error)})
        raise
    finally:
        reset_trace_context(token)


@app.exception_handler(RequestValidationError)
async def validation_error_without_secrets(request, error: RequestValidationError):
    # FastAPI's default `input` may echo the complete config, including API keys.
    details = [
        {key: value for key, value in item.items() if key not in {"input", "ctx"}}
        for item in error.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": details})
