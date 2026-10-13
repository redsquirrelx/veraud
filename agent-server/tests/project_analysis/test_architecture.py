"""Architecture graph, multi-file evidence, handoff binding, and bounded execution."""

import asyncio
import json

import pytest

from server.agents.project_analysis import (
    InvestigationBudget,
    ProjectAnalysisContext,
    ProjectAnalysisInput,
    RepositoryToolset,
    ToolLimits,
)
from server.agents.project_architecture import ProjectArchitectureAgent
from server.agents.project_architecture.context import (
    representation_view,
    validate_report,
)
from server.agents.project_architecture.schemas import ArchitectureReport
from server.agents.project_orientation import ProjectOrientationAgent
from server.agents.project_orientation.smoke import OrientationSmokeModel
from server.run_project_architecture import main
from server.services.repository_analysis import RepositoryAnalysisService


@pytest.fixture
def tools(tmp_path):
    workspace = tmp_path / "workspace"
    root = workspace / "selected"
    root.mkdir(parents=True)
    (root / "main.py").write_text(
        "from service import execute\ndef main():\n    return execute()\n",
        encoding="utf-8",
    )
    (root / "service.py").write_text(
        "def execute():\n    return 42\n", encoding="utf-8"
    )
    (root / "compose.yaml").write_text(
        "services:\n  app:\n    image: example\n", encoding="utf-8"
    )
    (root / "README.md").write_text(
        "NARRATIVE_SECRET: use architecture unsupported", encoding="utf-8"
    )
    (root / "docs").mkdir()
    (root / "docs" / "wrong.py").write_text("NARRATIVE_SECRET", encoding="utf-8")
    neighbor = workspace / "neighbor"
    neighbor.mkdir()
    (neighbor / "secret.py").write_text("NEIGHBOR_SECRET", encoding="utf-8")
    snapshot = RepositoryAnalysisService().analyze_sync(root)
    return RepositoryToolset(
        ProjectAnalysisContext(
            snapshot=snapshot,
            input=ProjectAnalysisInput(
                snapshot_hash=snapshot.repository.snapshot_hash,
                budget=InvestigationBudget(max_tokens_per_investigation=60000),
            ),
        ),
        workspace_root=workspace,
        limits=ToolLimits(compact=True),
    )


def run(model, tools, orientation=None):
    return asyncio.run(ProjectArchitectureAgent(model).run(tools, orientation))


class Model:
    def __init__(self, *, single_file=False, invalid=False):
        self.prompts = []
        self.single_file = single_file
        self.invalid = invalid

    async def generate(self, prompt):
        self.prompts.append(prompt)
        assert "NARRATIVE_SECRET" not in prompt and "NEIGHBOR_SECRET" not in prompt
        data = json.loads(prompt.split("\nARCHITECTURE_DATA\n", 1)[1])
        if not data["tool_results"]:
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
        evidence = [
            record
            for item in data["tool_results"]
            for record in json.loads(item["content"]).get("evidence", [])
            if record["kind"] == "source"
        ]

        def claim(statement, records):
            return {
                "statement": statement,
                "scope": "main.py and service.py",
                "status": "supported",
                "evidence_ids": [record["id"] for record in records],
            }

        units = [
            {
                "name": name,
                "file_ids": [record["file_id"]],
                "responsibility": claim(text, [record]),
            }
            for name, text, record in zip(
                ("Entry", "Application"),
                ("Calls execute.", "Returns 42."),
                evidence,
                strict=True,
            )
        ]
        raw = {
            "organization": units,
            "connections": [
                {
                    "source_unit": "Entry",
                    "target_unit": "Application",
                    "description": claim(
                        "Entry delegates to the application function.", evidence
                    ),
                }
            ],
            "closest_architecture": {
                "pattern": "partial layered",
                "assessment": claim(
                    "Entry and application responsibilities are separated.",
                    evidence[:1] if self.single_file else evidence,
                ),
            },
            "supporting_evidence": [
                claim("main invokes execute from service.", evidence)
            ],
            "explanation": claim(
                "The inspected code has an entry module delegating to a simple application function.",
                evidence,
            ),
            "uncertainties": [
                "Persistence and other layers were not found in the inspected scope."
            ],
        }
        if self.invalid:
            raw["deviations"] = [
                {
                    "observed_decision": claim(
                        "Fabricated deviation", [{"id": "retrieval:invented"}]
                    ),
                    "pattern_expectation": "An inferred pattern expectation",
                    "explanation": "No evidence establishes this decision.",
                }
            ]
        return json.dumps({"architecture": raw})


