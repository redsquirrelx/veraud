import asyncio
import subprocess
import sys
import threading
from unittest.mock import AsyncMock

import pytest

from server.infrastructure.process import create_process


def test_unsupported_subprocess_transport_runs_without_blocking_loop(monkeypatch):
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(side_effect=NotImplementedError))

    async def run():
        process = await create_process(
            sys.executable, "-I", "-c", "import time; time.sleep(0.2)",
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        waiter = asyncio.create_task(process.wait())
        await asyncio.sleep(0)
        assert not waiter.done()
        assert await waiter == 0
        assert process.returncode == 0

    asyncio.run(run())


def test_cancel_during_fallback_spawn_reaps_owned_process(monkeypatch):
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(side_effect=NotImplementedError))
    original = subprocess.Popen
    started = threading.Event()
    released = threading.Event()
    processes = []

    def spawn(arguments, **options):
        process = original(arguments, **options)
        if arguments[0] == sys.executable:
            processes.append(process)
            started.set()
            released.wait(timeout=5)
        return process

    monkeypatch.setattr(subprocess, "Popen", spawn)

    async def run():
        task = asyncio.create_task(create_process(
            sys.executable, "-I", "-c", "import time; time.sleep(60)",
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ))
        try:
            assert await asyncio.to_thread(started.wait, 5)
            task.cancel()
            released.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert processes[0].poll() is not None
        finally:
            released.set()
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.wait()

    asyncio.run(run())
