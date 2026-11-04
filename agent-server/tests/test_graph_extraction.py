import asyncio
import os
import stat
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.graphs import GraphRequest, router
from server.app.graph_jobs import GraphJobs
from server.config.settings import GraphSettings
from server.infrastructure.callback.client import CallbackClient, build_callback_config
from server.services.graph_extraction import (
    GraphExtractionError,
    GraphExtractionService,
)
from server.services.graphify import GraphifyError


def git(repository, *arguments):
    return subprocess.check_output(["git", "-C", str(repository), *arguments], text=True).strip()


def checkout(tmp_path):
    workspace = tmp_path / "workspace"
    repository = workspace / "repo"
    repository.mkdir(parents=True)
    git(repository, "init")
    git(repository, "config", "user.name", "Test")
    git(repository, "config", "user.email", "test@example.test")
    (repository / "source.py").write_text("selected = 1\n")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "selected")
    commit = git(repository, "rev-parse", "HEAD")
    (repository / "source.py").write_text("selected = 2\n")
    (repository / "untracked.py").write_text("secret = True\n")
    return workspace, repository, commit


def request(repository, commit, task_id=1):
    return GraphRequest(task_id=task_id, project_id=2, branch="main", commit_hash=commit,
                        repository_path=str(repository), callback_token="a" * 64)


def test_extracts_selected_commit_and_publishes_atomically(tmp_path):
    workspace, repository, commit = checkout(tmp_path)
    phases = []
    graphs = tmp_path / "graphs"

    class Structure:
        async def extract_structure(self, snapshot, output):
            assert (snapshot / "source.py").read_text() == "selected = 1\n"
            assert not (snapshot / "untracked.py").exists()
            assert not (graphs / "2" / commit / "1").exists()
            (output / "graphify-out").mkdir(parents=True)
            (output / "graphify-out" / "graph.json").write_text('{"nodes": [], "edges": []}')

    service = GraphExtractionService(workspace, graphs, Structure())

    async def report(phase):
        phases.append(phase)

    asyncio.run(service.extract(request(repository, commit), report))
    assert phases == ["preparing", "extracting", "saving"]
    assert service.artifact(2, commit, 1).is_file()
    assert (graphs / "2" / commit / "1" / "manifest.json").is_file()
    assert not list((graphs / "2" / commit).glob(".snapshot-*"))
    assert (repository / "source.py").read_text() == "selected = 2\n"


def test_failed_extraction_does_not_publish_partial_output(tmp_path):
    workspace, repository, commit = checkout(tmp_path)

    class Failing:
        async def extract_structure(self, snapshot, output):
            output.mkdir()
            raise RuntimeError("private source detail")

    service = GraphExtractionService(workspace, tmp_path / "graphs", Failing())

    async def report(phase):
        pass

    with pytest.raises(RuntimeError):
        asyncio.run(service.extract(request(repository, commit), report))
    with pytest.raises(FileNotFoundError):
        service.artifact(2, commit, 1)
    with pytest.raises(ValueError):
        service.repository(str(tmp_path))
    with pytest.raises(ValueError):
        GraphExtractionService(workspace, repository / "graphs")


@pytest.mark.skipif(os.name != "nt", reason="Windows Uvicorn reload event loop")
def test_real_git_and_graphify_work_on_windows_selector_loop(tmp_path):
    workspace, repository, commit = checkout(tmp_path)
    service = GraphExtractionService(workspace, tmp_path / "graphs")
    phases = []

    async def report(phase):
        phases.append(phase)

    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(service.extract(request(repository, commit), report))
    assert phases == ["preparing", "extracting", "saving"]
    assert service.artifact(2, commit, 1).stat().st_size > 0
    assert (repository / "source.py").read_text() == "selected = 2\n"


def test_graph_job_reports_lifecycle_and_bounds_queue(tmp_path):
    _workspace, repository, commit = checkout(tmp_path)
    delivered = []

    class Service:
        repository = staticmethod(lambda path: Path(path))

        async def extract(self, body, report):
            await report("preparing")
            await report("extracting")
            await report("saving")

    class Callbacks:
        async def graph_task(self, task_id, token, phase, error_code=None):
            delivered.append((task_id, phase))
            return SimpleNamespace(acknowledged=True)

    async def run():
        jobs = GraphJobs(Service(), Callbacks(), GraphSettings(graph_max_pending=1))
        body = request(repository, commit)
        jobs.start(body)
        jobs.start(body)  # Idempotent delivery while active.
        with pytest.raises(OverflowError):
            jobs.start(request(repository, commit, 2))
        await asyncio.gather(*(task for _, task in list(jobs.jobs.values())))
        assert not jobs.jobs

    asyncio.run(run())
    assert delivered == [(1, "preparing"), (1, "extracting"), (1, "saving"), (1, "completed")]


