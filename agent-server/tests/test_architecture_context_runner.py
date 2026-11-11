"""The discovery runner prepares an index and executes the actual LangGraph node."""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import get_args
from unittest.mock import AsyncMock, Mock

import pytest

from server import run_architecture_context as runner
from server.agents.architecture_context.schemas import (
    ArchitectureContextResult,
    RetrievalCategory,
)
from server.run_architecture_context import create_planning_model


@pytest.fixture(autouse=True)
def planning_provider(monkeypatch):
    async def respond(messages, **kwargs):
        prompt = messages[0].content
        payload = {"tasks": []}
        if "Accumulated knowledge" in prompt:
            payload = {"categories": [
                {"category": category, "sufficient": False, "rationale": "No retrieved evidence"}
                for category in get_args(RetrievalCategory)
            ]}
        elif "Retrieved sections:" in prompt:
            source = json.loads(prompt.split("Retrieved sections:\n", 1)[1])
            payload = {"sections": [
                {"section_id": item["section_id"], "claims": [], "issues": []}
                for item in source
            ]}
        return SimpleNamespace(
            content=json.dumps(payload),
            usage_metadata={"input_tokens": 100, "output_tokens": 10},
        )

    provider = SimpleNamespace(
        ainvoke=AsyncMock(side_effect=respond)
    )
    factory = Mock(return_value=(provider, SimpleNamespace(max_tokens=4000)))
    monkeypatch.setattr(runner, "create_planning_model", factory)
    return factory, provider


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repository with spaces"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True)
    return root


def commit(root):
    subprocess.run(
        ["git", "-C", str(root), "add", "."], check=True, capture_output=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )


def test_usage_rollup_separates_retry_attempts_reported_and_estimated_tokens():
    usage = runner._aggregate_model_usage(
        [
            {
                "call": 2,
                "node": "plan_retrieval",
                "round": 1,
                "phase": "planning",
                "status": "completed",
                "provider_attempts": 2,
                "provider_retries": 1,
                "input_tokens": 90,
                "output_tokens": 20,
                "reported_total_tokens": 110,
                "unknown_usage_attempts": 1,
                "accounted_tokens": 510,
                "estimated_tokens": 400,
            }
        ]
    )
    total = usage["total"]
    assert total["model_calls"] == 1
    assert total["provider_attempts"] == 2
    assert total["provider_retries"] == 1
    assert total["reported_total_tokens"] == 110
    assert total["accounted_tokens"] == 510
    assert total["estimated_tokens"] == 400
    assert total["unknown_usage_attempts"] == 1
    assert total["reported_usage_complete"] is False
    assert usage["by_phase"]["planning"]["provider_attempts"] == 2


@pytest.mark.parametrize("empty", [False, True])
@pytest.mark.parametrize("output_option", ["--output", "--output-file"])
def test_runner_exports_metadata_state_without_reading_json(
    repository, tmp_path, monkeypatch, capsys, empty, output_option
):
    if not empty:
        for name in ("z.md", "a.md"):
            (repository / name).write_text(
                "# Architecture\nSource text", encoding="utf-8"
            )
    commit(repository)
    calls = []
    reports = []
    original_node = runner.discover_documents
    original_dump = runner.json.dump

    def observe_node(state, *, indexing_service):
        calls.append(state["document_index"])
        return original_node(state, indexing_service=indexing_service)

    def observe_report(report, stream, **kwargs):
        reports.append(report)
        return original_dump(report, stream, **kwargs)

    monkeypatch.setattr(runner, "discover_documents", observe_node)
    monkeypatch.setattr(runner.json, "dump", observe_report)
    arguments = [
        str(repository),
        "--diagnostics",
        "--database",
        str(tmp_path / "docs.sqlite"),
        "--limit",
        "1",
    ]
    output = tmp_path / "report" / "discovery.json"
    assert runner.main([*arguments, output_option, str(output)]) == 0
    assert len(calls) == 1 and output.is_file()
    state = reports[0]["state"]
    assert state["document_discovery_status"] == "ready"
    assert state["document_discovery_error"] is None
    assert [doc["path"] for doc in state["documents"]] == (
        [] if empty else ["a.md", "z.md"]
    )
    assert all("content" not in doc for doc in state["documents"])
    assert state["document_index"]["commit"] == reports[0]["indexing"]["commit"]
    text = capsys.readouterr().out
    assert "Discovery status: ready" in text
    if not empty:
        assert "a.md (2 lines" in text and "z.md (2 lines" not in text
    assert runner.main(arguments) == 0
    assert "processed 0; reused" in capsys.readouterr().out


