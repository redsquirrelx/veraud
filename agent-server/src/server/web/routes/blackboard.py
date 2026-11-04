from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


@router.get("/blackboard", response_class=HTMLResponse)
async def blackboard(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="blackboard.html",
        context={"title": "Blackboard"},
    )
