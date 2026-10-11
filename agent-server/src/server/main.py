from fastapi import APIRouter, FastAPI

from .api.executions import router as executions_router
from .api.pipelines import router as pipelines_router

router = APIRouter(prefix="/api")

@router.get("/status")
def get_status():
    return {
        "status": "ok",
        "service": "agent-server"
    }

app = FastAPI()
app.include_router(router)
app.include_router(executions_router)
app.include_router(pipelines_router)