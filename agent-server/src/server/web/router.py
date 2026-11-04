from pathlib import Path

from fastapi import APIRouter
from fastapi.staticfiles import StaticFiles

from .routes.blackboard import router as blackboard_router

router = APIRouter(include_in_schema=False)
router.include_router(blackboard_router)

static_files = StaticFiles(directory=Path(__file__).parent / "static")
