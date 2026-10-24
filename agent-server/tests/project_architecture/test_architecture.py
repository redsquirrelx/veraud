"""Architecture graph, multi-file evidence, handoff binding, and bounded execution."""

import asyncio
import json

import pytest

from server.agents.project_analysis.project_architecture import ProjectArchitectureAgent
from server.agents.project_analysis.project_architecture.context import (
    validate_report,
)
from server.agents.project_analysis.project_architecture.projection import (
    representation_view,
)
from server.agents.project_analysis.project_architecture.schemas import (
    ArchitectureLimits,
    ArchitectureReport,
    ArchitectureTurn,
)
from server.agents.project_analysis.project_orientation import ProjectOrientationAgent
from server.agents.project_analysis.project_orientation.smoke import (
    OrientationSmokeModel,
)
from server.run_project_architecture import main
from server.runtimes.repository import (
    ExecutionBudget,
    RepositoryContext,
    RepositoryInput,
    RepositoryToolset,
    ToolLimits,
)
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
        RepositoryContext(
            snapshot=snapshot,
            input=RepositoryInput(
                snapshot_hash=snapshot.repository.snapshot_hash,
                budget=ExecutionBudget(max_tokens_per_objective=60000),
            ),
        ),
        workspace_root=workspace,
        limits=ToolLimits(compact=True),
    )


def run(model, tools, orientation=None):
    return asyncio.run(ProjectArchitectureAgent(model).run(tools, orientation))


def test_mixed_response_executes_tools_before_accepting_report(tools):
    class MixedModel(Model):
        async def generate(self, prompt):
            value = json.loads(await super().generate(prompt))
            if value.get("tool_calls"):
                value["architecture"] = {"organization": "invalid premature report"}
            return json.dumps(value)

    events = []
    model = MixedModel()
    result = asyncio.run(
        ProjectArchitectureAgent(
            model, on_event=lambda name, values: events.append(name)
        ).run(tools)
    )
    assert "architecture_mixed_response_recovered" in events
    assert not result.execution_issues
    assert result.architecture is not None
    assert result.usage.tool_calls >= 2


