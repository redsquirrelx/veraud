"""Independent provenance, calibrated coverage, recovery, and bounded coordination."""

import asyncio
import json

import pytest

from server.agents.project_architecture.schemas import (
    ArchitectureReport,
    ArchitectureResult,
)
from server.agents.project_semantic_validation import (
    ProjectSemanticValidationAgent,
    ValidationLimits,
)
from server.agents.project_semantic_validation.context import review_targets
from server.agents.project_semantic_validation.schemas import SemanticFinding
from server.agents.repository_runtime import (
    ExecutionBudget,
    RepositoryContext,
    RepositoryInput,
    RepositoryToolset,
)
from server.agents.repository_runtime.schemas import BudgetUsage
from server.agents.repository_runtime.telemetry import ExecutionTelemetry
from server.pipelines.semantic_validation import validate_architecture_pipeline
from server.services.repository_analysis import RepositoryAnalysisService


@pytest.fixture
def fixture(tmp_path):
    root = tmp_path / "workspace" / "selected"
    root.mkdir(parents=True)
    (root / "service.py").write_text(
        "from port import Repository\nclass Service:\n    def execute(self, repo: Repository):\n        return repo.load()\n",
        encoding="utf-8",
    )
    (root / "port.py").write_text(
        "class Repository:\n    def load(self):\n        raise NotImplementedError\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        "This is DEFINITELY globally hexagonal.", encoding="utf-8"
    )
    snapshot = RepositoryAnalysisService().analyze_sync(root)

    def tools(budget=None):
        return RepositoryToolset(
            RepositoryContext(
                snapshot=snapshot,
                input=RepositoryInput(
                    snapshot_hash=snapshot.repository.snapshot_hash,
                    budget=budget
                    or ExecutionBudget(
                        max_input_tokens_per_call=12000, max_tokens_per_objective=60000
                    ),
                ),
            ),
            workspace_root=root.parent,
        )

    architect_tools = tools()
    response = architect_tools.execute(
        "get_source_excerpt", {"path": "service.py"}, tool_call_id="architect-read"
    )
    source = next(source for source in snapshot.files if source.path == "service.py")
    original = ArchitectureResult(
        snapshot_hash=snapshot.repository.snapshot_hash,
        completion_status="partial",
        architecture=ArchitectureReport.model_validate(
            {
                "organization": [
                    {
                        "name": "Service",
                        "file_ids": [source.id],
                        "responsibility": {
                            "statement": "The service depends on the repository port.",
                            "scope": "service.py",
                            "status": "supported",
                            "evidence_ids": [response.evidence[0].id],
                        },
                    }
                ]
            }
        ),
        retrieved_evidence=response.evidence,
        inspected_file_ids=(source.id,),
        usage=BudgetUsage(),
        telemetry=ExecutionTelemetry(),
    )
    return tools, original


class ReviewingModel:
    def __init__(self, verdict="supported", *, forged=False, partial_invalid=False):
        self.verdict, self.forged, self.partial_invalid = (
            verdict,
            forged,
            partial_invalid,
        )
        self.prompts = []

    async def generate(self, prompt):
        self.prompts.append(str(prompt))
        data = json.loads(str(prompt).split("\nVALIDATION_DATA\n", 1)[1])
        if not data["source_evidence_ledger"]:
            return json.dumps(
                {
                    "tool_calls": [
                        {
                            "id": "read",
                            "name": "get_source_excerpt",
                            "arguments": {"path": "service.py"},
                        }
                    ]
                }
            )
        evidence = (
            [data["active_targets"][0]["claim"]["evidence_ids"][0]]
            if self.forged
            else [data["source_evidence_ledger"][0]["id"]]
        )
        findings = []
        for target in data["active_targets"]:
            finding = {
                "target_id": target["id"],
                "checked_statement": target["claim"]["statement"],
                "verdict": self.verdict,
                "reason": "Inspected service and its dependency declaration.",
                "counterevidence_check": "Checked the import and load call; they use the repository port rather than a concrete adapter.",
                "evidence_ids": evidence,
            }
            if self.verdict == "insufficient_evidence":
                finding["missing_evidence"] = [
                    {
                        "question": "Inspect the port contract and adapter binding.",
                        "paths": ["port.py"],
                    }
                ]
            if self.verdict in {"overstated", "contradicted"}:
                finding["correction"] = {
                    "statement": "The inspected service delegates loading through a port.",
                    "scope": "service.py",
                    "status": "supported",
                    "evidence_ids": evidence,
                }
            findings.append(finding)
        if self.partial_invalid and len(findings) > 1:
            findings[1]["target_id"] = "/invented"
        return json.dumps({"findings": findings})


