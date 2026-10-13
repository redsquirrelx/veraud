import asyncio
import json
from types import SimpleNamespace

import pytest

from server.agents.analyzer.schemas import ProjectDescription
from server.agents.architect.schemas import ArchitectureDescription, ComponentInfo
from server.agents.models.base import Model
from server.api.schemas import ExecutionConfig
from server.benchmark.metrics import (
    automatic_scores,
    citation_valid,
    human_scores,
    judge_scores,
    path_scores,
    review_template,
    stability,
)
from server.benchmark.report import write_report
from server.benchmark.runner import DEFAULT_SUITE, load_suite, run_benchmark, run_case
from server.benchmark.schemas import BenchmarkCase
from server.benchmark.telemetry import MeasuredModel, call_metrics
from server.config.schemas import AgentSettings, ModelCredentials, ModelSettings


def case():
    return BenchmarkCase(
        id="fixture", repository="fixture", commit="a" * 40,
        kinds=["library"], primary_language="python", entrypoints=["a.py"],
        key_components=["a.py"],
        expected_facts=[{"id": "answer", "description": "Returns 42", "evidence": ["a.py:1"]}],
        judge_claims=[
            {"id": verdict, "observation": verdict, "evidence": ["a.py:1"], "verdict": verdict, "rationale": "Fixture label"}
            for verdict in ("supported", "contradicted", "unverifiable")
        ],
    )


class ScriptedModel(Model):
    def __init__(self, answers):
        super().__init__(ModelSettings(provider="groq", name="fixture", temperature=0, max_tokens=100), ModelCredentials(api_key="not-written"))
        self.answers = iter(answers)

    async def generate(self, message):
        value = next(self.answers)
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(content=json.dumps(value), usage_metadata={"input_tokens": 10, "output_tokens": 5})


class StubAgent:
    def __init__(self, settings, model, collection=None):
        self.settings, self.model, self._collection = settings, model, collection

    async def run(self, input_data):
        await self.model.generate("agent prompt")
        if self.settings.agent_id == "analyzer":
            return ProjectDescription(kind="library", summary="Returns 42", primary_language="python", entrypoints=["a.py"], key_components=["a.py"])
        return ArchitectureDescription(components=[ComponentInfo(path="a.py", responsibility="Returns 42")])


class StubService:
    def __init__(self, fail_analyzer=False):
        self.fail_analyzer = fail_analyzer

    def build_agent(self, agent_type, config):
        if agent_type == "analyzer":
            answers = [RuntimeError("secret provider detail") if self.fail_analyzer else {}]
        else:
            grade = lambda verdict: {"verdict": verdict, "reason": "Fixture", "evidence": ["a.py:1"]}
            answers = [{}] + [grade(verdict) for verdict in ("supported", "supported", "contradicted", "unverifiable")]
            if self.fail_analyzer:
                answers = [grade(verdict) for verdict in ("supported", "contradicted", "unverifiable")]
        return StubAgent(AgentSettings(agent_id=agent_type, timeout_seconds=2), ScriptedModel(answers)), 2


OPTIONS = {"max_files": 500, "max_depth": 8, "rounds": 3, "files_per_round": 8, "timeout": 2, "judge_timeout": 2, "input_price": 1, "output_price": 2, "request_interval": 0, "max_retries": 0, "retry_backoff": 0}


def test_partial_reference_does_not_treat_unlisted_components_as_wrong():
    scores = path_scores(["a", "b"], ["a"])
    assert scores["reference_recall"] == 1
    assert scores["precision"] is None
    assert path_scores(["a", "b"], ["a"], exhaustive=True)["precision"] == 0.5


def test_citations_check_bounds_and_repository_containment(tmp_path):
    (tmp_path / "a.py").write_text("return 42\n", encoding="utf-8")
    assert citation_valid(tmp_path, "a.py:1")
    assert not citation_valid(tmp_path, "a.py:2")
    assert not citation_valid(tmp_path, "../a.py")
    scores = automatic_scores(tmp_path, case(), {}, {})
    assert scores["kind_correct"] is False
    assert scores["language_correct"] is False
    assert scores["citation_validity"] is None


def test_judge_false_acceptance_and_missing_metrics():
    scores = judge_scores([
        {"expected": "supported", "predicted": "supported"},
        {"expected": "contradicted", "predicted": "supported"},
        {"expected": "unverifiable", "predicted": "unverifiable"},
    ])
    assert scores["accuracy"] == pytest.approx(2 / 3)
    assert scores["false_support_rate"] == 1
    assert scores["macro_f1"] == pytest.approx((2 / 3 + 0 + 1) / 3)
    assert judge_scores([])["accuracy"] is None