def test_snapshot_unpack_rejects_traversal_and_skips_links(tmp_path):
    snapshot = tmp_path / "source"
    snapshot.mkdir()
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as output:
        link = zipfile.ZipInfo("link.py")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        output.writestr(link, "../outside.py")
        output.writestr("normal.py", "value = 1")
    GraphExtractionService._unpack(archive, snapshot)
    assert not (snapshot / "link.py").exists()
    assert (snapshot / "normal.py").is_file()
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../outside.py", "escape = True")
    with pytest.raises(ValueError):
        GraphExtractionService._unpack(archive, snapshot)
    assert not (tmp_path / "outside.py").exists()


def test_publication_retries_transient_locks_without_exposing_partial_output(tmp_path, monkeypatch):
    source = tmp_path / "private"
    source.mkdir()
    final = tmp_path / "published"
    rename = Path.rename
    attempts = []

    def locked_once(path, destination):
        attempts.append(path)
        assert not final.exists()
        if len(attempts) == 1:
            raise PermissionError("temporary file lock")
        return rename(path, destination)

    monkeypatch.setattr(Path, "rename", locked_once)
    asyncio.run(GraphExtractionService._publish(source, final))
    assert len(attempts) == 2
    assert final.is_dir()


@pytest.mark.parametrize(("phase", "error_code", "payload"), [
    ("completed", None, b'{"phase":"completed"}'),
    ("failed", "storage_failed", b'{"phase":"failed","errorCode":"storage_failed"}'),
])
def test_graph_callback_uses_task_route_and_private_capability(phase, error_code, payload):
    async def run():
        async def receive(request):
            assert request.url.path == "/api/tasks/8/graph-callback"
            assert request.headers["X-Graph-Token"] == "private-token"
            assert request.content == payload
            return httpx.Response(200)

        async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as client:
            callbacks = CallbackClient(build_callback_config("http://backend"), client)
            assert (await callbacks.graph_task(8, "private-token", phase, error_code)).acknowledged

    asyncio.run(run())


def test_graph_jobs_report_failure_and_cancel_without_exposing_exception(tmp_path, caplog):
    delivered = []

    class Service:
        repository = staticmethod(lambda path: Path(path))

        async def extract(self, body, report):
            await report("preparing")
            if body.task_id == 1:
                raise RuntimeError("private repository detail")
            await asyncio.Event().wait()

    class Callbacks:
        async def graph_task(self, task_id, token, phase, error_code=None):
            delivered.append((task_id, phase, error_code))
            return SimpleNamespace(acknowledged=True)

    async def run():
        jobs = GraphJobs(Service(), Callbacks())
        jobs.start(request(tmp_path, "a" * 40))
        await asyncio.gather(*(task for _, task in list(jobs.jobs.values())))
        assert delivered[-1] == (1, "failed", "extraction_failed")
        jobs.start(request(tmp_path, "b" * 40, 2))
        await asyncio.sleep(0)
        with pytest.raises(PermissionError):
            await jobs.cancel(2, "wrong-token")
        await jobs.cancel(2, "a" * 64)
        assert delivered[-1] == (2, "failed", "interrupted")
        assert not jobs.jobs

    asyncio.run(run())
    assert "exception_type=RuntimeError" in caplog.text
    assert "phase=preparing" in caplog.text
    assert "private repository detail" not in caplog.text


@pytest.mark.parametrize(("failure", "expected"), [
    (GraphExtractionError("commit_unavailable"), "commit_unavailable"),
    (GraphifyError("timeout"), "timeout"),
    (GraphifyError("unavailable"), "extractor_unavailable"),
    (OSError("private storage path"), "storage_failed"),
])
def test_graph_failure_callbacks_preserve_safe_categories(tmp_path, failure, expected):
    delivered = []

    class Service:
        repository = staticmethod(lambda path: Path(path))

        async def extract(self, body, report):
            raise failure

    class Callbacks:
        async def graph_task(self, task_id, token, phase, error_code=None):
            delivered.append((phase, error_code))
            return SimpleNamespace(acknowledged=True)

    async def run():
        jobs = GraphJobs(Service(), Callbacks())
        jobs.start(request(tmp_path, "a" * 40))
        await asyncio.gather(*(task for _, task in list(jobs.jobs.values())))

    asyncio.run(run())
    assert delivered == [("failed", expected)]


def test_graph_http_accepts_without_waiting_and_rejects_invalid_commit(tmp_path):
    accepted = []
    app = FastAPI()
    app.include_router(router)
    app.state.graph_jobs = SimpleNamespace(start=accepted.append)
    body = request(tmp_path, "a" * 40).model_dump()
    with TestClient(app) as client:
        response = client.post("/api/graphs", json=body)
        assert response.status_code == 202
        assert len(accepted) == 1
        body["commit_hash"] = "../HEAD"
        assert client.post("/api/graphs", json=body).status_code == 422
