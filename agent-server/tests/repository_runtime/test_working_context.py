"""Large-context regressions: source survives fitting and retains exact provenance."""

import asyncio
import json

import pytest

from server.project_analysis.project_architecture import ProjectArchitectureAgent
from server.project_analysis.project_orientation import ProjectOrientationAgent
from server.runtimes.repository import (
    ExecutionBudget,
    RepositoryContext,
    RepositoryInput,
    RepositoryToolset,
    ToolLimits,
)
from server.runtimes.repository.working_context import (
    WorkingContext,
    source_arguments,
    source_view,
)
from server.services.repository_analysis import RepositoryAnalysisService


@pytest.fixture
def tools(tmp_path):
    workspace = tmp_path / "workspace"
    root = workspace / "selected"
    root.mkdir(parents=True)
    for name in ("main", "service"):
        content = (
            f"# {name.upper()}_SOURCE\ndef {name}():\n    return 42\n"
            + "# retained implementation context "
            + "x" * 100
            + "\n"
        )
        content += ("# " + "context " * 12 + "\n") * 50
        (root / f"{name}.py").write_text(content, encoding="utf-8")
    snapshot = RepositoryAnalysisService().analyze_sync(root)
    return RepositoryToolset(
        RepositoryContext(
            snapshot=snapshot,
            input=RepositoryInput(snapshot_hash=snapshot.repository.snapshot_hash),
        ),
        workspace_root=workspace,
        limits=ToolLimits(compact=True),
    )


@pytest.mark.parametrize("role", ["orientation", "architecture"])
def test_large_metadata_does_not_hide_source_or_repeat_initial_prompt(
    tools, monkeypatch, role
):
    if role == "orientation":
        import server.project_analysis.project_orientation.agent as module

        agent_type = ProjectOrientationAgent
        marker = "\nORIENTATION_DATA\n"
    else:
        import server.project_analysis.project_architecture.agent as module

        agent_type = ProjectArchitectureAgent
        marker = "\nARCHITECTURE_DATA\n"
    original = module.representation_view

    def oversized(*args):
        view = original(*args)
        view["entrypoints"] = [
            {"kind": "service", "target": "signal" * 100} for _ in range(24)
        ]
        view["projects"] = [
            {"id": f"project:{index}", "path": str(index), "name": "project" * 450}
            for index in range(4)
        ]
        for item in view["candidate_files"]:
            item["symbols"] = [
                {"name": "symbol" * 200, "start_line": 1, "end_line": 20}
            ]
        return view

    monkeypatch.setattr(module, "representation_view", oversized)

    class Model:
        def __init__(self):
            self.prompts = []

        async def generate(self, prompt):
            self.prompts.append(prompt)
            data = json.loads(prompt.split(marker, 1)[1])
            if len(self.prompts) == 1:
                assert not data["tool_results"]
                return json.dumps(
                    {
                        "tool_calls": [
                            {
                                "id": path,
                                "name": "get_source_excerpt",
                                "arguments": {"path": path},
                            }
                            for path in ("main.py", "service.py")
                        ]
                    }
                )
            responses = [json.loads(item["content"]) for item in data["tool_results"]]
            responses = [
                item for item in responses if "file_id" in item.get("data", {})
            ]
            assert len(responses) == 2
            assert {value["data"]["path"] for value in responses} == {
                "main.py",
                "service.py",
            }
            assert all(
                value["data"]["truncated"]
                and value["data"]["end_line"] < value["data"]["requested_end_line"]
                for value in responses
            )
            assert "MAIN_SOURCE" in prompt and "SERVICE_SOURCE" in prompt
            assert data["representation"]["prompt_metadata_omissions"]
            evidence = [
                record["id"]
                for value in responses
                for record in value["evidence"]
                if record["kind"] == "source"
            ]
            assert set(evidence) <= {
                record["id"] for record in data["source_evidence_ledger"]
            }
            if role == "orientation":
                assert data["query_ledger"]
                claim = {
                    "statement": "Two implementation files were inspected.",
                    "status": "supported",
                    "evidence_ids": evidence,
                }
                return json.dumps(
                    {
                        "orientation": {
                            "project_type": claim,
                            "purpose": claim,
                            "starting_points": [
                                {
                                    "file_id": responses[0]["data"]["file_id"],
                                    "reason": "Implementation starting point.",
                                }
                            ],
                        }
                    }
                )
            return json.dumps(
                {
                    "architecture": {
                        "relationship_investigations": [
                            {
                                "unit_name": "Application",
                                "status": "unresolved",
                                "resolution_blocker": "evidence_inconclusive",
                                "blocker_reason": "Only truncated implementation ranges are retained; complete boundary behavior beyond these ranges is not established by this fixture.",
                                "examined_file_ids": [
                                    value["data"]["file_id"] for value in responses
                                ],
                                "assessment": {
                                    "statement": "Cross-module boundaries were not investigated by this context-fitting fixture.",
                                    "scope": "main.py and service.py",
                                    "status": "unresolved",
                                    "evidence_ids": evidence,
                                    "limitations": [
                                        "Only source context fitting was verified."
                                    ],
                                },
                            }
                        ],
                        "closest_architecture": {
                            "pattern": "No clear pattern established",
                            "assessment": {
                                "statement": "No pattern established.",
                                "scope": "Two inspected files",
                                "status": "unresolved",
                                "limitations": [
                                    "Only source context fitting was verified."
                                ],
                            },
                        },
                        "organization": [
                            {
                                "name": "Application",
                                "file_ids": [
                                    value["data"]["file_id"] for value in responses
                                ],
                                "responsibility": {
                                    "statement": "Implements entry and service functions.",
                                    "scope": "main.py and service.py",
                                    "status": "supported",
                                    "evidence_ids": evidence,
                                },
                            }
                        ],
                        "explanation": {
                            "statement": "Two implementation files were inspected.",
                            "scope": "main.py and service.py",
                            "status": "supported",
                            "evidence_ids": evidence,
                        },
                    }
                }
            )

    model = Model()
    result = asyncio.run(agent_type(model).run(tools))
    assert result.completion_status != "failed"
    assert (
        result.usage.model_calls
        == len(model.prompts)
        == (3 if role == "architecture" else 2)
    )
    assert result.usage.tool_calls == (3 if role == "architecture" else 2)
    assert not result.execution_issues
    assert any(
        part.category == "source" and part.characters > 0
        for part in result.telemetry.model_calls[-1].context
    )