def test_usage_cost_and_provider_failure_do_not_leak_details():
    model = MeasuredModel(ScriptedModel([{}, RuntimeError("credential-secret")]))
    asyncio.run(model.generate("prompt"))
    assert call_metrics(model.calls, 1, 2)["cost_usd"] == pytest.approx(0.00002)
    with pytest.raises(RuntimeError):
        asyncio.run(model.generate("prompt"))
    metrics = call_metrics(model.calls, 1, 2)
    assert metrics["usage_calls"] == 1
    assert metrics["usage_complete"] is False
    assert metrics["cost_usd"] is None
    assert "credential-secret" not in json.dumps(model.calls)


def test_cancellation_is_recorded():
    class SlowModel(ScriptedModel):
        async def generate(self, message):
            await asyncio.Event().wait()

    model = MeasuredModel(SlowModel([]))
    async def run():
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(model.generate("prompt"), 0.01)
    asyncio.run(run())
    assert model.calls[0]["status"] == "cancelled"


def test_pipeline_and_labeled_judge_have_separate_measurements(tmp_path):
    (tmp_path / "a.py").write_text("return 42\n", encoding="utf-8")
    record = asyncio.run(run_case(StubService(), case(), {"root_path": str(tmp_path)}, 1, ExecutionConfig(), OPTIONS))
    assert record["pipeline_status"] == "completed"
    assert record["judge_calibration"]["accuracy"] == 1
    assert record["stages"]["judge"]["telemetry"]["calls"] == 1
    assert record["stages"]["judge_calibration"]["telemetry"]["calls"] == 3
    assert record["automatic"]["kind_correct"] is True
    assert "not-written" not in json.dumps(record)


def test_upstream_failure_still_calibrates_judge(tmp_path):
    (tmp_path / "a.py").write_text("return 42\n", encoding="utf-8")
    record = asyncio.run(run_case(StubService(fail_analyzer=True), case(), {"root_path": str(tmp_path)}, 1, ExecutionConfig(), OPTIONS))
    assert record["pipeline_status"] == "failed"
    assert record["stages"]["analyzer"]["status"] == "failed"
    assert record["stages"]["architect"]["status"] == "skipped"
    assert record["stages"]["judge"]["status"] == "skipped"
    assert record["judge_calibration"]["accuracy"] == 1
    assert stability([record, record])["pairs"] == 0


def test_review_is_bound_to_original_claims_and_artifact():
    record = {"run_id": "fixture-01", "analysis": {"summary": "Returns 42"}, "description": {}}
    template = review_template(record, case())
    review = template.model_copy(deep=True)
    assert human_scores(review, template)["support_rate"] is None
    review.claims[0].verdict = "supported"
    review.expected_facts[0].found = True
    assert human_scores(review, template)["expected_fact_recall"] == 1
    review.claims[0].claim = "Different claim"
    with pytest.raises(ValueError, match="claims were changed"):
        human_scores(review, template)


def test_full_offline_run_writes_recomputable_report(tmp_path, monkeypatch):
    from server.benchmark import runner

    root = tmp_path / "workspace" / "fixture"
    root.mkdir(parents=True)
    (root / "a.py").write_text("return 42\n", encoding="utf-8")
    suite_path = tmp_path / "suite.yaml"
    # JSON is a YAML subset.
    suite_path.write_text(json.dumps({"description": "Fixture", "cases": [case().model_dump()]}), encoding="utf-8")
    monkeypatch.setattr(runner, "validate_case", lambda workspace, reference: {"root_path": str(root), "input_sha256": "fixture-hash"})
    monkeypatch.setattr(runner, "AgentExecutionService", StubService)
    output = tmp_path / "output"
    asyncio.run(run_benchmark(suite_path, root.parent, output, [], 2, ExecutionConfig(), OPTIONS))
    report = write_report(output)
    assert report["summary"]["runs"] == 2
    assert report["summary"]["planned_runs"] == 2
    assert report["summary"]["judge_calibration"]["accuracy"] == 1
    assert report["summary"]["human_support_rate"] is None
    assert report["summary"]["stability"]["fixture"]["pairs"] == 1
    assert (output / "report.md").is_file()
    assert len(list((output / "reviews").glob("*.json"))) == 2


def test_workspace_suite_covers_all_judge_labels():
    suite = load_suite(DEFAULT_SUITE)
    assert len(suite.cases) == 6
    assert all({claim.verdict for claim in item.judge_claims} == {"supported", "contradicted", "unverifiable"} for item in suite.cases)
