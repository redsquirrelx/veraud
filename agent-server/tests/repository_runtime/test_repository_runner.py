"""Repository runner lifecycle, JSON/progress separation, and wait cancellation."""

import asyncio
import json

import pytest

from server.repository_progress import ProgressReporter, with_progress
from server.run_project_architecture import main as architecture_main
from server.run_project_orientation import main as orientation_main


def test_wait_progress_heartbeat_and_cancellation_cleanup(capsys):
    async def scenario():
        reporter = ProgressReporter(0.01)
        reporter("provider_request", {"attempt": 1})
        assert (
            await with_progress(asyncio.sleep(0.035, result="done"), reporter) == "done"
        )
        output = capsys.readouterr().err
        assert "still_running" in output and "provider_request" in output
        assert "activity_seconds" in output and "elapsed_seconds" in output
        await asyncio.sleep(0.025)
        assert capsys.readouterr().err == ""
        task = asyncio.create_task(with_progress(asyncio.sleep(3600), reporter))
        await asyncio.sleep(0.025)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        capsys.readouterr()
        await asyncio.sleep(0.025)
        assert capsys.readouterr().err == ""

    asyncio.run(scenario())


def test_provider_wait_heartbeat_shows_reason_and_countdown(capsys, monkeypatch):
    import server.repository_progress as progress

    clock = [100.0]
    monkeypatch.setattr(progress, "monotonic", lambda: clock[0])

    async def scenario():
        reporter = ProgressReporter(0.01)
        reporter(
            "provider_wait",
            {
                "wait_seconds": 90,
                "reason": "provider_retry_after",
                "call": 2,
                "attempt": 2,
                "http_status": 429,
            },
        )
        clock[0] += 30
        await with_progress(asyncio.sleep(0.025), reporter)
        output = capsys.readouterr().err
        assert "wait_remaining_seconds=60.0" in output
        assert "wait_total_seconds=90" in output
        assert 'reason="provider_retry_after"' in output
        assert "http_status=429" in output
        assert 'next_action="send_provider_request"' in output
        reporter("provider_request", {"call": 2, "attempt": 2})
        await with_progress(asyncio.sleep(0.025), reporter)
        assert "wait_remaining_seconds" not in capsys.readouterr().err

    asyncio.run(scenario())


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "workspace" / "selected"
    root.mkdir(parents=True)
    (root / "main.py").write_text("def main():\n    return 42\n", encoding="utf-8")
    (root / "service.py").write_text(
        "def serve():\n    return 'service'\n", encoding="utf-8"
    )
    return root


@pytest.mark.parametrize("main", [orientation_main, architecture_main])
def test_verbose_progress_keeps_json_clean_and_quiet_suppresses_it(
    checkout, capsys, main
):
    args = [
        str(checkout),
        "--workspace-root",
        str(checkout.parent),
        "--smoke",
        "--json",
    ]
    assert main(args) == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["completion_status"] == "partial"
    assert data["run_metadata"]["snapshot_hash"] == data["snapshot_hash"]
    assert len(data["run_metadata"]["implementation_sha256"]) == 64
    assert "api_key" not in json.dumps(data["run_metadata"])
    for event in (
        "snapshot_started",
        "snapshot_ready",
        "tools_ready",
        "model_ready",
        "provider_request",
        "tool_started",
        "tool_finished",
        "cleanup_finished",
    ):
        assert f"[{event}]" in captured.err
    assert main([*args, "--quiet"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["completion_status"] == "partial"
    assert captured.err == ""
    assert main([*args, "--progress-interval", "0"]) == 2


@pytest.mark.parametrize("main", [orientation_main, architecture_main])
def test_runner_scope_budget_errors_and_readable_summary(checkout, capsys, main):
    args = [
        str(checkout),
        "--workspace-root",
        str(checkout.parent),
        "--smoke",
        "--quiet",
    ]
    assert main(args) == 0
    assert "Status: partial" in capsys.readouterr().out
    assert (
        main(
            [str(checkout.parent), "--workspace-root", str(checkout.parent), "--smoke"]
        )
        == 2
    )
    assert "directly inside" in capsys.readouterr().err
    assert main([*args, "--max-model-calls", "0"]) == 2