def test_range_bounding_registers_the_actual_range_and_marks_the_requested_omission(
    tools,
):
    args, requested = source_arguments(
        tools, "get_source_excerpt", {"path": "main.py"}, max_characters=400
    )
    assert args["end_line"] < requested
    response = tools.execute("get_source_excerpt", args, tool_call_id="bounded-range")
    view = source_view(tools, response, requested)
    record = next(record for record in response.evidence if record.kind == "source")
    assert record.end_line == args["end_line"] == view["data"]["end_line"]
    assert view["data"]["requested_end_line"] == requested and view["data"]["truncated"]
    assert len(view["data"]["content"]) <= 400
    unchanged, _ = source_arguments(
        tools, "get_source_excerpt", {"path": "../neighbor/secret.py"}
    )
    assert unchanged == {"path": "../neighbor/secret.py"}


def test_protection_prefers_distinct_source_files_without_mutating_retained_context():
    def message(signature, file_id):
        return {
            "signature": signature,
            "content": json.dumps(
                {"status": "ok", "data": {"file_id": file_id, "content": "source"}}
            ),
        }

    responses = [
        message("old-a", "file:a"),
        message("b", "file:b"),
        message("new-a", "file:a"),
    ]
    original = {
        "projects": [{"id": "one"}, {"id": "two"}],
        "candidate_files": [{"id": "a"}, {"id": "b"}],
    }
    working = WorkingContext(original, responses)
    while working.reduce():
        pass
    assert {item["signature"] for item in working.responses} == {"b", "new-a"}
    assert working.omitted_results == 1
    assert len(original["projects"]) == 2 and len(responses) == 3
    assert not working.representation["projects"]
    assert not working.representation["candidate_files"]


def test_initial_navigation_is_kept_until_source_is_available():
    working = WorkingContext(
        {"projects": [{"id": "one"}], "candidate_files": [{"id": "a"}, {"id": "b"}]}, []
    )
    assert not working.reduce()
    assert len(working.representation["candidate_files"]) == 2
    assert len(working.representation["projects"]) == 1


@pytest.mark.parametrize(
    "agent_type", [ProjectOrientationAgent, ProjectArchitectureAgent]
)
@pytest.mark.usefixtures("finite_token_budget")
def test_rejected_request_reports_sizes_and_budget_without_submitting(
    tools, agent_type
):
    limited = RepositoryToolset(
        RepositoryContext(
            snapshot=tools.context.snapshot,
            input=tools.context.input.model_copy(
                update={"budget": ExecutionBudget(max_total_tokens=1000)}
            ),
        ),
        workspace_root=tools.policy.workspace_root,
        limits=ToolLimits(compact=True),
    )

    class Model:
        async def generate(self, prompt):
            raise AssertionError("Request must be rejected locally")

    events = []
    options = {}
    if agent_type is ProjectArchitectureAgent:
        from server.project_analysis.project_architecture.schemas import (
            ArchitectureLimits,
        )

        options["limits"] = ArchitectureLimits(soft_token_budgets=False)
    result = asyncio.run(
        agent_type(
            Model(),
            on_event=lambda name, values: events.append((name, values)),
            **options,
        ).run(limited)
    )
    assert result.completion_status == "failed" and result.usage.model_calls == 0
    rejected = next(values for name, values in events if name == "context_rejected")
    assert rejected["estimated_input_tokens"] > 0 and rejected["prompt_characters"] > 0
    assert rejected["remaining_total_tokens"] == 1000
    assert sum(rejected["context_characters"].values()) == rejected["prompt_characters"]
    assert "reason" in rejected
