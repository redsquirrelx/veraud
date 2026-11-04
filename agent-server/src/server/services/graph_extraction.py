"""Immutable Git snapshots and atomically published Graphify artifacts."""

from __future__ import annotations

import asyncio
import json
import shutil
import stat
import subprocess
import tempfile
import zipfile
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from server.infrastructure.process import create_process
from server.services.repository_structure import RepositoryStructureService


class GraphExtractionError(ValueError):
    """Public failure category without filesystem or parser details."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class GraphExtractionService:
    def __init__(self, workspace: Path, graphs_root: Path, structure=None):
        self.workspace = workspace.resolve()
        self.graphs_root = graphs_root.resolve()
        if self.graphs_root.is_relative_to(self.workspace):
            raise ValueError("Graph artifacts must be outside the source workspace")
        self.structure = structure or RepositoryStructureService()

    def repository(self, path: str) -> Path:
        try:
            repository = Path(path).resolve(strict=True)
        except OSError:
            raise GraphExtractionError("repository_unavailable") from None
        if repository.parent != self.workspace or not (repository / ".git").exists():
            raise GraphExtractionError("repository_unavailable")
        return repository

    def artifact(self, project_id: int, commit: str, task_id: int) -> Path:
        directory = self.graphs_root / str(project_id) / commit / str(task_id)
        artifact = (directory / "graphify-out" / "graph.json").resolve()
        if not artifact.is_relative_to(self.graphs_root) or not (directory / "manifest.json").is_file():
            raise FileNotFoundError("Graph is not available")
        if not artifact.is_file():
            raise FileNotFoundError("Graph is not available")
        return artifact

    async def extract(self, request, report):
        repository = self.repository(request.repository_path)
        parent = self.graphs_root / str(request.project_id) / request.commit_hash
        parent.mkdir(parents=True, exist_ok=True)
        final = parent / str(request.task_id)
        if final.exists():
            raise ValueError("Graph output already exists")
        # Both directories are private to this extraction, never the mutable checkout.
        with tempfile.TemporaryDirectory(prefix=".snapshot-", dir=parent) as temporary:
            temporary = Path(temporary)
            snapshot = temporary / "source"
            snapshot.mkdir()
            archive = temporary / "source.zip"
            output = temporary / "output"
            await report("preparing")
            process = await create_process(
                "git", "-C", str(repository), "archive", "--format=zip",
                f"--output={archive}", request.commit_hash,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(process.wait(), timeout=60)
            except (TimeoutError, asyncio.CancelledError):
                if process.returncode is None:
                    process.kill()
                await process.wait()
                raise
            if process.returncode:
                raise GraphExtractionError("commit_unavailable")
            # No links or paths escaping the snapshot may reach the parser.
            unpack = asyncio.create_task(asyncio.to_thread(self._unpack, archive, snapshot))
            try:
                await asyncio.shield(unpack)
            except (ValueError, zipfile.BadZipFile):
                raise GraphExtractionError("snapshot_failed") from None
            except asyncio.CancelledError:
                # Let the worker release file handles before removing its private directory.
                await unpack
                raise
            await report("extracting")
            await self.structure.extract_structure(snapshot, output)
            await report("saving")
            manifest = {
                "project_id": request.project_id, "task_id": request.task_id,
                "branch": request.branch, "commit_hash": request.commit_hash,
                "graphify_version": version("graphifyy"), "created_at": datetime.now(UTC).isoformat(),
            }
            (output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            # Same filesystem rename: readers cannot observe a partially published graph.
            await self._publish(output, final)
        return final

    @staticmethod
    async def _publish(output: Path, final: Path):
        # Windows scanners can briefly hold a newly written directory open.
        # Retry only the atomic rename; never copy partial output into place.
        for attempt in range(4):
            try:
                output.rename(final)
                return
            except PermissionError:
                if attempt == 3:
                    raise
                await asyncio.sleep(0.05 * (attempt + 1))

    @staticmethod
    def _unpack(archive: Path, snapshot: Path):
        with zipfile.ZipFile(archive) as source:
            for entry in source.infolist():
                target = (snapshot / entry.filename).resolve()
                if not target.is_relative_to(snapshot) or "\\" in entry.filename or ":" in entry.filename:
                    raise ValueError("Invalid snapshot path")
                if stat.S_ISLNK(entry.external_attr >> 16):
                    continue
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source.open(entry) as content, target.open("wb") as destination:
                        shutil.copyfileobj(content, destination)