@pytest.mark.parametrize(
    "verdict,overall",
    [
        ("supported", "accepted"),
        ("overstated", "revisions_needed"),
        ("contradicted", "revisions_needed"),
        ("insufficient_evidence", "needs_evidence"),
    ],
)
def test_verdicts_preserve_original_and_require_independent_source(
    fixture, verdict, overall
):
    tools, original = fixture
    before = original.model_dump_json()
    result = asyncio.run(
        ProjectSemanticValidationAgent(ReviewingModel(verdict)).run(tools(), original)
    )
    assert result.completion_status == "complete" and result.verdict == overall
    assert (
        result.original_result.model_dump_json() == before == original.model_dump_json()
    )
    assert len(result.report_hash) == 64
    assert result.findings[0].target_id == "/organization/0/responsibility"
    assert result.findings[0].evidence_ids[0] not in {
        record.id for record in original.retrieved_evidence
    }
    assert result.citations[0].path == "service.py"
    assert result.usage.model_calls == 2 and result.usage.tool_calls == 1


def test_architect_citations_cannot_be_reused_as_validator_evidence(fixture):
    tools, original = fixture
    result = asyncio.run(
        ProjectSemanticValidationAgent(ReviewingModel(forged=True)).run(
            tools(), original
        )
    )
    assert result.completion_status == "failed" and result.verdict == "inconclusive"
    assert result.pending_target_ids == ("/organization/0/responsibility",)
    assert result.execution_issues[-1].category == "invalid_findings"


def test_selection_and_partial_salvage_never_accept_unreviewed_claims(fixture):
    tools, original = fixture
    report = original.architecture.model_copy(
        update={"explanation": original.architecture.organization[0].responsibility}
    )
    original = original.model_copy(update={"architecture": report})
    result = asyncio.run(
        ProjectSemanticValidationAgent(
            ReviewingModel(), limits=ValidationLimits(max_claims=1)
        ).run(tools(), original)
    )
    assert result.verdict == "inconclusive" and result.completion_status == "partial"
    assert result.pending_target_ids == ("/explanation",)
    result = asyncio.run(
        ProjectSemanticValidationAgent(
            ReviewingModel(partial_invalid=True),
            limits=ValidationLimits(max_model_calls=2),
        ).run(tools(), original)
    )
    assert len(result.findings) == 1 and result.pending_target_ids == ("/explanation",)
    assert result.verdict != "accepted"


def test_selection_prioritizes_classification_before_responsibilities(fixture):
    tools, original = fixture
    classification = {
        "pattern": "Hexagonal",
        "assessment": {
            "statement": "A local ports-and-adapters pattern is plausible.",
            "scope": "service.py",
            "status": "hypothesis",
            "limitations": ["Adapter not inspected."],
        },
    }
    report = ArchitectureReport.model_validate(
        original.architecture.model_dump(mode="json")
        | {"closest_architecture": classification}
    )
    targets = review_targets(
        tools(), original.model_copy(update={"architecture": report})
    )
    assert targets[0].id == "/closest_architecture/assessment"
    assert targets[0].context["scope_kind"] == "local"


