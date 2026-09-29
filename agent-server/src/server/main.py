from fastapi import FastAPI, APIRouter

router = APIRouter()

@router.get("/status")
def get_status():
    return {
        "status": "ok",
        "service": "agent-server"
    }

app = FastAPI()
app.include_router(router)