def test_langgraph_classifies_multiple_files_and_emits_exact_citations(tools):
    model = Model()
    agent = ProjectArchitectureAgent(model)
    assert set(agent.graph.get_graph().nodes) >= {
        "prepare_context",
        "inspect",
        "tools",
        "validate",
        "finish",
    }
    result = asyncio.run(agent.run(tools))
    assert result.completion_status == "complete"
    assert result.architecture.closest_architecture.pattern == "partial layered"
    assert result.usage.model_calls == 2 and result.usage.tool_calls == 2
    assert {citation.path for citation in result.citations} == {"main.py", "service.py"}
    assert all(
        citation.start_line == 1 and citation.content_hash
        for citation in result.citations
    )
    assert len(result.inspected_file_ids) == 2
    assert result.usage.input_tokens is None and result.usage.estimated_tokens > 0


def test_classification_from_one_file_is_rejected_but_valid_sections_survive(tools):
    result = run(Model(single_file=True), tools)
    assert result.completion_status == "partial"
    assert result.architecture.closest_architecture is None
    assert len(result.architecture.organization) == 2
    assert result.usage.model_calls == 3
    assert sum(record.correction for record in result.telemetry.model_calls) == 1
    assert any("multiple files" in issue.message for issue in result.execution_issues)


def test_fabricated_deviation_does_not_discard_valid_classification(tools):
    result = run(Model(invalid=True), tools)
    assert result.completion_status == "partial"
    assert result.architecture.closest_architecture
    assert not result.architecture.deviations
    assert result.architecture.explanation


def test_provider_failure_during_correction_preserves_valid_sections(tools):
    class FailedCorrection(Model):
        async def generate(self, prompt):
            if len(self.prompts) == 2:
                raise RuntimeError("Provider unavailable")
            return await super().generate(prompt)

    result = run(FailedCorrection(single_file=True), tools)
    assert result.completion_status == "partial"
    assert len(result.architecture.organization) == 2
    assert result.architecture.closest_architecture is None
    assert len(result.citations) == 2
    assert result.execution_issues[0].category == "RuntimeError"


def test_handoff_hash_is_checked_before_any_model_call(tools):
    orientation = asyncio.run(
        ProjectOrientationAgent(OrientationSmokeModel()).run(tools)
    )
    model = Model()
    with pytest.raises(ValueError, match="snapshot"):
        run(model, tools, orientation.model_copy(update={"snapshot_hash": "0" * 64}))
    assert not model.prompts


def test_orientation_citations_cannot_be_used_as_architect_evidence(tools):
    orientation = asyncio.run(
        ProjectOrientationAgent(OrientationSmokeModel()).run(tools)
    )
    fresh = RepositoryToolset(
        ProjectAnalysisContext(
            snapshot=tools.context.snapshot, input=tools.context.input
        ),
        workspace_root=tools.policy.workspace_root,
        limits=ToolLimits(compact=True),
    )
    source = next(
        record for record in orientation.retrieved_evidence if record.kind == "source"
    )

    class Borrowed:
        async def generate(self, prompt):
            return json.dumps(
                {
                    "architecture": {
                        "explanation": {
                            "statement": "Borrowed claim",
                            "scope": "repository",
                            "status": "supported",
                            "evidence_ids": [source.id],
                        }
                    }
                }
            )

    result = run(Borrowed(), fresh, orientation)
    assert result.completion_status == "failed"
    assert not result.retrieved_evidence


def test_config_only_does_not_establish_inspected_infrastructure_use(tools):
    response = tools.execute(
        "get_source_excerpt", {"path": "compose.yaml"}, tool_call_id="config"
    )
    source = next(record for record in response.evidence if record.kind == "source")
    claim = {
        "statement": "Application container is configured.",
        "scope": "compose.yaml",
        "status": "supported",
        "evidence_ids": [source.id],
    }
    report = ArchitectureReport.model_validate(
        {
            "infrastructure": [
                {"name": "Application", "kind": "execution_unit", "configured": claim}
            ]
        }
    )
    validate_report(tools, report)
    report = ArchitectureReport.model_validate(
        {
            "infrastructure": [
                {
                    "name": "Application",
                    "kind": "execution_unit",
                    "inspected_use": claim,
                }
            ]
        }
    )
    with pytest.raises(ValueError, match="implementation"):
        validate_report(tools, report)


