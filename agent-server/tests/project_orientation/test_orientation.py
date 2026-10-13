"""Bounded orientation, evidence integrity, partial recovery, and runner mode."""

import asyncio
import json

import pytest

from server.agents.project_orientation import ProjectOrientationAgent
from server.agents.project_orientation.context import representation_view
from server.agents.repository_runtime import (
    ExecutionBudget,
    RepositoryContext,
    RepositoryInput,
    RepositoryToolset,
    ToolLimits,
)
from server.run_project_orientation import main
from server.services.repository_analysis import RepositoryAnalysisService


@pytest.fixture
def tools(tmp_path):
    workspace = tmp_path / "workspace"
    root = workspace / "selected"
    root.mkdir(parents=True)
    (root / "main.py").write_text("def main():\n    return 42\n", encoding="utf-8")
    (root / "README.md").write_text(
        "NARRATIVE_SECRET: main returns 99", encoding="utf-8"
    )
    (root / "docs").mkdir()
    (root / "docs" / "sample.py").write_text("NARRATIVE_SECRET", encoding="utf-8")
    neighbor = workspace / "neighbor"
    neighbor.mkdir()
    (neighbor / "secret.py").write_text("NEIGHBOR_SECRET", encoding="utf-8")
    snapshot = RepositoryAnalysisService().analyze_sync(root)
    return RepositoryToolset(
        RepositoryContext(
            snapshot=snapshot,
            input=RepositoryInput(snapshot_hash=snapshot.repository.snapshot_hash),
        ),
        workspace_root=workspace,
        limits=ToolLimits(compact=True),
    )


class Model:
    def __init__(self, *, bad_component=False, no_evidence=False):
        self.prompts = []
        self.bad_component = bad_component
        self.no_evidence = no_evidence

    async def generate(self, prompt):
        self.prompts.append(prompt)
        assert "NARRATIVE_SECRET" not in prompt and "NEIGHBOR_SECRET" not in prompt
        data = json.loads(prompt.split("\nORIENTATION_DATA\n", 1)[1])
        if not data["tool_results"] and not self.no_evidence:
            return json.dumps(
                {
                    "tool_calls": [
                        {
                            "id": "read",
                            "name": "get_source_excerpt",
                            "arguments": {"path": "main.py"},
                        }
                    ]
                }
            )
        source = (
            json.loads(data["tool_results"][-1]["content"])
            if data["tool_results"]
            else {}
        )
        evidence = next(
            (item for item in source.get("evidence", []) if item["kind"] == "source"),
            {"id": "retrieval:invented"},
        )
        file_id = data["representation"]["candidate_files"][0]["id"]
        observation = {
            "statement": "main returns 42.",
            "status": "supported",
            "evidence_ids": [evidence["id"]],
        }
        return json.dumps(
            {
                "orientation": {
                    "project_type": observation,
                    "purpose": observation,
                    "components": [
                        {
                            "name": "Main",
                            "file_ids": [
                                "file:invented" if self.bad_component else file_id
                            ],
                            "responsibility": observation,
                        }
                    ],
                    "starting_points": [
                        {
                            "file_id": file_id,
                            "reason": "Inspect the main implementation.",
                        }
                    ],
                    "uncertainties": ["Runtime invocation was not verified."],
                }
            }
        )


def run(model, tools):
    return asyncio.run(ProjectOrientationAgent(model).run(tools))


def test_graph_interprets_existing_snapshot_with_two_calls_and_one_tool(tools):
    model = Model()
    agent = ProjectOrientationAgent(model)
    assert set(agent.graph.get_graph().nodes) >= {
        "prepare_context",
        "inspect",
        "tools",
        "validate",
        "finish",
    }
    result = asyncio.run(agent.run(tools))
    assert result.completion_status == "complete"
    assert result.orientation.purpose.statement == "main returns 42."
    assert result.snapshot_hash == tools.context.input.snapshot_hash
    assert result.usage.model_calls == len(model.prompts) == 2
    assert result.usage.tool_calls == 1
    assert result.usage.input_tokens is None and result.usage.estimated_tokens > 0
    assert result.inspected_file_ids == (tools.accessible_snapshot.files[0].id,)
    assert {stage.stage for stage in result.telemetry.stages} == {"investigation"}
    assert not result.execution_issues


def test_one_correction_then_invalid_components_are_discarded_without_losing_purpose(
    tools,
):
    model = Model(bad_component=True)
    result = run(model, tools)
    assert result.completion_status == "partial"
    assert result.orientation.purpose.statement == "main returns 42."
    assert not result.orientation.components
    assert len(model.prompts) == 3
    assert sum(call.correction for call in result.telemetry.model_calls) == 1
    assert result.execution_issues[0].category == "invalid_orientation"


def test_supported_observations_cannot_cite_unretrieved_source(tools):
    result = run(Model(no_evidence=True), tools)
    assert result.completion_status == "failed"
    assert result.orientation is None
    assert result.usage.model_calls == 2
    assert not result.retrieved_evidence


def test_tool_and_call_limits_terminate_repetitive_requests(tools):
    class Repeater:
        async def generate(self, prompt):
            return json.dumps(
                {
                    "tool_calls": [
                        {"id": str(index), "name": "list_files", "arguments": {}}
                        for index in range(3)
                    ]
                }
            )

    result = run(Repeater(), tools)
    assert result.usage.tool_calls == 6
    assert result.usage.model_calls <= 4
    assert result.completion_status == "failed"


def test_token_stop_happens_before_submission_and_external_cancellation_propagates(
    tools,
):
    limited = RepositoryToolset(
        RepositoryContext(
            snapshot=tools.context.snapshot,
            input=RepositoryInput(
                snapshot_hash=tools.context.input.snapshot_hash,
                budget=ExecutionBudget(max_total_tokens=1000),
            ),
        ),
        workspace_root=tools.policy.workspace_root,
        limits=ToolLimits(compact=True),
    )
    model = Model()
    result = run(model, limited)
    assert result.completion_status == "failed" and not model.prompts
    assert result.usage.token_budget_exhausted

    async def cancel_run():
        entered = asyncio.Event()

        class Waiting:
            async def generate(self, prompt):
                entered.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(ProjectOrientationAgent(Waiting()).run(tools))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_run())


def test_runner_mode_is_explicit_and_smoke_retains_uncertainty(tools, capsys):
    root = tools.context.snapshot.repository.root_path
    args = [
        root,
        "--workspace-root",
        str(tools.policy.workspace_root),
        "--smoke",
        "--quiet",
        "--json",
    ]
    assert main(args) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["completion_status"] == "partial"
    assert data["run_metadata"]["workflow"] == "orientation"
    assert data["usage"]["model_calls"] == 2
    assert data["file_paths"]
    with pytest.raises(SystemExit) as error:
        main([*args, "--baseline"])
    assert error.value.code == 2


def test_representation_projection_is_compact_and_access_filtered(tools):
    from server.agents.project_orientation.agent import ALLOWED_TOOLS
    from server.agents.repository_runtime.tools import TOOL_SCHEMAS

    assert ALLOWED_TOOLS <= TOOL_SCHEMAS.keys()
    view = representation_view(tools)
    assert view["technical_file_count"] == 1
    assert [file["path"] for file in view["candidate_files"]] == ["main.py"]
    assert len(json.dumps(view)) < 4000
