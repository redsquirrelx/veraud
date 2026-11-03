"""Subprocesses with discarded/file-backed output, including Windows reload loops.

Uvicorn reload workers may use SelectorEventLoop on Windows, which does not
implement asyncio subprocess transports. Fall back without blocking the loop
or losing ownership of a process spawned during cancellation.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
from pathlib import Path


class _PollingProcess:
    def __init__(self, process: subprocess.Popen):
        self._process = process

    @property
    def pid(self):
        return self._process.pid

    @property
    def returncode(self):
        return self._process.poll()

    async def wait(self):
        while (code := self._process.poll()) is None:
            await asyncio.sleep(0.05)
        return code

    def kill(self):
        self._process.kill()


def _reap_cancelled_spawn(process: subprocess.Popen, new_session: bool):
    if process.poll() is None:
        if os.name == "nt":
            try:
                subprocess.run(
                    [str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"),
                     "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=5, check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        elif new_session:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
    process.wait()


async def create_process(*arguments, **options):
    """Use native asyncio when supported; no shell or captured PIPE streams."""
    try:
        return await asyncio.create_subprocess_exec(*arguments, **options)
    except NotImplementedError:
        pass
    spawned = asyncio.create_task(asyncio.to_thread(subprocess.Popen, arguments, **options))
    try:
        process = await asyncio.shield(spawned)
    except asyncio.CancelledError:
        # to_thread cannot stop process creation. Wait for ownership, then reap it.
        process = await spawned
        await asyncio.to_thread(_reap_cancelled_spawn, process, options.get("start_new_session", False))
        raise
    return _PollingProcess(process)