def test_node_error_returns_failure(repository, tmp_path, monkeypatch, capsys):
    commit(repository)
    monkeypatch.setattr(
        runner,
        "discover_documents",
        lambda state, **kwargs: {
            "documents": [],
            "document_discovery_status": "error",
            "document_discovery_error": "index inaccessible",
            "retrieval_context": "catalog unavailable",
        },
    )
    assert (
        runner.main([str(repository), "--database", str(tmp_path / "docs.sqlite")]) == 1
    )
    assert "index inaccessible" in capsys.readouterr().err


def test_output_and_database_validation_precedes_writes(repository, tmp_path, capsys):
    existing = tmp_path / "user-work.txt"
    existing.write_text("preserve", encoding="utf-8")
    assert (
        runner.main(
            [
                str(repository),
                "--database",
                str(tmp_path / "docs.sqlite"),
                "--output",
                str(existing),
            ]
        )
        == 1
    )
    assert existing.read_text(encoding="utf-8") == "preserve"
    assert "Output must be a new file" in capsys.readouterr().err
    assert not (tmp_path / "docs.sqlite").exists()
    assert (
        runner.main([str(repository), "--database", str(repository / "index.sqlite")])
        == 1
    )
    assert not (repository / "index.sqlite").exists()


def test_direct_script_execution(repository, tmp_path):
    commit(repository)
    script = (
        Path(__file__).resolve().parents[1] / "src/server/run_architecture_context.py"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            str(repository),
            "--database",
            str(tmp_path / "docs.sqlite"),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert (
        "Discovery status: ready" in result.stdout
        and "Documents discovered: 0" in result.stdout
    )


def test_stdout_prints_full_report_without_json_file(
    repository, tmp_path, monkeypatch, capsys
):
    for name in ("a.md", "z.md"):
        (repository / name).write_text("# Architecture", encoding="utf-8")
    commit(repository)
    reports = []
    original_dump = runner.json.dump

    def observe_report(report, stream, **kwargs):
        reports.append(report)
        return original_dump(report, stream, **kwargs)

    monkeypatch.setattr(runner.json, "dump", observe_report)
    assert (
        runner.main(
            [
                str(repository),
                "--database",
                str(tmp_path / "docs.sqlite"),
                "--stdout",
                "--diagnostics",
                "--limit",
                "1",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert captured.out.startswith("{\n") and captured.out.endswith("}\n")
    assert "Repository:" not in captured.out
    assert "Discovery status: ready" in captured.err
    assert [doc["path"] for doc in reports[0]["state"]["documents"]] == ["a.md", "z.md"]
    assert not list(tmp_path.rglob("*.json"))


def test_stdout_and_output_are_mutually_exclusive(repository, tmp_path):
    with pytest.raises(SystemExit) as error:
        runner.main(
            [str(repository), "--stdout", "--output", str(tmp_path / "report.json")]
        )
    assert error.value.code == 2
    assert not (tmp_path / "report.json").exists()


def test_runner_executes_planner_and_exports_plan(
    repository, tmp_path, planning_provider, monkeypatch, capsys
):
    (repository / "README.md").write_text("# Architecture\ngateway", encoding="utf-8")
    commit(repository)
    factory, provider = planning_provider

    def respond(messages, **kwargs):
        prompt = messages[0].content
        if "Retrieval context:\n" in prompt:
            content = '{"tasks": [{"category": "components", "operation": "read", "path": "README.md"}]}'
        elif "Retrieved sections:\n" in prompt:
            source = json.loads(prompt.split("Retrieved sections:\n", 1)[1])
            content = json.dumps({"sections": [
                {"section_id": item["section_id"], "claims": [], "issues": []}
                for item in source
            ]})
        else:
            content = json.dumps({"categories": [
                {"category": category, "sufficient": False, "rationale": "No claims"}
                for category in get_args(RetrievalCategory)
            ]})
        return SimpleNamespace(
            content=content,
            usage_metadata={"input_tokens": 100, "output_tokens": 20},
            response_metadata={"finish_reason": "STOP"},
        )

    provider.ainvoke.side_effect = respond

    async def native_response(messages, **kwargs):
        return {
            "raw": await provider.ainvoke(messages, **kwargs),
            "parsed": None,
            "parsing_error": None,
        }

    provider.with_structured_output = Mock(
        return_value=SimpleNamespace(ainvoke=AsyncMock(side_effect=native_response))
    )
    reports = []
    original_dump = runner.json.dump
    cleanup = AsyncMock()
    monkeypatch.setattr(runner, "close_model_clients", cleanup)

    def observe_report(report, stream, **kwargs):
        reports.append(report)
        return original_dump(report, stream, **kwargs)

    monkeypatch.setattr(runner.json, "dump", observe_report)
    assert (
        runner.main(
            [str(repository), "--database", str(tmp_path / "docs.sqlite"), "--stdout", "--diagnostics"]
        )
        == 0
    )
    assert factory.call_count == cleanup.await_count == 1
    assert provider.ainvoke.await_count == 2
    assert provider.with_structured_output.call_count == 2
    assert (
        "tasks"
        in provider.with_structured_output.call_args_list[0].args[0]["properties"]
    )
    plan = reports[0]["state"]["retrieval_plan"]
    assert plan["tasks"][0]["path"] == "README.md"
    captured = capsys.readouterr()
    assert "Retrieval plan:" in captured.err
    events = [
        json.loads(line.removeprefix("[architecture_context] "))
        for line in captured.err.splitlines()
        if line.startswith("[architecture_context] ")
    ]
    assert [event["node"] for event in events if event["event"] == "node_started"] == [
        "discover_documents",
        "plan_retrieval",
        "retrieve_documents",
        "extract_knowledge",
        "validate_and_finalize",
    ]
    assert all(
        event["seconds"] >= 0 for event in events if event["event"] == "node_finished"
    )
    assert (
        next(event for event in events if event["event"] == "retrieval_task_started")[
            "task"
        ]["path"]
        == "README.md"
    )
    assert (
        next(event for event in events if event["event"] == "retrieval_task_finished")[
            "newly_retained"
        ]
        == 1
    )
    completed = [event for event in events if event["event"] == "model_call_finished"]
    assert len(completed) == 2 and all(
        event["finish_reason"] == "STOP" for event in completed
    )
    assert all(event["input_tokens"] == 100 for event in completed)
    assert any(
        event["event"] == "route" and event["reason"] == "retrieval_completed"
        and event["destination"] == "extract_knowledge"
        for event in events
    )
    assert (
        "gateway is documented" not in captured.err
        and "README names gateway" not in captured.err
    )
    assert captured.out.startswith(
        "{\n"
    )  # Operational traces never contaminate stdout.
    assert reports[0]["state"]["retrieval_history"][0]["status"] == "ok"
    assert reports[0]["state"]["retrieved_sections"][0]["path"] == "README.md"
    assert reports[0]["state"]["retrieved_sections"][0]["content"] == "# Architecture\ngateway"
    assert reports[0]["state"]["knowledge"] == []
    assert reports[0]["state"]["processed_section_ids"]
    assert "extraction_status" not in reports[0]["state"]
    assert reports[0]["state"]["retrieval_round"] == 1
    assert set(reports[0]["model_usage"]["by_phase"]) == {
        "planning", "initial_extraction", "coverage_assessment"
    }


def test_runner_stops_on_empty_followup_plan_without_reextracting(
    repository, tmp_path, planning_provider, capsys
):
    (repository / "README.md").write_text(
        "# Gateway\nGateway routes requests.", encoding="utf-8"
    )
    commit(repository)
    _, provider = planning_provider

    async def respond(messages, **kwargs):
        prompt = messages[0].content
        if "Retrieval context:\n" in prompt:
            context = json.loads(prompt.split("Retrieval context:\n", 1)[1])
            payload = {"tasks": [] if context["executed_tasks"] else [{
                "category": "components", "operation": "read", "path": "README.md"
            }]}
        elif "Retrieved sections:\n" in prompt:
            source = json.loads(prompt.split("Retrieved sections:\n", 1)[1])
            item = source[0]
            payload = {"sections": [{
                "section_id": item["section_id"],
                "claims": [{
                    "category": "components", "subject": "Gateway",
                    "statement": "Routes requests", "related_subjects": [],
                    "certainty": "explicit", "section_ids": [item["section_id"]],
                    "reasoning": "The document states this responsibility.",
                    "constraint": "unspecified",
                    "evidence": [{
                        "section_id": item["section_id"], "start_line": 2, "end_line": 2
                    }],
                }], "issues": [],
            }]}
        else:
            payload = {"categories": [
                {"category": category, "sufficient": category == "components",
                 "rationale": "Documented component responsibility"}
                for category in get_args(RetrievalCategory)
            ]}
        return SimpleNamespace(
            content=json.dumps(payload),
            usage_metadata={"input_tokens": 100, "output_tokens": 30},
        )

    provider.ainvoke.side_effect = respond
    assert runner.main([
        str(repository), "--database", str(tmp_path / "one-round.sqlite"),
        "--stdout", "--no-trace", "--diagnostics",
    ]) == 0
    output = json.loads(capsys.readouterr().out)
    state = output["state"]
    assert output["model_usage"]["total"]["model_calls"] == 4
    assert state["retrieval_round"] == 2
    assert state["knowledge"][0]["evidence"][0]["quote"] == "Gateway routes requests."
    assert state["extraction_section_status"]
    assert state["coverage_assessment_status"] == "completed"
    assert state["covered_categories"] == ["components"]
    assert state["execution_status"] == "partial"
    assert state["validation_errors"] == []


@pytest.mark.parametrize("diagnostics", [False, True])
def test_runner_continues_for_pending_interfaces_and_accumulates_two_rounds(
    repository, tmp_path, planning_provider, capsys, diagnostics
):
    (repository / "overview.md").write_text("Architecture facts.", encoding="utf-8")
    (repository / "contracts.md").write_text("Documented operation contract.", encoding="utf-8")
    commit(repository)
    _, provider = planning_provider
    stages = []
    categories = get_args(RetrievalCategory)

    async def respond(messages, **kwargs):
        prompt = messages[0].content
        if "Retrieval context:\n" in prompt:
            stages.append("planning")
            context = json.loads(prompt.split("Retrieval context:\n", 1)[1])
            if context["executed_tasks"]:
                assert context["pending_categories"] == ["interfaces_and_contracts"]
                assert ["contracts.md", 1] in context["catalog_path_line_pairs"]
                assert context["executed_tasks"][0]["path"] == "overview.md"
                path, category = "contracts.md", "interfaces_and_contracts"
            else:
                path, category = "overview.md", "components"
            payload = {"tasks": [{"operation": "read", "path": path, "category": category}]}
        elif "Retrieved sections:\n" in prompt:
            stages.append("extraction")
            source = json.loads(prompt.split("Retrieved sections:\n", 1)[1])
            assert len(source) == 1  # Process only newly recovered sections.
            item = source[0]
            selected = (
                ["interfaces_and_contracts"] if item["path"] == "contracts.md"
                else [category for category in categories if category != "interfaces_and_contracts"]
            )
            payload = {"sections": [{
                "section_id": item["section_id"], "issues": [],
                "claims": [{
                    "category": category, "subject": category,
                    "statement": f"Documented {category}", "certainty": "explicit",
                    "reasoning": "Documented", "section_ids": [item["section_id"]],
                    "constraint": "unspecified", "evidence": [{
                        "section_id": item["section_id"], "start_line": 1, "end_line": 1,
                    }],
                } for category in selected],
            }]}
        else:
            stages.append("coverage")
            context = json.loads(prompt.split("Accumulated knowledge:\n", 1)[1])
            present = {claim["category"] for claim in context["claims"]}
            payload = {"categories": [
                {"category": category, "sufficient": category in present,
                 "rationale": "Deterministic coverage fixture"}
                for category in categories
            ]}
        return SimpleNamespace(
            content=json.dumps(payload), usage_metadata={"input_tokens": 100, "output_tokens": 30}
        )

    provider.ainvoke.side_effect = respond
    assert runner.main([
        str(repository), "--database", str(tmp_path / "two-rounds.sqlite"),
        "--stdout", "--no-trace", *(["--diagnostics"] if diagnostics else []),
    ]) == 0
    output = json.loads(capsys.readouterr().out)
    state = output["state"] if diagnostics else output
    assert stages == ["planning", "extraction", "coverage"] * 2
    if diagnostics:
        assert state["retrieval_round"] == 2
        assert len(state["processed_section_ids"]) == 2
        result = ArchitectureContextResult.model_validate(state["result"])
        assert [claim.model_dump(mode="json") for claim in result.knowledge] == state["knowledge"]
    else:
        result = ArchitectureContextResult.model_validate(output)
        assert "state" not in output and "model_usage" not in output
        assert "retrieved_sections" not in output and "retrieval_plan" not in output
    assert len(result.section_paths) == 2
    assert len(state["knowledge"]) == 7
    assert state["pending_categories"] == []
    assert set(state["covered_categories"]) == set(categories)
    assert state["execution_status"] == "complete"
    assert state["validation_errors"] == []
    assert {document["path"] for document in state["consulted_documents"]} == {
        "overview.md", "contracts.md"
    }


@pytest.mark.parametrize("destination", ["--stdout", "--output", "--output-file"])
def test_default_export_is_canonical_final_result(repository, tmp_path, capsys, destination):
    commit(repository)
    path = tmp_path / "result.json"
    arguments = [str(repository), "--database", str(tmp_path / "index.sqlite"), "--discovery-only"]
    arguments += [destination] if destination == "--stdout" else [destination, str(path)]
    assert runner.main(arguments) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out if destination == "--stdout" else path.read_text(encoding="utf-8"))
    result = ArchitectureContextResult.model_validate(payload)
    assert set(payload) == set(ArchitectureContextResult.model_fields)
    assert result.execution_status == "partial"
    assert result.knowledge == []
    assert len(result.pending_categories) == 7


def test_later_planner_failure_finalizes_and_exports_previous_valid_knowledge(
    repository, tmp_path, planning_provider, monkeypatch, capsys
):
    from server.agents.architecture_context.schemas import ReadTask, RetrievalPlan

    (repository / "README.md").write_text("Gateway routes requests.", encoding="utf-8")
    commit(repository)

    async def planner(state, **kwargs):
        if state.get("retrieval_round"):
            raise RuntimeError("private provider response")
        return {"retrieval_plan": RetrievalPlan(tasks=[ReadTask(
            category="components", operation="read", path="README.md",
        )]), "retrieval_round": 1}

    monkeypatch.setattr(runner, "plan_retrieval", planner)

    async def respond(messages, **kwargs):
        prompt = messages[0].content
        if "Retrieved sections:\n" in prompt:
            source = json.loads(prompt.split("Retrieved sections:\n", 1)[1])[0]
            payload = {"sections": [{
                "section_id": source["section_id"], "issues": [], "claims": [{
                    "category": "components", "subject": "Gateway", "statement": "Routes requests",
                    "certainty": "explicit", "reasoning": "Documented", "constraint": "unspecified",
                    "section_ids": [source["section_id"]], "evidence": [{
                        "section_id": source["section_id"], "start_line": 1, "end_line": 1,
                    }],
                }],
            }]}
        else:
            payload = {"categories": [
                {"category": category, "sufficient": False, "rationale": "More sources needed"}
                for category in get_args(RetrievalCategory)
            ]}
        return SimpleNamespace(content=json.dumps(payload), usage_metadata={"input_tokens": 100, "output_tokens": 20})

    planning_provider[1].ainvoke.side_effect = respond
    assert runner.main([
        str(repository), "--database", str(tmp_path / "partial-final.sqlite"),
        "--stdout", "--no-trace",
    ]) == 1
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert "private provider response" not in captured.err + captured.out
    assert result["execution_status"] == "partial"
    assert result["finalization_reason"] == "plan_retrieval_failed"
    assert len(result["knowledge"]) == 1
    assert result["knowledge"][0]["evidence"][0]["quote"] == "Gateway routes requests."
    assert result["consulted_documents"][0]["path"] == "README.md"
    assert result["validation_errors"][0]["target"] == "execution"


def test_discovery_only_does_not_create_model(
    repository, tmp_path, planning_provider, capsys
):
    (repository / "README.md").write_text("documentation", encoding="utf-8")
    commit(repository)
    assert (
        runner.main(
            [
                str(repository),
                "--database",
                str(tmp_path / "docs.sqlite"),
                "--discovery-only",
            ]
        )
        == 0
    )
    planning_provider[0].assert_not_called()
    captured = capsys.readouterr()
    assert "Retrieval plan" not in captured.out
    assert "Model token usage" in captured.out
    assert "discover_documents: calls=0, attempts=0, reported=0" in captured.out
    assert "TOTAL" in captured.out and "unknown_attempts=0" in captured.out


def test_stdout_no_trace_keeps_json_clean_and_prints_usage_summary(
    repository, tmp_path, planning_provider, capsys
):
    (repository / "README.md").write_text("# Architecture\nGateway", encoding="utf-8")
    commit(repository)
    assert (
        runner.main(
            [
                str(repository),
                "--database",
                str(tmp_path / "usage.sqlite"),
                "--stdout",
                "--diagnostics",
                "--no-trace",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["model_usage"]["total"]["model_calls"] == 1
    assert report["model_usage"]["by_phase"]["planning"]["reported_total_tokens"] == 110
    assert "Model token usage by phase" in captured.err
    assert "[architecture_context]" not in captured.err
    assert planning_provider[1].ainvoke.await_count == 1


def test_runner_prints_partial_usage_after_provider_failure(
    repository, tmp_path, planning_provider, capsys
):
    class ProviderError(Exception):
        pass

    (repository / "README.md").write_text(
        "# Architecture\nGateway handles requests.", encoding="utf-8"
    )
    commit(repository)
    _, provider = planning_provider
    provider.ainvoke.side_effect = ProviderError("provider payload must not leak")
    assert (
        runner.main(
            [
                str(repository),
                "--database",
                str(tmp_path / "partial.sqlite"),
                "--no-trace",
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert "Model token usage by phase" in captured.err
    assert "unknown_attempts=1" in captured.err
    assert "estimated=" in captured.err
    assert "provider payload must not leak" not in captured.err


def test_empty_catalog_needs_no_credentials_and_has_empty_plan(
    repository, tmp_path, planning_provider, capsys
):
    commit(repository)
    assert (
        runner.main([str(repository), "--database", str(tmp_path / "docs.sqlite")]) == 0
    )
    planning_provider[0].assert_not_called()
    assert '"tasks": []' in capsys.readouterr().out


def test_provider_failure_closes_client_and_returns_failure(
    repository, tmp_path, planning_provider, monkeypatch, capsys
):
    (repository / "README.md").write_text("documentation", encoding="utf-8")
    commit(repository)
    planning_provider[1].ainvoke.side_effect = RuntimeError("secret provider payload")
    cleanup = AsyncMock()
    monkeypatch.setattr(runner, "close_model_clients", cleanup)
    assert (
        runner.main([str(repository), "--database", str(tmp_path / "docs.sqlite")]) == 1
    )
    cleanup.assert_awaited_once()
    message = capsys.readouterr().err
    assert "secret provider payload" not in message
    errors = [
        json.loads(line.removeprefix("[architecture_context] "))
        for line in message.splitlines()
        if line.startswith("[architecture_context] ") and '"event": "exception"' in line
    ]
    assert len(errors) >= 2
    assert errors[0]["cause_depth"] == 0 and errors[1]["cause_depth"] == 1
    assert any(
        frame["function"] == "run_node"
        for event in errors
        for frame in event["traceback"]
    )
    assert all(frame["line"] > 0 for event in errors for frame in event["traceback"])


@pytest.mark.parametrize("failed", [False, True])
def test_no_trace_disables_operational_and_exception_traces(
    repository,
    tmp_path,
    planning_provider,
    capsys,
    failed,
):
    (repository / "README.md").write_text("# Architecture", encoding="utf-8")
    commit(repository)
    if failed:
        planning_provider[1].ainvoke.side_effect = RuntimeError(
            "secret provider payload"
        )
    assert runner.main(
        [
            str(repository),
            "--database",
            str(tmp_path / "quiet.sqlite"),
            "--no-trace",
            "--stdout",
        ]
    ) == int(failed)
    message = capsys.readouterr()
    assert "[architecture_context]" not in message.err
    assert "secret provider payload" not in message.err
    assert not failed or "Architecture context failed" in message.err


@pytest.mark.usefixtures("finite_token_budget")
def test_runner_respects_global_finite_budget_and_preserves_failed_attempt_accounting(
    repository,
    tmp_path,
    planning_provider,
    monkeypatch,
    capsys,
):
    from server.config.token_budget import effective_token_budget_policy

    class ProviderError(Exception):
        status_code = 503

    (repository / "README.md").write_text("# Architecture\nGateway", encoding="utf-8")
    commit(repository)
    factory, provider = planning_provider
    factory.return_value = (provider, SimpleNamespace(max_tokens=64000))
    original_limits = runner.InvestigationConfig
    monkeypatch.setattr(
        runner,
        "InvestigationConfig",
        lambda **options: original_limits(
            max_provider_retries=2,
            provider_retry_backoff_seconds=0,
            provider_request_interval_seconds=0,
            provider_rate_limits={
                "requests_per_minute": None,
                "tokens_per_minute": None,
            },
            **options,
        ),
    )
    runtimes = []
    original_runtime = runner.BudgetedModel

    def capture_runtime(*args):
        runtime = original_runtime(*args)
        runtimes.append(runtime)
        return runtime

    monkeypatch.setattr(runner, "BudgetedModel", capture_runtime)
    planning_attempts = 0

    def respond(messages, **kwargs):
        nonlocal planning_attempts
        prompt = messages[0].content
        if "Retrieved sections:\n" in prompt:
            source = json.loads(prompt.split("Retrieved sections:\n", 1)[1])
            return SimpleNamespace(content=json.dumps({"sections": [
                {"section_id": item["section_id"], "claims": [], "issues": []}
                for item in source
            ]}), usage_metadata={"input_tokens": 100, "output_tokens": 20})
        if "Accumulated knowledge" in prompt:
            return SimpleNamespace(content=json.dumps({"categories": [
                {"category": category, "sufficient": False, "rationale": "No claims"}
                for category in get_args(RetrievalCategory)
            ]}), usage_metadata={"input_tokens": 100, "output_tokens": 20})
        assert "Retrieval context:\n" in prompt
        planning_attempts += 1
        if planning_attempts < 3:
            raise ProviderError()
        result = {
            "tasks": [
                {"category": "components", "operation": "read", "path": "README.md"}
            ]
        }
        return SimpleNamespace(
            content=json.dumps(result),
            usage_metadata={"input_tokens": 100, "output_tokens": 20},
        )

    provider.ainvoke.side_effect = respond
    policy_before = effective_token_budget_policy()
    assert not policy_before.unlimited_token_budget
    assert (
        runner.main(
            [
                str(repository),
                "--database",
                str(tmp_path / "unlimited.sqlite"),
                "--max-output-tokens",
                "64000",
            ]
        )
        == 1
    )
    assert effective_token_budget_policy() == policy_before
    assert planning_attempts == 1 and provider.ainvoke.await_count == 1
    assert runtimes[0].tokens.used > 0
    assert runtimes[0].tokens.estimated == runtimes[0].tokens.used
    assert runtimes[0].attempts == 1
    events = [
        json.loads(line.removeprefix("[architecture_context] "))
        for line in capsys.readouterr().err.splitlines()
        if line.startswith("[architecture_context] ")
    ]
    provider_errors = [event for event in events if event["event"] == "provider_error"]
    assert len(provider_errors) == 1 and all(
        event["http_status"] == 503 for event in provider_errors
    )
    assert len([event for event in events if event["event"] == "provider_request"]) == 1
    assert any(event.get("diagnostic") == "local_token_budget_exhausted" for event in events)


def test_output_override_reaches_both_model_settings_and_execution_limits(
    repository,
    tmp_path,
    planning_provider,
    monkeypatch,
):
    from server.config.schemas import ModelSettings

    (repository / "README.md").write_text("# Architecture", encoding="utf-8")
    commit(repository)
    planning_provider[0].return_value = (
        planning_provider[1],
        SimpleNamespace(max_tokens=12000),
    )
    assert (
        runner.main(
            [
                str(repository),
                "--database",
                str(tmp_path / "output.sqlite"),
                "--max-output-tokens",
                "12000",
            ]
        )
        == 0
    )
    assert planning_provider[1].ainvoke.call_args.kwargs["max_tokens"] == 12000
    args = planning_provider[0].call_args.args[0]
    settings = ModelSettings(
        provider="google",
        name="gemini-3.5-flash-lite",
        max_tokens=4000,
        temperature=1.0,
    )
    monkeypatch.setattr(
        runner, "load_dev_agents_config", lambda: {"dummy": (None, settings)}
    )
    monkeypatch.setattr(
        runner,
        "get_server_settings",
        lambda: SimpleNamespace(llm_api_key="offline-test"),
    )
    builder = Mock(return_value=planning_provider[1])
    monkeypatch.setattr(runner, "build_chat_model", builder)
    create_planning_model(args)
    assert builder.call_args.args[0].max_tokens == 12000
    assert settings.max_tokens == 4000


def test_duplicate_planning_json_is_diagnosed_without_payload_leak(
    repository,
    tmp_path,
    planning_provider,
    capsys,
):
    (repository / "README.md").write_text("# Architecture\nGateway", encoding="utf-8")
    commit(repository)
    provider = planning_provider[1]

    def respond(messages, **kwargs):
        text = '{"tasks": [], "tasks": [], "private": "sensitive source"}'
        return SimpleNamespace(
            content=text, usage_metadata={"input_tokens": 100, "output_tokens": 20}
        )

    provider.ainvoke.side_effect = respond
    assert (
        runner.main([str(repository), "--database", str(tmp_path / "invalid.sqlite")])
        == 1
    )
    message = capsys.readouterr().err
    assert "plan_retrieval: invalid_json (duplicate_keys)" in message
    assert "discovery failed" not in message and "sensitive source" not in message
    assert provider.ainvoke.await_count == 1


def test_runner_verifies_commit_and_keeps_selected_subdirectory(
    repository, tmp_path, monkeypatch, capsys
):
    child = repository / "examples" / "shoplab" / "repository"
    child.mkdir(parents=True)
    (child / "README.md").write_text("scoped documentation", encoding="utf-8")
    (repository / "parent.md").write_text("outside scope", encoding="utf-8")
    commit(repository)
    reference = (
        subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"])
        .decode()
        .strip()
    )
    (child / "untracked.md").write_text("not committed", encoding="utf-8")

    original_run = subprocess.run

    def scoped_git(command, **kwargs):
        assert "--show-toplevel" not in command and "--full-tree" not in command
        return original_run(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", scoped_git)
    assert runner.main([str(child), "--database", str(tmp_path / "scoped.sqlite")]) == 0
    text = capsys.readouterr().out
    assert f"Repository: {child.resolve()}" in text
    assert "Documents discovered: 1" in text and f"Commit: {reference}" in text
    assert "parent.md" not in text
