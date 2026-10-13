import asyncio
import json

import pytest

from server.run_project_analysis import ProgressReporter, main, with_progress


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
    import server.run_project_analysis as runner

    clock = [100.0]
    monkeypatch.setattr(runner, "monotonic", lambda: clock[0])

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


def test_verbose_progress_keeps_json_stdout_clean_and_quiet_suppresses_it(
    workspace, capsys
):
    parent, root = workspace
    args = [
        str(root),
        "--workspace-root",
        str(parent),
        "--smoke",
        "--max-investigations",
        "1",
        "--json",
    ]
    assert main(args) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["completion_status"] == "partial"
    for event in (
        "snapshot_started",
        "snapshot_ready",
        "tools_ready",
        "model_ready",
        "model_call_started",
        "provider_request",
        "model_call_finished",
        "tool_started",
        "tool_finished",
        "finding_accepted",
        "cleanup_finished",
    ):
        assert f"[{event}]" in captured.err
    assert main([*args, "--quiet"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["completion_status"] == "partial"
    assert captured.err == ""
    assert main([*args, "--progress-interval", "0"]) == 2


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workspace" / "selected"
    root.mkdir(parents=True)
    (root / "main.py").write_text("def main():\n    return 42\n", encoding="utf-8")
    return root.parent, root


def test_runner_smoke_json_handoff_and_plan_only(workspace, capsys):
    parent, root = workspace
    args = [
        str(root),
        "--workspace-root",
        str(parent),
        "--smoke",
        "--max-investigations",
        "1",
        "--quiet",
    ]
    assert main([*args, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert (
        data["completion_status"] == "partial"
        and data["execution_mode"] == "protocol_smoke"
    )
    assert data["usage"]["provider_attempts"] > 0
    assert main([*args, "--handoff"]) == 0
    handoff = json.loads(capsys.readouterr().out)
    assert (
        handoff["snapshot_hash"] == handoff["project_analysis_report"]["snapshot_hash"]
    )
    assert main([*args, "--plan-only", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["planning_status"] == "ready"


def test_runner_scope_budget_errors_and_readable_summary(workspace, capsys):
    parent, root = workspace
    args = [
        str(root),
        "--workspace-root",
        str(parent),
        "--smoke",
        "--max-investigations",
        "1",
        "--quiet",
    ]
    assert main(args) == 0
    assert "Status: partial" in capsys.readouterr().out
    assert main([str(parent), "--workspace-root", str(parent), "--smoke"]) == 2
    assert "directly inside" in capsys.readouterr().err
    assert main([*args, "--max-model-calls", "2"]) == 2
    assert "Report reserve" in capsys.readouterr().err
    assert main([*args, "--plan-only", "--handoff"]) == 2


def test_workspace_evaluation_proxies_reviews_and_repeat_stability(
    workspace, capsys, tmp_path
):
    import yaml

    parent, root = workspace
    suite = tmp_path / "suite.yaml"
    suite.write_text(
        yaml.safe_dump(
            {
                "cases": [
                    {
                        "id": "selected",
                        "repository": root.name,
                        "key_components": ["main.py"],
                        "expected_facts": [
                            {
                                "id": "return",
                                "description": "main returns 42",
                                "evidence": ["main.py:1-2"],
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    args = [
        "--evaluate-workspace",
        "--suite",
        str(suite),
        "--workspace-root",
        str(parent),
        "--smoke",
        "--max-investigations",
        "1",
        "--quiet",
        "--json",
    ]
    assert main(args) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["repeat_stability"]["selected"] is None
    record = data["runs"][0]
    assert record["metrics"]["reference_location_coverage"] == 1.0
    assert record["metrics"]["reference_component_coverage"] == 0.0
    assert record["semantic_review"]["status"] == "not_applicable_protocol_smoke"
    assert record["estimated_cost_usd"] is None
    assert main([*args, "--repeat", "2"]) == 0
    assert (
        json.loads(capsys.readouterr().out)["summary"]["repeat_stability"]["selected"]
        is True
    )
    assert main([*args, "--case", "unknown"]) == 2