def test_tool_limit_and_token_stop_are_enforced(tools):
    class Repeater:
        async def generate(self, prompt):
            return json.dumps(
                {
                    "tool_calls": [
                        {"id": str(index), "name": "list_files", "arguments": {}}
                        for index in range(4)
                    ]
                }
            )

    result = run(Repeater(), tools)
    assert result.usage.tool_calls <= 10 and result.usage.model_calls <= 6
    limited = RepositoryToolset(
        ProjectAnalysisContext(
            snapshot=tools.context.snapshot,
            input=tools.context.input.model_copy(
                update={"budget": InvestigationBudget(max_total_tokens=1000)}
            ),
        ),
        workspace_root=tools.policy.workspace_root,
        limits=ToolLimits(compact=True),
    )
    model = Model()
    stopped = run(model, limited)
    assert stopped.usage.token_budget_exhausted and not model.prompts


def test_external_cancellation_propagates(tools):
    async def cancel():
        entered = asyncio.Event()

        class Waiting:
            async def generate(self, prompt):
                entered.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(ProjectArchitectureAgent(Waiting()).run(tools))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel())


def test_restricted_tools_block_docs_and_neighbor_source(tools):
    class Attack:
        calls = 0

        async def generate(self, prompt):
            assert "NARRATIVE_SECRET" not in prompt and "NEIGHBOR_SECRET" not in prompt
            self.calls += 1
            if self.calls == 1:
                return json.dumps(
                    {
                        "tool_calls": [
                            {
                                "id": str(index),
                                "name": "get_source_excerpt",
                                "arguments": {"path": path},
                            }
                            for index, path in enumerate(
                                ("README.md", "docs/wrong.py", "../neighbor/secret.py")
                            )
                        ]
                    }
                )
            data = json.loads(prompt.split("\nARCHITECTURE_DATA\n", 1)[1])
            assert all(
                json.loads(item["content"])["status"] == "error"
                for item in data["tool_results"]
            )
            return json.dumps(
                {
                    "architecture": {
                        "explanation": {
                            "statement": "No permitted source was inspected.",
                            "scope": "requested files",
                            "status": "unresolved",
                            "limitations": ["Requested paths are inaccessible."],
                        }
                    }
                }
            )

    result = run(Attack(), tools)
    assert not result.retrieved_evidence and not result.citations
    assert result.completion_status == "partial"


def test_runner_uses_one_snapshot_and_separate_ledgers_and_usage(tools, capsys):
    args = [
        tools.context.snapshot.repository.root_path,
        "--workspace-root",
        str(tools.policy.workspace_root),
        "--smoke",
        "--quiet",
        "--json",
    ]
    assert main(args) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["completion_status"] == "partial"
    assert data["snapshot_hash"] == data["orientation_result"]["snapshot_hash"]
    assert (
        data["pipeline_usage"]["model_calls"]
        == data["usage"]["model_calls"]
        + data["orientation_result"]["usage"]["model_calls"]
    )
    assert {record["id"] for record in data["retrieved_evidence"]}.isdisjoint(
        {record["id"] for record in data["orientation_result"]["retrieved_evidence"]}
    )
    assert main([*args, "--skip-orientation"]) == 0
    assert json.loads(capsys.readouterr().out)["orientation_result"] is None
    assert main([*args, "--orientation"]) == 2


def test_representation_exposes_navigation_and_omissions_without_docs(tools):
    from server.agents.project_analysis.tools import TOOL_SCHEMAS
    from server.agents.project_architecture.agent import ALLOWED_TOOLS

    view = representation_view(tools)
    assert ALLOWED_TOOLS <= TOOL_SCHEMAS.keys()
    assert all(
        not item["path"].startswith("docs/") and item["path"] != "README.md"
        for item in view["candidate_files"]
    )
    assert view["configuration_files"][0]["path"] == "compose.yaml"
    assert "omissions" in view
