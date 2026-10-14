"""Backend-facing graph shares one snapshot and isolates stage ledgers."""

import asyncio
import json

import pytest

from server.agents.project_architecture import ProjectArchitectureAgent
from server.agents.project_architecture.smoke import ArchitectureSmokeModel
from server.agents.project_orientation import ProjectOrientationAgent
from server.agents.project_orientation.smoke import OrientationSmokeModel
from server.agents.project_semantic_validation import ProjectSemanticValidationAgent
from server.agents.project_semantic_validation.smoke import SemanticValidationSmokeModel
from server.agents.repository_runtime import ExecutionBudget
from server.agents.repository_runtime.model_runtime import ModelGateway
from server.pipelines import ProjectArchitecturePipeline
from server.services.repository_analysis import RepositoryAnalysisService


def setup_pipeline(tmp_path):
    root = tmp_path / "workspace" / "checkout"
    root.mkdir(parents=True)
    (root / "main.py").write_text(
        "from service import run\ndef main():\n    return run()\n", encoding="utf-8"
    )
    (root / "service.py").write_text("def run():\n    return 42\n", encoding="utf-8")
    snapshot = RepositoryAnalysisService().analyze_sync(root)
    seen = []

    class Orientation(ProjectOrientationAgent):
        async def run(self, tools):
            seen.append(tools)
            return await super().run(tools)

    class Architect(ProjectArchitectureAgent):
        async def run(self, tools, orientation=None, **kwargs):
            seen.append(tools)
            return await super().run(tools, orientation, **kwargs)

    class Validator(ProjectSemanticValidationAgent):
        async def run(self, tools, original_result, **kwargs):
            seen.append(tools)
            return await super().run(tools, original_result, **kwargs)

    class Hooks:
        def __init__(self):
            self.events = []
            self.skips = []

        async def on_stage_start(self, stage):
            self.events.append((stage, "start"))

        async def on_stage_result(self, stage, result):
            self.events.append((stage, "result"))

        async def on_stage_skip(self, stage, reason):
            self.skips.append((stage, reason))

    hooks = Hooks()
    pipeline = ProjectArchitecturePipeline(
        Architect(ArchitectureSmokeModel()),
        orientation=Orientation(OrientationSmokeModel()),
        validator=Validator(SemanticValidationSmokeModel()),
        hooks=hooks,
    )
    return pipeline, snapshot, root.parent, seen, hooks


def test_backend_pipeline_runs_all_stages_over_one_snapshot(tmp_path):
    pipeline, snapshot, workspace, seen, hooks = setup_pipeline(tmp_path)
    result = asyncio.run(
        pipeline.run(
            snapshot,
            budget=ExecutionBudget(
                max_total_tokens=200000,
                max_tokens_per_objective=100000,
                max_input_tokens_per_call=12000,
            ),
            workspace_root=workspace,
        )
    )
    assert result.usable and result.snapshot_hash == snapshot.repository.snapshot_hash
    assert result.semantic_validation.return_count == 1
    assert len(result.semantic_validation.validations) == 2
    assert len(seen) == 5 and len({id(tools) for tools in seen}) == 5
    assert all(tools.context.snapshot is snapshot for tools in seen)
    assert hooks.events == [
        ("orientation", "start"),
        ("orientation", "result"),
        ("architecture", "start"),
        ("architecture", "result"),
        ("semantic_validation", "start"),
        ("architecture", "start"),
        ("architecture", "result"),
        ("semantic_validation", "start"),
        ("semantic_validation", "result"),
    ]
    assert result.tool_calls == sum(tools.budget_usage.tool_calls for tools in seen)
    assert (
        result.displayed_architecture == result.semantic_validation.revised_architecture
    )
    assert result.model_dump(mode="json")["semantic_validation"][
        "original_architecture"
    ] == result.architecture.model_dump(mode="json")


