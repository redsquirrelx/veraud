from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Path, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field


class GraphRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: int = Field(gt=0)
    project_id: int = Field(gt=0)
    branch: str = Field(min_length=1, max_length=255)
    commit_hash: str = Field(pattern=r"^[a-f0-9]{40}$")
    repository_path: str = Field(min_length=1)
    callback_token: str = Field(pattern=r"^[a-f0-9]{64}$", repr=False)


router = APIRouter(prefix="/api/graphs", tags=["Graphs"])


@router.post("", status_code=202, summary="Start a code-only Graphify task")
async def start_graph(body: GraphRequest, request: Request):
    try:
        request.app.state.graph_jobs.start(body)
    except (ValueError, OSError):
        raise HTTPException(422, "Invalid repository or graph request") from None
    except OverflowError:
        raise HTTPException(429, "Graph extraction queue is full") from None
    except RuntimeError:
        raise HTTPException(503, "Graph extraction callbacks are unavailable") from None
    return {"task_id": body.task_id, "accepted": True}


@router.delete("/{task_id}", summary="Stop a graph extraction")
async def cancel_graph(task_id: int, request: Request, x_graph_token: Annotated[str, Header()]):
    try:
        await request.app.state.graph_jobs.cancel(task_id, x_graph_token)
    except PermissionError:
        raise HTTPException(403, "Invalid graph token") from None
    return {"acknowledged": True}


@router.get("/{project_id}/{commit}/{task_id}/artifact", summary="Download a published Graphify artifact")
async def graph_artifact(
    project_id: Annotated[int, Path(gt=0)], commit: Annotated[str, Path(pattern=r"^[a-f0-9]{40}$")],
    task_id: Annotated[int, Path(gt=0)], request: Request,
):
    try:
        artifact = request.app.state.graph_jobs.service.artifact(project_id, commit, task_id)
    except (FileNotFoundError, OSError):
        raise HTTPException(404, "Graph is not available") from None
    return FileResponse(artifact, media_type="application/json", filename="graph.json")
