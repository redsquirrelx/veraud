"""Offline patch-runner tests; scripted statuses are not LLM accuracy results."""

import asyncio
import csv
import hashlib
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_finding_resolution as shared

from server.agents.finding_resolution import (
    FindingResolutionRequest,
    FindingResolutionResult,
)
from server.agents.finding_resolution.schemas import FindingVerificationResult
from server.contracts.audit import Consumption, EvidenceReference

finding = shared.finding


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "src" / "test-agents"))
    return importlib.import_module("run_finding_resolution_patch_suite")


def make_suite(tmp_path, finding, count=1):
    suite = tmp_path / "suite"
    fixture = suite / "fixture_A"
    fixture.mkdir(parents=True)
    (fixture / "service.py").write_text("def use(): return 1\n", encoding="utf-8")
    (suite / "findings.json").write_text(json.dumps({"findings": [finding.model_dump(mode="json")]}), encoding="utf-8")
    patches = suite / "patches"
    patches.mkdir()
    control = {"id": "000-baseline", "title": "Control", "patch": None, "expected": {finding.id: "inconclusive"}}
    scenarios = []
    for index in range(count):
        patch = patches / f"{index + 1:03}.patch"
        patch.write_text("--- a/service.py\n+++ b/service.py\n@@ -1 +1 @@\n-def use(): return 1\n"
            f"+def use(): return {index + 2}\n", encoding="utf-8")
        scenarios.append({"id": f"{index + 1:03}", "title": f"Patch {index + 1}",
            "patch": patch.relative_to(suite).as_posix(), "expected": {finding.id: "resolved"},
            "patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest(), "custom_metadata": {"keep": index}})
    oracle = {"schema_version": 2, "custom_suite_metadata": ["preserve"], "expected_ids": [finding.id],
        "control": control, "scenarios": scenarios}
    (suite / "expected-results.json").write_text(json.dumps(oracle), encoding="utf-8")
    return suite, oracle


def tree_hash(directory):
    return {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in directory.rglob("*") if path.is_file()}


def offline_result(runner, repository, findings_path):
    request = FindingResolutionRequest(repository_path=repository, findings=runner.load_findings(findings_path))
    results = [FindingVerificationResult(finding_id=item.id, status="inconclusive",
        reason="Offline protocol test has not evaluated this finding.", evidence_ids=[]) for item in request.findings]
    state = {"final_result": FindingResolutionResult.model_validate({"results": results}, context={"request": request}),
        "investigations": [], "limitations": [], "termination_reason": "offline_test",
        "consumption": Consumption(model_calls=2, tool_calls=1, accounted_tokens=120, estimated_tokens=10)}
    return request, state, SimpleNamespace(diagnostics=[{"node": "offline_test"}], traces=[])


def test_isolated_patches_immediate_progress_reports_and_metadata(runner, finding, tmp_path, monkeypatch, capsys):
    suite, oracle = make_suite(tmp_path, finding, count=2)
    before = tree_hash(suite)
    roots, contents = [], []
    directory = tmp_path / "reports"

    async def fake_run(repository, findings_path, agent_config, output):
        assert output is None and agent_config == "test-config"
        assert Path(findings_path) == suite / "findings.json"
        assert not (Path(repository) / ".git").exists()
        if roots:
            saved = json.loads((directory / "report.json").read_text(encoding="utf-8"))
            assert len(saved["scenarios"]) == len(roots)
            # A previous result is visible before the next model execution.
            assert "Exactitud de estados" in capsys.readouterr().out
        roots.append(repository)
        contents.append((Path(repository) / "service.py").read_text(encoding="utf-8"))
        request, state, capture = offline_result(runner, repository, findings_path)
        digest = hashlib.sha256(contents[-1].encode()).hexdigest()
        reference = EvidenceReference(id="current", snapshot_hash=digest, commit=None, path="service.py",
            file_id="file-current", content_hash=digest, kind="source", start_line=1, end_line=1, tool_call_id="read")
        state["final_result"].results[0] = state["final_result"].results[0].model_copy(update={"evidence_ids": [reference.id]})
        state["investigations"] = [SimpleNamespace(finding_id=finding.id, evidence=[reference],
            tool_results=[SimpleNamespace(evidence=[reference], snapshot_hash=digest)], consumption=state["consumption"])]
        return request, state, capture

    monkeypatch.setattr(runner, "run", fake_run)
    report = asyncio.run(runner.run_suite(suite, findings=suite / "findings.json", agent_config="test-config", report_dir=directory))
    assert report["oracle"] == oracle
    assert [item["outcome"] for item in report["scenarios"]] == ["passed", "discrepancy", "discrepancy"]
    assert len(set(roots)) == 3 and all(not Path(root).exists() for root in roots)
    assert contents == [f"def use(): return {number}\n" for number in (1, 2, 3)]
    assert before == tree_hash(suite)
    assert report["summary"]["consumption"]["accounted_tokens"] == 360
    assert report["summary"]["status_accuracy"] == pytest.approx(1 / 3)
    assert report["scenarios"][0]["diagnostics"] == [{"node": "offline_test"}]
    with (directory / "report.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 3 and rows[0]["actual"] == "inconclusive"
    assert rows[0]["reason"] and json.loads(rows[0]["evidence_ids"]) == ["current"]
    assert json.loads(rows[0]["evidence"])[0]["path"] == "service.py"
    assert rows[0]["scenario_accounted_tokens"] == "120"


def test_patch_and_agent_errors_are_distinct_and_do_not_stop_later_scenarios(runner, finding, tmp_path, monkeypatch):
    suite, oracle = make_suite(tmp_path, finding, count=3)
    # A valid hash with invalid patch syntax must fail in git apply, not the agent.
    invalid = suite / "patches" / "001.patch"
    invalid.write_text("invalid patch", encoding="utf-8")
    oracle["scenarios"][0]["patch_sha256"] = hashlib.sha256(invalid.read_bytes()).hexdigest()
    (suite / "expected-results.json").write_text(json.dumps(oracle), encoding="utf-8")
    before = tree_hash(suite)
    seen = []

    async def fake_run(repository, findings_path, agent_config, output):
        text = (Path(repository) / "service.py").read_text(encoding="utf-8")
        seen.append(text)
        if "return 3" in text:
            raise RuntimeError("private provider response: secret-must-not-be-exported")
        return offline_result(runner, repository, findings_path)

    monkeypatch.setattr(runner, "run", fake_run)
    directory = tmp_path / "reports"
    report = asyncio.run(runner.run_suite(suite, findings=suite / "findings.json", report_dir=directory))
    assert [item["outcome"] for item in report["scenarios"]] == ["passed", "patch_error", "agent_error", "discrepancy"]
    assert report["scenarios"][1]["patch_returncode"] != 0
    assert len(seen) == 3 and "return 4" in seen[-1] and before == tree_hash(suite)
    assert report["summary"]["usage_unavailable"] == 2
    assert "secret-must-not-be-exported" not in (directory / "report.json").read_text(encoding="utf-8")


def test_validation_error_is_separate_from_status_matches(runner, finding, tmp_path, monkeypatch):
    suite, _ = make_suite(tmp_path, finding)

    async def fake_run(repository, findings_path, agent_config, output):
        request, state, capture = offline_result(runner, repository, findings_path)
        state["final_result"].results[0] = state["final_result"].results[0].model_copy(
            update={"evidence_ids": ["historical-evidence"], "reason": " "})
        return request, state, capture

    monkeypatch.setattr(runner, "run", fake_run)
    report = asyncio.run(runner.run_suite(suite, findings=suite / "findings.json",
        selected=["000-baseline"], report_dir=tmp_path / "reports"))
    result = report["scenarios"][0]
    assert result["outcome"] == "validation_error" and result["status_accuracy"] == 1
    assert {item["rule"] for item in result["validation_errors"]} >= {
        "nonempty_reason", "finding_local_current_evidence_ids"}


def test_selection_always_includes_control_and_uses_suite_findings(runner, finding, tmp_path, capsys):
    suite, oracle = make_suite(tmp_path, finding, count=2)
    loaded, chosen, findings, _ = runner.load_suite(suite, None, ["002"])
    assert loaded == oracle and [item["id"] for item in chosen] == ["000-baseline", "002"]
    assert findings == suite / "findings.json"
    assert "Aviso" not in capsys.readouterr().out
    assert runner.DEFAULT_FINDINGS == runner.DEFAULT_SUITE / "findings.json"
    with pytest.raises(FileNotFoundError):
        runner.load_suite(suite, tmp_path / "explicitly-missing.json", [])
    with pytest.raises(ValueError, match="Unknown scenarios"):
        runner.load_suite(suite, findings, ["unknown"])


def test_real_oracle_all_34_patches_preserve_metadata_without_rewriting(runner):
    suite = runner.DEFAULT_SUITE
    original = tree_hash(suite)
    oracle, scenarios, _, _ = runner.load_suite(suite, suite / "findings.json", [])
    assert len(scenarios) == 35 and len(oracle["scenarios"]) == 34
    assert all("patch_sha256" in item and "verification" in item and "rationale" in item for item in scenarios[1:])
    assert original == tree_hash(suite)


def test_reports_cannot_overwrite_original_fixture(runner, finding, tmp_path):
    suite, _ = make_suite(tmp_path, finding)
    with pytest.raises(ValueError, match="outside the original fixture"):
        asyncio.run(runner.run_suite(suite, report_dir=suite / "fixture_A"))


@pytest.mark.parametrize("passed,code", [(True, 0), (False, 1)])
def test_cli_selection_paths_and_exit_status(runner, tmp_path, monkeypatch, passed, code):
    seen = {}

    async def fake_suite(suite, **kwargs):
        seen.update(suite=suite, **kwargs)
        return {"scenarios": [{"outcome": "passed" if passed else "discrepancy"}]}

    monkeypatch.setattr(runner, "run_suite", fake_suite)
    monkeypatch.setattr("sys.argv", ["patch-suite", "--suite", str(tmp_path), "--findings", str(tmp_path / "findings.json"),
        "--scenario", "001", "002", "--scenario", "003", "--report-dir", str(tmp_path / "reports")])
    assert runner.main() == code
    assert seen["selected"] == ["001", "002", "003"] and seen["suite"] == tmp_path
    assert seen["findings"] == tmp_path / "findings.json"