def test_snapshot_and_ledger_rejection_happens_before_model_call(fixture):
    tools, original = fixture
    model = ReviewingModel()
    agent = ProjectSemanticValidationAgent(model)
    with pytest.raises(ValueError, match="snapshot"):
        asyncio.run(
            agent.run(tools(), original.model_copy(update={"snapshot_hash": "0" * 64}))
        )
    reused = tools()
    reused.execute("list_files", {}, tool_call_id="previous-role")
    with pytest.raises(ValueError, match="fresh"):
        asyncio.run(agent.run(reused, original))
    assert not model.prompts


def test_strict_admission_and_external_cancellation(fixture):
    tools, original = fixture
    model = ReviewingModel()
    result = asyncio.run(
        ProjectSemanticValidationAgent(model).run(
            tools(ExecutionBudget(max_total_tokens=1000)), original
        )
    )
    assert result.usage.model_calls == 0 and result.usage.token_budget_exhausted
    assert not model.prompts

    async def scenario():
        entered = asyncio.Event()

        class Waiting:
            async def generate(self, prompt):
                entered.set()
                await asyncio.sleep(3600)

        task = asyncio.create_task(
            ProjectSemanticValidationAgent(Waiting()).run(tools(), original)
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_first_pipeline_review_ignores_token_budgets_but_revalidation_is_strict(
    fixture,
):
    tools, original = fixture
    events = []
    validator = ProjectSemanticValidationAgent(
        ReviewingModel("insufficient_evidence"),
        on_event=lambda name, values: events.append((name, values)),
    )

    class Architect:
        async def run(self, fresh, orientation, **kwargs):
            return original

    def fresh_tools():
        return tools(
            ExecutionBudget(
                max_total_tokens=1000,
                max_tokens_per_objective=1000,
                max_input_tokens_per_call=1000,
            )
        )

    pipeline = asyncio.run(
        validate_architecture_pipeline(
            original,
            validator=validator,
            architect=Architect(),
            fresh_tools=fresh_tools,
        )
    )
    first, second = pipeline.validations
    assert first.completion_status == "complete" and first.usage.model_calls == 2
    assert not first.usage.token_budget_exhausted
    assert any(name == "budget_advisory" for name, _ in events)
    assert second.completion_status == "failed" and second.usage.model_calls == 0
    assert second.usage.token_budget_exhausted
    assert pipeline.return_count == 1


def test_evidence_requests_cannot_target_documentation_or_neighbors(fixture):
    tools, original = fixture

    class Unsafe(ReviewingModel):
        async def generate(self, prompt):
            value = json.loads(await super().generate(prompt))
            for finding in value.get("findings", []):
                finding["missing_evidence"][0]["paths"] = [
                    "README.md",
                    "../neighbor/main.py",
                ]
            return json.dumps(value)

    result = asyncio.run(
        ProjectSemanticValidationAgent(Unsafe("insufficient_evidence")).run(
            tools(), original
        )
    )
    assert not result.findings and result.verdict == "inconclusive"


def test_no_evidence_is_not_contradiction_contract():
    with pytest.raises(ValueError, match="independently"):
        SemanticFinding(
            target_id="/explanation",
            verdict="contradicted",
            checked_statement="A source claim.",
            reason="Source missing.",
            counterevidence_check="No source was inspected.",
        )


def test_decisive_verdict_cannot_omit_literal_counterevidence_check():
    with pytest.raises(ValueError, match="counterevidence"):
        SemanticFinding(
            target_id="/explanation",
            verdict="supported",
            checked_statement="A source claim.",
            reason="The broad pattern fits.",
            evidence_ids=("read:1",),
        )


def test_provider_failure_preserves_previously_accepted_findings(fixture):
    tools, original = fixture
    original = original.model_copy(
        update={
            "architecture": original.architecture.model_copy(
                update={
                    "explanation": original.architecture.organization[0].responsibility
                }
            )
        }
    )

    class FailsLater(ReviewingModel):
        async def generate(self, prompt):
            if len(self.prompts) == 2:
                raise RuntimeError("Provider unavailable")
            return await super().generate(prompt)

    result = asyncio.run(
        ProjectSemanticValidationAgent(
            FailsLater(), limits=ValidationLimits(batch_size=1)
        ).run(tools(), original)
    )
    assert len(result.findings) == 1 and result.completion_status == "partial"
    assert result.pending_target_ids == ("/explanation",)
    assert result.execution_issues[-1].category == "RuntimeError"


def test_rejected_extra_finding_is_visible_even_when_all_targets_were_reviewed(fixture):
    tools, original = fixture

    class Extra(ReviewingModel):
        async def generate(self, prompt):
            value = json.loads(await super().generate(prompt))
            if value.get("findings"):
                value["findings"].append(
                    value["findings"][0] | {"target_id": "/invented"}
                )
            return json.dumps(value)

    result = asyncio.run(ProjectSemanticValidationAgent(Extra()).run(tools(), original))
    assert len(result.findings) == 1 and not result.pending_target_ids
    assert result.completion_status == "partial" and result.verdict == "inconclusive"
    assert result.execution_issues[-1].category == "invalid_findings"


def test_unrelated_inspected_source_cannot_replace_the_claims_cited_range(fixture):
    tools, original = fixture

    class Unrelated(ReviewingModel):
        async def generate(self, prompt):
            value = json.loads(await super().generate(prompt))
            for call in value.get("tool_calls", []):
                call["arguments"]["path"] = "port.py"
            return json.dumps(value)

    result = asyncio.run(
        ProjectSemanticValidationAgent(Unrelated()).run(tools(), original)
    )
    assert not result.findings and result.verdict == "inconclusive"
    assert "cited source" in result.execution_issues[-1].message


def test_finding_cannot_silently_review_a_different_statement(fixture):
    tools, original = fixture

    class DifferentStatement(ReviewingModel):
        async def generate(self, prompt):
            value = json.loads(await super().generate(prompt))
            for finding in value.get("findings", []):
                finding["checked_statement"] = "A different assertion about deployment."
            return json.dumps(value)

    result = asyncio.run(
        ProjectSemanticValidationAgent(DifferentStatement()).run(tools(), original)
    )
    assert not result.findings and result.pending_target_ids
    assert "exactly match" in result.execution_issues[-1].message


@pytest.mark.parametrize("revision", [False, True])
def test_summary_identifies_displayed_report_and_separates_certainty(
    fixture, capsys, revision
):
    from server.repository_runner import print_summary

    tools, original = fixture
    shown = original
    if revision:
        report = original.architecture.model_dump(mode="json")
        report["organization"][0]["responsibility"]["statement"] = (
            "Revised service responsibility."
        )
        shown = original.model_copy(
            update={"architecture": ArchitectureReport.model_validate(report)}
        )
    review = asyncio.run(
        ProjectSemanticValidationAgent(ReviewingModel("overstated")).run(tools(), shown)
    )
    data = original.model_dump(mode="json") | {
        "execution_mode": "architecture",
        "semantic_validation": {
            "original_architecture": original.model_dump(mode="json"),
            "revised_architecture": shown.model_dump(mode="json") if revision else None,
            "validations": [review.model_dump(mode="json")],
            "return_count": int(revision),
        },
    }
    print_summary(data)
    text = capsys.readouterr().out
    assert (
        f"Report shown: {'REVISED' if revision else 'ORIGINAL'} ARCHITECTURE REPORT"
        in text
    )
    assert "architect certainty: supported | semantic: overstated" in text
    assert "Final acceptance: not established" in text
    assert "Semantic review coverage: 1 of 1 claims" in text
    assert "Proposed correction (not automatically applied)" in text
    if revision:
        assert "Revised service responsibility." in text
        assert (
            original.architecture.organization[0].responsibility.statement not in text
        )
        assert "Original report: preserved in revision history" in text
    else:
        assert "Architect revision: not performed" in text


def test_summary_explains_partial_review_and_failed_revision(fixture, capsys):
    from server.repository_runner import print_summary

    tools, original = fixture
    review = asyncio.run(
        ProjectSemanticValidationAgent(ReviewingModel()).run(
            tools(ExecutionBudget(max_total_tokens=1000)), original
        )
    )
    failed = original.model_copy(
        update={"architecture": None, "completion_status": "failed"}
    )
    data = original.model_dump(mode="json") | {
        "execution_mode": "architecture",
        "semantic_validation": {
            "original_architecture": original.model_dump(mode="json"),
            "revised_architecture": failed.model_dump(mode="json"),
            "validations": [review.model_dump(mode="json")],
            "return_count": 1,
        },
    }
    print_summary(data)
    text = capsys.readouterr().out
    assert "Report shown: ORIGINAL ARCHITECTURE REPORT" in text
    assert "Revision generation: failed; produced no report" in text
    assert "Semantic review coverage: 0 of 1 claims" in text
    assert "Pending claim: /organization/0/responsibility" in text
    assert "Review issue: token_budget_exhausted" in text
    assert "architect certainty: supported | semantic: not reviewed" in text
    assert "Final acceptance: not established" in text


def test_summary_does_not_apply_original_review_to_unvalidated_revision(
    fixture, capsys
):
    from server.repository_runner import print_summary

    tools, original = fixture
    review = asyncio.run(
        ProjectSemanticValidationAgent(ReviewingModel()).run(tools(), original)
    )
    report = original.architecture.model_dump(mode="json")
    report["organization"][0]["responsibility"]["statement"] = "Unvalidated revision."
    revised = original.model_copy(
        update={"architecture": ArchitectureReport.model_validate(report)}
    )
    data = original.model_dump(mode="json") | {
        "execution_mode": "architecture",
        "semantic_validation": {
            "original_architecture": original.model_dump(mode="json"),
            "revised_architecture": revised.model_dump(mode="json"),
            "validations": [review.model_dump(mode="json")],
            "return_count": 1,
        },
    }
    print_summary(data)
    text = capsys.readouterr().out
    assert "Report shown: REVISED ARCHITECTURE REPORT" in text
    assert "Semantic revalidation: not performed" in text
    assert "Review details below concern the original report" in text
    assert "Final acceptance: not established" in text
    assert (
        "Unvalidated revision. (architect certainty: supported | semantic: not reviewed)"
        in text
    )


def test_pipeline_returns_once_preserves_history_and_revalidates(fixture):
    tools, original = fixture

    class Architect:
        def __init__(self):
            self.calls = []

        async def run(self, fresh, orientation, **kwargs):
            assert not fresh.retrieved_evidence
            self.calls.append(kwargs)
            return original

    architect = Architect()
    agent = ProjectSemanticValidationAgent(ReviewingModel("insufficient_evidence"))
    result = asyncio.run(
        validate_architecture_pipeline(
            original, validator=agent, architect=architect, fresh_tools=tools
        )
    )
    assert result.return_count == 1 and len(result.validations) == 2
    assert len(architect.calls) == 1
    assert (
        architect.calls[0]["feedback"]["requests"][0]["target_id"]
        == "/organization/0/responsibility"
    )
    assert result.original_architecture == original
    assert all(review.verdict == "needs_evidence" for review in result.validations)
    assert (
        result.validations[0].usage.model_calls
        == result.validations[1].usage.model_calls
        == 2
    )


def test_pipeline_does_not_return_for_decisive_findings(fixture):
    tools, original = fixture

    class Architect:
        async def run(self, *args, **kwargs):
            raise AssertionError("No evidence request, no return.")

    result = asyncio.run(
        validate_architecture_pipeline(
            original,
            validator=ProjectSemanticValidationAgent(ReviewingModel("contradicted")),
            architect=Architect(),
            fresh_tools=tools,
        )
    )
    assert (
        result.return_count == 0 and result.validations[0].verdict == "revisions_needed"
    )