def test_pipeline_skip_stages_and_reuse_does_not_reuse_ledgers(tmp_path):
    pipeline, snapshot, workspace, seen, hooks = setup_pipeline(tmp_path)

    async def scenario():
        for _ in range(2):
            result = await pipeline.run(
                snapshot,
                budget=ExecutionBudget(),
                workspace_root=workspace,
                include_orientation=False,
                validate_semantics=False,
            )
            assert result.orientation is None and result.semantic_validation is None

    asyncio.run(scenario())
    assert len(seen) == 2 and seen[0] is not seen[1]
    assert hooks.events == [
        ("architecture", action) for _ in range(2) for action in ("start", "result")
    ]


def test_failed_revision_preserves_first_review_and_stops(tmp_path):
    from server.agents.project_architecture.schemas import ArchitectureResult
    from server.agents.repository_runtime.schemas import BudgetUsage
    from server.agents.repository_runtime.telemetry import ExecutionTelemetry

    pipeline, snapshot, workspace, _seen, hooks = setup_pipeline(tmp_path)
    original_run = pipeline.architect.run
    published = []
    original_publish = hooks.on_stage_result

    async def publish(stage, result):
        if stage == "semantic_validation":
            published.append(result)
        await original_publish(stage, result)

    async def fail_revision(tools, orientation=None, **kwargs):
        if kwargs.get("feedback"):
            return ArchitectureResult(
                snapshot_hash=snapshot.repository.snapshot_hash,
                completion_status="failed",
                usage=BudgetUsage(),
                telemetry=ExecutionTelemetry(),
            )
        return await original_run(tools, orientation, **kwargs)

    hooks.on_stage_result = publish
    pipeline.architect.run = fail_revision
    result = asyncio.run(
        pipeline.run(
            snapshot,
            budget=ExecutionBudget(
                max_total_tokens=200000, max_tokens_per_objective=100000
            ),
            workspace_root=workspace,
        )
    )
    history = result.semantic_validation
    assert history.return_count == 1 and len(history.validations) == 1
    assert history.revised_architecture.completion_status == "failed"
    assert result.displayed_architecture == result.architecture
    assert published == [history]


def test_developed_report_reviews_findings_beyond_old_limit(tmp_path):
    from server.agents.project_architecture.schemas import (
        ArchitecturalClaim,
        ArchitectureReport,
    )

    pipeline, snapshot, workspace, _seen, _hooks = setup_pipeline(tmp_path)

    async def scenario():
        budget = ExecutionBudget(
            max_model_calls=24, max_total_tokens=300000, max_tokens_per_objective=200000
        )
        initial = await pipeline.run(
            snapshot,
            budget=budget,
            workspace_root=workspace,
            validate_semantics=False,
            include_diagram=False,
        )
        original = initial.architecture
        findings = tuple(
            ArchitecturalClaim(
                statement=f"Inspection finding {index}: "
                + "The retained excerpt defines the inspected scope. " * 35,
                scope="retained source",
                status="hypothesis",
                evidence_ids=(original.retrieved_evidence[0].id,),
                limitations=(
                    "Offline fixture leaves the interpretation hypothetical.",
                ),
            )
            for index in range(24)
        )
        report = ArchitectureReport.model_validate(
            original.architecture.model_dump() | {"supporting_evidence": findings}
        )
        expanded = original.model_copy(update={"architecture": report})
        reviewed = await pipeline.run(
            snapshot,
            budget=budget,
            workspace_root=workspace,
            resume_architecture=expanded,
            include_diagram=False,
            allow_return=False,
        )
        return findings, reviewed.semantic_validation.validations[0]

    findings, review = asyncio.run(scenario())
    assert len(review.selected_target_ids) > 18
    assert not review.pending_target_ids
    checked = {item.target_id: item.checked_statement for item in review.findings}
    assert all(
        checked[f"/supporting_evidence/{index}"] == claim.statement
        for index, claim in enumerate(findings)
    )


