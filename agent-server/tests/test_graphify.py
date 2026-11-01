import asyncio
import os
import subprocess
import sys
from unittest.mock import AsyncMock

import pytest

from server.services.graphify import GraphifyAdapter, GraphifyError


def test_extract_real_code_without_modifying_repository(tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    source = repository / "example.py"
    content = b"def greet(name):\n    return name.upper()\n"
    source.write_bytes(content)

    result = asyncio.run(GraphifyAdapter().extract(repository, tmp_path / "artifacts"))

    assert result.graph_file.is_file()
    assert result.graph_file.stat().st_size > 0
    assert result.elapsed_seconds > 0
    assert list(repository.iterdir()) == [source]
    assert source.read_bytes() == content


def test_command_is_local_isolated_and_does_not_inherit_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("GRAPHIFY_BACKEND", "openai")
    monkeypatch.setenv("GRAPHIFY_OUT", "unexpected")
    monkeypatch.setenv("PYTHONPATH", "untrusted")
    repository = tmp_path / "repository with spaces"
    repository.mkdir()
    output = tmp_path / "artifacts"
    process = AsyncMock(returncode=0)

    async def spawn(*args, **kwargs):
        assert args[1:5] == ("-I", "-m", "graphify", "extract")
        assert str(repository) in args
        assert "--code-only" in args
        assert kwargs["cwd"] == output
        env = kwargs["env"]
        assert env["GRAPHIFY_BACKEND"] == "none"
        assert env["GRAPHIFY_OUT"] == "graphify-out"
        assert env["GRAPHIFY_NO_AUTO_REFRESH"] == "1"
        assert env["GRAPHIFY_QUERY_LOG_DISABLE"] == "1"
        assert "OPENAI_API_KEY" not in env
        assert "PYTHONPATH" not in env
        graph = output / "graphify-out" / "graph.json"
        graph.parent.mkdir()
        graph.write_text("{}", encoding="utf-8")
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    asyncio.run(GraphifyAdapter().extract(repository, output))


@pytest.mark.parametrize("case", ["missing", "file", "inside", "existing"])
def test_reject_invalid_paths_before_spawning(tmp_path, monkeypatch, case):
    repository = tmp_path / "repository"
    repository.mkdir()
    output = tmp_path / "artifacts"
    if case == "missing":
        repository = tmp_path / "missing"
    elif case == "file":
        repository = tmp_path / "file.py"
        repository.touch()
    elif case == "inside":
        output = repository / "artifacts"
    else:
        output.mkdir()
    spawn = AsyncMock()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(GraphifyError) as error:
        asyncio.run(GraphifyAdapter().extract(repository, output))
    assert error.value.code == "invalid_path"
    spawn.assert_not_called()


@pytest.mark.parametrize("returncode,code", [(1, "execution_failed"), (0, "missing_output")])
def test_failed_or_missing_output_is_not_success(tmp_path, monkeypatch, returncode, code):
    repository = tmp_path / "repository"
    repository.mkdir()
    process = AsyncMock(returncode=returncode)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    with pytest.raises(GraphifyError) as error:
        asyncio.run(GraphifyAdapter().extract(repository, tmp_path / "output"))
    assert error.value.code == code


def test_spawn_error_is_sanitized(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setattr(
        asyncio, "create_subprocess_exec", AsyncMock(side_effect=OSError("secret detail"))
    )
    with pytest.raises(GraphifyError) as error:
        asyncio.run(GraphifyAdapter().extract(repository, tmp_path / "output"))
    assert error.value.code == "unavailable"
    assert "secret" not in str(error.value)
    assert error.value.__suppress_context__


@pytest.mark.parametrize("cancel", [False, True])
def test_timeout_and_cancellation_stop_process(tmp_path, monkeypatch, cancel):
    repository = tmp_path / "repository"
    repository.mkdir()
    process = AsyncMock(returncode=None)

    async def wait():
        if cancel:
            raise asyncio.CancelledError()
        await asyncio.Event().wait()

    process.wait.side_effect = wait
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    stop = AsyncMock()
    monkeypatch.setattr(GraphifyAdapter, "_stop", stop)
    with pytest.raises(asyncio.CancelledError if cancel else GraphifyError) as error:
        asyncio.run(GraphifyAdapter(timeout_seconds=0.01).extract(repository, tmp_path / "output"))
    if not cancel:
        assert error.value.code == "timeout"
    stop.assert_awaited_once_with(process)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_timeout_is_rejected(timeout):
    with pytest.raises(ValueError):
        GraphifyAdapter(timeout_seconds=timeout)


@pytest.mark.parametrize("workers", [0, -1, True, 1.5])
def test_invalid_worker_count_is_rejected(workers):
    with pytest.raises(ValueError):
        GraphifyAdapter(max_workers=workers)


def test_stop_reaps_real_process():
    async def run():
        options = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
            if os.name == "nt"
            else {"start_new_session": True}
        )
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-c", "import time; time.sleep(60)", **options
        )
        try:
            await asyncio.wait_for(GraphifyAdapter._stop(process), timeout=10)
            assert process.returncode is not None
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()

    asyncio.run(run())
