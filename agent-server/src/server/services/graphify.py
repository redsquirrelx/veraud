"""Local, code-only Graphify adapter; never runs repository code or an LLM."""

from __future__ import annotations

import asyncio
import math
import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Literal


class GraphifyError(RuntimeError):
    """Safe failure details, without CLI output, source paths or credentials."""

    def __init__(
        self,
        code: Literal["invalid_path", "unavailable", "timeout", "execution_failed", "missing_output"],
        *,
        returncode: int | None = None,
    ) -> None:
        self.code = code
        self.returncode = returncode
        super().__init__(f"Graphify failed: {code}.")


@dataclass(frozen=True)
class GraphifyResult:
    graph_file: Path
    elapsed_seconds: float


class GraphifyAdapter:
    """Invoke the pinned package in this interpreter, not a CLI found on PATH.

    Each call requires a new output directory outside the repository snapshot.
    Artifacts (including partial output on failure) belong to the caller.
    """

    def __init__(self, *, timeout_seconds: float = 120, max_workers: int = 1) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive.")
        if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers < 1:
            raise ValueError("max_workers must be a positive integer.")
        self.timeout_seconds = timeout_seconds
        self.max_workers = max_workers

    async def extract(self, repository_path: Path, output_directory: Path) -> GraphifyResult:
        """Build a local graph without reading its contents or changing the snapshot."""
        try:
            repository = Path(repository_path).resolve(strict=True)
            output = Path(output_directory).resolve()
            if (
                not repository.is_dir()
                or output.is_relative_to(repository)
                or repository.is_relative_to(output)
            ):
                raise GraphifyError("invalid_path")
            output.mkdir(parents=True, exist_ok=False)
        except OSError:
            raise GraphifyError("invalid_path") from None

        # Do not inherit Graphify overrides, provider credentials, or Python import
        # injection. System variables are retained for Windows and grammar workers.
        env = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL"}
        }
        env.update(
            GRAPHIFY_BACKEND="none",
            GRAPHIFY_NO_AUTO_REFRESH="1",
            GRAPHIFY_QUERY_LOG_DISABLE="1",
            GRAPHIFY_OUT="graphify-out",
            PYTHONHASHSEED="0",
            PYTHONIOENCODING="utf-8",
            HOME=str(output),
            USERPROFILE=str(output),
            XDG_CACHE_HOME=str(output / ".cache"),
        )
        process_options = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
            if os.name == "nt"
            else {"start_new_session": True}
        )
        started = monotonic()
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                "-m",
                "graphify",
                "extract",
                str(repository),
                "--code-only",
                "--max-workers",
                str(self.max_workers),
                "--out",
                str(output),
                cwd=output,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **process_options,
            )
        except OSError:
            raise GraphifyError("unavailable") from None

        try:
            await asyncio.wait_for(process.wait(), timeout=self.timeout_seconds)
        except (TimeoutError, asyncio.CancelledError) as error:
            await self._stop(process)
            if isinstance(error, asyncio.CancelledError):
                raise
            raise GraphifyError("timeout") from None
        if process.returncode != 0:
            raise GraphifyError("execution_failed", returncode=process.returncode)

        graph_file = output / "graphify-out" / "graph.json"
        try:
            has_output = graph_file.is_file() and graph_file.stat().st_size > 0
        except OSError:
            has_output = False
        if not has_output:
            raise GraphifyError("missing_output")
        return GraphifyResult(graph_file=graph_file, elapsed_seconds=monotonic() - started)

    @staticmethod
    async def _stop(process: asyncio.subprocess.Process) -> None:
        """Stop the extraction tree, including AST worker processes."""
        if process.returncode is None:
            if os.name == "nt":
                system_root = os.environ.get("SystemRoot", r"C:\Windows")
                try:
                    killer = await asyncio.create_subprocess_exec(
                        str(Path(system_root) / "System32" / "taskkill.exe"),
                        "/PID", str(process.pid), "/T", "/F",
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    await killer.wait()
                except OSError:
                    pass
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
        await process.wait()