@pytest.mark.parametrize("verdict", ["overstated", "contradicted"])
@pytest.mark.parametrize("allow_return", [True, False])
def test_graph_returns_for_corrections_once(tmp_path, verdict, allow_return):
    pipeline, snapshot, workspace, _seen, hooks = setup_pipeline(tmp_path)
    feedbacks = []

    class CorrectionModel(SemanticValidationSmokeModel):
        async def generate(self, prompt):
            answer = json.loads(await super().generate(prompt))
            if "findings" in answer:
                data = json.loads(str(prompt).split("\nVALIDATION_DATA\n", 1)[1])
                evidence_id = data["source_evidence_ledger"][0]["id"]
                for finding in answer["findings"]:
                    finding.update(
                        verdict=verdict,
                        evidence_ids=[evidence_id],
                        missing_evidence=[],
                        correction={
                            "statement": "Only the inspected implementation is established.",
                            "scope": "inspected source",
                            "status": "hypothesis",
                            "evidence_ids": [evidence_id],
                            "limitations": [
                                "Offline fixture does not establish global behavior."
                            ],
                        },
                    )
            return json.dumps(answer)

    original_run = pipeline.architect.run

    async def capture(tools, orientation=None, **kwargs):
        if kwargs.get("feedback"):
            feedbacks.append(kwargs["feedback"])
        return await original_run(tools, orientation, **kwargs)

    pipeline.architect.run = capture
    pipeline.validator.generate = CorrectionModel().generate
    result = asyncio.run(
        pipeline.run(
            snapshot,
            budget=ExecutionBudget(
                max_total_tokens=200000, max_tokens_per_objective=100000
            ),
            workspace_root=workspace,
            include_diagram=False,
            allow_return=allow_return,
        )
    )
    history = result.semantic_validation
    assert history.return_count == int(allow_return)
    assert len(history.validations) == 1 + int(allow_return)
    assert len(feedbacks) == int(allow_return)
    assert all(
        not finding.missing_evidence for finding in history.validations[0].findings
    )
    if allow_return:
        assert feedbacks[0]["requests"][0]["correction"] is not None
        assert feedbacks[0]["requests"][0]["verdict"] == verdict
        assert history.validations[1].original_result == history.revised_architecture
        assert [stage for stage, action in hooks.events if action == "start"] == [
            "orientation",
            "architecture",
            "semantic_validation",
            "architecture",
            "semantic_validation",
        ]