def test_empty_response_has_distinct_action_error():
    with pytest.raises(ValueError, match="No action returned"):
        ArchitectureTurn.model_validate({"tool_calls": [], "architecture": None})


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
            "relationship_investigations": [
                {
                    "unit_name": unit["name"],
                    "status": "connected",
                    "assessment": claim(
                        "The inspected entry delegates to the inspected application; the boundary relationship is established by these files.",
                        evidence,
                    ),
                    "examined_file_ids": unit["file_ids"],
                }
                for unit in units
            ],
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
                "observed_paths": [
                    [
                        {
                            "source_unit": "Entry",
                            "target_unit": "Application",
                            "description": claim(
                                "main calls service.execute and returns its result.",
                                evidence,
                            ),
                        }
                    ]
                ],
                "contrast_question": "Does the inspected entry implement the application computation itself?",
                "contrast_result": claim(
                    "main delegates the computation to execute; this check is limited to the inspected entry.",
                    evidence,
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


def test_file_shaped_source_aliases_are_resolved_and_audited_without_downgrading(tools):
    class FileAliases(Model):
        async def generate(self, prompt):
            value = json.loads(await super().generate(prompt))
            if "architecture" in value:
                data = json.loads(prompt.split("\nARCHITECTURE_DATA\n", 1)[1])
                aliases = {
                    record["id"]: "retrieval:" + record["file_id"].removeprefix("file:")
                    for record in data["source_evidence_ledger"]
                }
                text = json.dumps(value)
                for identifier, alias in aliases.items():
                    text = text.replace(identifier, alias)
                return text
            return json.dumps(value)

    result = run(FileAliases(), tools)
    assert result.completion_status == "complete"
    assert result.architecture.closest_architecture.assessment.status == "supported"
    assert len(result.reference_repairs) == 2
    assert set(result.reference_repairs.values()) == {
        record.evidence_id for record in result.citations
    }


def test_classification_from_one_file_is_rejected_but_valid_sections_survive(tools):
    result = run(Model(single_file=True), tools)
    assert result.completion_status == "partial"
    assert result.architecture.closest_architecture.assessment.status == "hypothesis"
    assert len(result.architecture.organization) == 2
    assert result.usage.model_calls == 4
    assert sum(record.correction for record in result.telemetry.model_calls) == 0
    assert any("multiple files" in issue.message for issue in result.execution_issues)


def test_fabricated_deviation_does_not_discard_valid_classification(tools):
    result = run(Model(invalid=True), tools)
    assert result.completion_status == "partial"
    assert result.architecture.closest_architecture
    assert not result.architecture.deviations
    assert result.architecture.explanation


@pytest.mark.parametrize(
    "missing", ["observed_paths", "contrast_question", "contrast_result"]
)
def test_supported_pattern_requires_path_and_contrast_but_salvages_other_findings(
    tools, missing
):
    class MissingEvidence(Model):
        async def generate(self, prompt):
            value = json.loads(await super().generate(prompt))
            if "architecture" in value:
                value["architecture"]["closest_architecture"].pop(missing)
            return json.dumps(value)

    result = run(MissingEvidence(), tools)
    assert result.completion_status == "partial"
    assert result.architecture.closest_architecture.assessment.status == "hypothesis"
    assert len(result.architecture.organization) == 2
    assert result.architecture.connections and result.architecture.explanation


@pytest.mark.parametrize(
    "failure",
    ["single_endpoint", "unknown_evidence", "disconnected", "repeated_global"],
)
def test_pattern_path_and_contrast_are_checked_against_own_source(tools, failure):
    class InvalidInvestigation(Model):
        async def generate(self, prompt):
            value = json.loads(await super().generate(prompt))
            if "architecture" not in value:
                return json.dumps(value)
            classification = value["architecture"]["closest_architecture"]
            edge = classification["observed_paths"][0][0]
            if failure == "single_endpoint":
                edge["description"]["evidence_ids"] = edge["description"][
                    "evidence_ids"
                ][:1]
            elif failure == "unknown_evidence":
                classification["contrast_result"]["evidence_ids"] = [
                    "retrieval:invented"
                ]
            elif failure == "disconnected":
                classification["observed_paths"][0].append(edge.copy())
            else:
                classification["scope_kind"] = "repository"
                classification["observed_paths"].append([edge.copy()])
            return json.dumps(value)

    result = run(InvalidInvestigation(), tools)
    if failure == "single_endpoint":
        assert result.completion_status == "complete"
        assert result.architecture.closest_architecture.assessment.status == "supported"
        assert result.architecture.closest_architecture.assessment_origin == "model"
        return
    assert result.completion_status == "partial"
    assert result.architecture.closest_architecture.assessment.status == "hypothesis"
    assert result.architecture.organization and result.architecture.explanation


def test_missing_path_can_be_reported_as_explicit_hypothesis(tools):
    class Hypothesis(Model):
        async def generate(self, prompt):
            value = json.loads(await super().generate(prompt))
            if "architecture" in value:
                classification = value["architecture"]["closest_architecture"]
                classification.pop("observed_paths")
                classification.pop("contrast_question")
                classification.pop("contrast_result")
                classification["assessment"].update(
                    status="hypothesis",
                    limitations=[
                        "A complete path and contrast have not been inspected."
                    ],
                )
            return json.dumps(value)

    result = run(Hypothesis(), tools)
    assert result.architecture.closest_architecture.assessment.status == "hypothesis"
    assert not result.execution_issues


@pytest.mark.parametrize("answer_final", [True, False])
def test_missing_assessment_gets_final_turn_or_explicit_unresolved_fallback(
    tools, answer_final
):
    class MissingAssessment(Model):
        async def generate(self, prompt):
            value = json.loads(await super().generate(prompt))
            if "architecture" not in value:
                return json.dumps(value)
            data = json.loads(prompt.split("\nARCHITECTURE_DATA\n", 1)[1])
            if answer_final and data["closing_instruction"].startswith(
                "Return architecture now"
            ):
                value["architecture"]["closest_architecture"]["assessment"].update(
                    status="hypothesis",
                    limitations=[
                        "Only the local entry/service boundary was inspected."
                    ],
                )
            else:
                value["architecture"].pop("closest_architecture")
                value["architecture"].pop("explanation")
            return json.dumps(value)

    events = []
    result = asyncio.run(
        ProjectArchitectureAgent(
            MissingAssessment(),
            on_event=lambda name, values: events.append((name, values)),
        ).run(tools)
    )
    assert result.usage.model_calls == 4
    assert any(name == "architecture_final_assessment" for name, _ in events)
    assert len(result.architecture.organization) == 2
    assert result.architecture.closest_architecture and result.architecture.explanation
    if answer_final:
        assert (
            result.architecture.closest_architecture.assessment.status == "hypothesis"
        )
        assert not result.execution_issues
    else:
        assert (
            result.architecture.closest_architecture.assessment.status == "unresolved"
        )
        assert result.architecture.explanation.status == "unresolved"
        assert result.completion_status == "partial"
        assert (
            "Host fallback"
            in result.architecture.closest_architecture.assessment.limitations[0]
        )


def test_provider_failure_during_correction_preserves_valid_sections(tools):
    class FailedCorrection(Model):
        async def generate(self, prompt):
            if len(self.prompts) == 2:
                raise RuntimeError("Provider unavailable")
            return await super().generate(prompt)

    result = run(FailedCorrection(single_file=True), tools)
    assert result.completion_status == "partial"
    assert len(result.architecture.organization) == 2
    assert result.architecture.closest_architecture.assessment.status == "hypothesis"
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
        RepositoryContext(snapshot=tools.context.snapshot, input=tools.context.input),
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
    assert result.usage.tool_calls <= 20 and result.usage.model_calls <= 8
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
    model = Model()
    stopped = asyncio.run(
        ProjectArchitectureAgent(
            model, limits=ArchitectureLimits(soft_token_budgets=False)
        ).run(limited)
    )
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


def test_soft_architecture_budgets_allow_submission_and_retry_over_estimated_limits(
    tools,
):
    limited = RepositoryToolset(
        RepositoryContext(
            snapshot=tools.context.snapshot,
            input=tools.context.input.model_copy(
                update={
                    "budget": ExecutionBudget(
                        max_total_tokens=1000,
                        max_tokens_per_objective=1000,
                        max_input_tokens_per_call=500,
                    )
                }
            ),
        ),
        workspace_root=tools.policy.workspace_root,
        limits=ToolLimits(compact=True),
    )
    model = Model()

    class Gateway:
        telemetry = True

        def __init__(self):
            self.measurements = []

        async def __call__(self, prompt):
            # Simulate runtime admission before a third provider attempt.
            self.request_guard(prompt, 2)
            return await model.generate(prompt)

    events = []
    result = asyncio.run(
        ProjectArchitectureAgent(
            model,
            generate=Gateway(),
            on_event=lambda name, values: events.append((name, values)),
        ).run(limited)
    )
    assert result.completion_status == "complete"
    assert result.usage.model_calls == 2 and not result.usage.token_budget_exhausted
    assert not any(name == "context_rejected" for name, _ in events)
    assert any(
        name == "budget_advisory" and values.get("previous_attempts") == 2
        for name, values in events
    )


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
    with pytest.raises(SystemExit) as error:
        main([*args, "--orientation"])
    assert error.value.code == 2


def test_runner_relaxed_architecture_defaults_respect_explicit_token_limits(
    tools, capsys, monkeypatch
):
    captured = []
    original = ProjectArchitectureAgent.run

    async def capture(agent, architecture_tools, orientation=None):
        captured.append((architecture_tools.context.input.budget, agent.limits))
        return await original(agent, architecture_tools, orientation)

    monkeypatch.setattr(ProjectArchitectureAgent, "run", capture)
    args = [
        tools.context.snapshot.repository.root_path,
        "--workspace-root",
        str(tools.policy.workspace_root),
        "--smoke",
        "--quiet",
        "--json",
        "--skip-orientation",
    ]
    assert main(args) == 0
    capsys.readouterr()
    budget, limits = captured[-1]
    assert (budget.max_model_calls, budget.max_tool_calls) == (24, 32)
    assert (
        budget.max_input_tokens_per_call,
        budget.max_tokens_per_objective,
        budget.max_total_tokens,
    ) == (10000, 80000, 160000)
    assert (
        limits.max_prompt_characters == 36000 and limits.max_source_characters == 2400
    )
    assert (
        main(
            [
                *args,
                "--max-input-tokens",
                "6000",
                "--max-objective-tokens",
                "20000",
                "--max-total-tokens",
                "60000",
                "--max-model-calls",
                "4",
                "--max-tool-calls",
                "6",
            ]
        )
        == 0
    )
    capsys.readouterr()
    budget, _ = captured[-1]
    assert (budget.max_model_calls, budget.max_tool_calls) == (4, 6)
    assert (
        budget.max_input_tokens_per_call,
        budget.max_tokens_per_objective,
        budget.max_total_tokens,
    ) == (6000, 20000, 60000)


def test_representation_exposes_navigation_and_omissions_without_docs(tools):
    from server.agents.project_analysis.project_architecture.agent import ALLOWED_TOOLS
    from server.runtimes.repository.tools import TOOL_SCHEMAS

    view = representation_view(tools)
    assert ALLOWED_TOOLS <= TOOL_SCHEMAS.keys()
    assert all(
        not item["path"].startswith("docs/") and item["path"] != "README.md"
        for item in view["candidate_files"]
    )
    assert view["configuration_files"][0]["path"] == "compose.yaml"
    assert "omissions" in view