def test_terminal_503_keeps_orientation_cause_and_skips_downstream_stages(
    tmp_path, capsys, monkeypatch
):
    from server.repository_runner import print_summary

    pipeline, snapshot, workspace, seen, hooks = setup_pipeline(tmp_path)
    events = []

    class ServerError(Exception):
        code = 503

    class Provider(OrientationSmokeModel):
        attempts = 0

        async def generate(self, prompt):
            self.attempts += 1
            if self.attempts > 1:
                raise ServerError("Unavailable")
            return await super().generate(prompt)

    provider = Provider()
    gateway = ModelGateway(provider, max_retries=2, backoff=0)
    for agent in (pipeline.orientation, pipeline.architect, pipeline.validator):
        agent.generate = gateway
    pipeline.on_event = lambda name, values: events.append(name)
    result = asyncio.run(
        pipeline.run(
            snapshot,
            budget=ExecutionBudget(
                max_total_tokens=200000,
                max_tokens_per_objective=100000,
                max_input_tokens_per_call=12000,
            ),
            workspace_root=workspace,
        )
    )
    assert provider.attempts == 4 and gateway.stopped
    assert len(seen) == 1  # Only orientation invoked an agent.
    assert [(stage.stage, stage.status) for stage in result.stages] == [
        ("orientation", "failed"),
        ("architecture", "skipped"),
        ("diagram_composition", "skipped"),
        ("semantic_validation", "skipped"),
    ]
    assert (
        "HTTP 503" in result.stages[0].reason
        and "3 attempt(s)" in result.stages[0].reason
    )
    assert result.orientation.telemetry.model_calls[-1].http_status == 503
    assert result.orientation.telemetry.model_calls[-1].error_type == "ServerError"
    assert "architecture_started" not in events and "architecture_skipped" in events
    assert (
        "semantic_validation_started" not in events
        and "semantic_validation_skipped" in events
    )
    assert hooks.events == [("orientation", "start"), ("orientation", "result")]
    assert [stage for stage, _ in hooks.skips] == [
        "architecture",
        "diagram_composition",
        "semantic_validation",
    ]
    assert (
        result.architecture.usage.model_calls
        == result.architecture.usage.tool_calls
        == 0
    )
    assert result.completion_status == "failed" and not result.usable
    data = result.architecture.model_dump(mode="json") | {
        "execution_mode": "architecture",
        "pipeline_status": result.completion_status,
        "pipeline_stages": [stage.model_dump(mode="json") for stage in result.stages],
        "orientation_result": result.orientation.model_dump(mode="json"),
    }
    print_summary(data)
    text = capsys.readouterr().out
    assert "Failed stage: orientation | Cause: Provider HTTP 503" in text
    assert "architecture: skipped" in text and "semantic_validation: skipped" in text
    assert "provider_unavailable" not in text
    import json

    from server import repository_runner
    from server.run_project_architecture import main

    monkeypatch.setattr(repository_runner, "create_model", lambda arguments: Provider())
    assert (
        main(
            [
                snapshot.repository.root_path,
                "--workspace-root",
                str(workspace),
                "--validate-semantics",
                "--quiet",
                "--json",
                "--retry-backoff",
                "0",
                "--max-total-tokens",
                "200000",
                "--max-objective-tokens",
                "100000",
                "--max-input-tokens",
                "12000",
                "--max-tokens",
                "3000",
            ]
        )
        == 1
    )
    exported = json.loads(capsys.readouterr().out)
    assert exported["pipeline_status"] == "failed"
    assert exported["pipeline_stages"][0]["stage"] == "orientation"
    assert "HTTP 503" in exported["pipeline_stages"][0]["reason"]
    assert exported["pipeline_stages"][1]["status"] == "skipped"
    assert (
        exported["orientation_result"]["telemetry"]["model_calls"][-1]["attempts"] == 3
    )


def test_orientation_provider_failure_does_not_stop_a_different_healthy_gateway(
    tmp_path,
):
    pipeline, snapshot, workspace, seen, _ = setup_pipeline(tmp_path)

    class ServerError(Exception):
        code = 503

    class Failing:
        async def generate(self, prompt):
            raise ServerError("Unavailable")

    pipeline.orientation.generate = ModelGateway(Failing(), max_retries=0)
    result = asyncio.run(
        pipeline.run(
            snapshot,
            budget=ExecutionBudget(
                max_total_tokens=200000,
                max_tokens_per_objective=100000,
                max_input_tokens_per_call=12000,
            ),
            workspace_root=workspace,
            allow_return=False,
        )
    )
    assert result.orientation.completion_status == "failed"
    assert (
        result.architecture.architecture is not None
        and result.semantic_validation is not None
    )
    assert len(seen) == 3 and result.stages[1].status != "skipped"


def test_pipeline_deadline_and_external_cancellation(tmp_path):
    pipeline, snapshot, workspace, seen, _ = setup_pipeline(tmp_path)
    with pytest.raises(TimeoutError):
        asyncio.run(
            pipeline.run(
                snapshot, budget=ExecutionBudget(), workspace_root=workspace, deadline=0
            )
        )
    assert not seen

    async def scenario():
        entered = asyncio.Event()

        class Waiting:
            async def run(self, tools):
                entered.set()
                await asyncio.sleep(3600)

        pipeline.orientation = Waiting()
        task = asyncio.create_task(
            pipeline.run(snapshot, budget=ExecutionBudget(), workspace_root=workspace)
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not seen

    asyncio.run(scenario())
