"""Offline oracle/protocol tests, not live LLM semantic accuracy measurements."""

import asyncio
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_finding_resolution as shared
from test_finding_resolution_evaluation import execute, verdict

from server.agents.finding_resolution import (
    FindingResolutionRequest,
    FindingResolutionResult,
)
from server.agents.finding_resolution.schemas import FindingVerificationResult
from server.contracts.audit import Consumption

finding = shared.finding
tools = shared.tools


@pytest.fixture
def scenarios(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "src" / "test-agents"))
    return importlib.import_module("run_finding_resolution_scenarios")


def test_comparison_is_by_id_status_not_order_reason_or_exact_citations(scenarios, finding, tools):
    findings = [finding, finding.model_copy(update={"id": "second"})]
    state, _, _ = execute(findings, tools, verdict)
    request = FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path, findings=findings)
    state["final_result"].results.reverse()
    state["final_result"].results[0] = state["final_result"].results[0].model_copy(
        update={"reason": "A different but nonempty explanation."})
    report = scenarios.compare_result(request, state, {"second": "persists", finding.id: "persists"})
    assert report["passed"] and len(report["matches"]) == 2
    assert report["consumption"] == state["consumption"].model_dump()
    mismatch = scenarios.compare_result(request, state, {"second": "resolved", finding.id: "persists"})
    assert not mismatch["passed"] and mismatch["discrepancies"][0]["finding_id"] == "second"


@pytest.mark.parametrize("invalid", ["blank_reason", "historical", "other_finding"])
def test_comparison_validates_reason_and_local_current_citations_separately(scenarios, finding, tools, invalid):
    findings = [finding, finding.model_copy(update={"id": "second"})]
    state, _, _ = execute(findings, tools, verdict)
    request = FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path, findings=findings)
    first, second = state["final_result"].results
    changes = {"reason": " "} if invalid == "blank_reason" else {
        "evidence_ids": finding.evidence_ids if invalid == "historical" else second.evidence_ids}
    state["final_result"].results[0] = first.model_copy(update=changes)
    report = scenarios.compare_result(request, state, {item.id: "persists" for item in findings})
    assert len(report["matches"]) == 2 and not report["discrepancies"] and not report["passed"]
    assert report["validation_errors"]


def test_all_34_patches_and_control_run_independently_and_preserve_oracle(scenarios, monkeypatch):
    suite = scenarios.DEFAULT_SUITE
    oracle_path = suite / "expected-results.json"
    original = oracle_path.read_bytes()
    oracle = json.loads(original)
    assert len(oracle["scenarios"]) == 34
    assert {row["patch"] for row in oracle["scenarios"]} == {
        path.relative_to(suite).as_posix() for path in (suite / "patches").glob("*.patch")}
    roots = []
    loader = scenarios.run.__globals__["load_findings"]

    async def offline_run(repository, findings_path, agent_config, output):
        roots.append(repository)
        assert Path(repository).is_dir() and Path(repository) != suite / "fixture_A"
        findings = loader(findings_path)
        request = FindingResolutionRequest(repository_path=repository, findings=findings)
        results = [FindingVerificationResult(finding_id=item.id, status="inconclusive",
            reason="Offline scenario execution does not adjudicate architecture.", evidence_ids=[]) for item in findings]
        state = {"final_result": FindingResolutionResult.model_validate({"results": results}, context={"request": request}),
            "investigations": [], "consumption": Consumption(), "termination_reason": "offline_test"}
        return request, state, SimpleNamespace(diagnostics=[{"node": "offline_test"}], traces=[])

    # Only patch application is real; no provider calls are made.
    monkeypatch.setattr(scenarios, "run", offline_run)
    reports = asyncio.run(scenarios.run_scenarios(suite, [], "unused"))["scenarios"]
    assert len(reports) == len(set(roots)) == 35
    assert all(len(report["discrepancies"]) == 3 and report["consumption"]["model_calls"] == 0 for report in reports)
    assert [report["scenario"] for report in reports] == [oracle["control"], *oracle["scenarios"]]
    assert all(report["diagnostics"] == [{"node": "offline_test"}] for report in reports)
    assert oracle_path.read_bytes() == original


def test_unknown_scenario_is_rejected_before_running(scenarios):
    with pytest.raises(ValueError, match="Unknown scenarios"):
        asyncio.run(scenarios.run_scenarios(scenarios.DEFAULT_SUITE, ["not-a-scenario"], "unused"))


def test_different_valid_evidence_lists_do_not_change_status_comparison(scenarios, finding, tools):
    state, _, _ = execute(finding, tools, lambda context: verdict(context, "inconclusive"))
    request = FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path, findings=[finding])
    expected = {finding.id: "inconclusive"}
    assert state["final_result"].results[0].evidence_ids
    assert scenarios.compare_result(request, state, expected)["passed"]
    state["final_result"].results[0] = state["final_result"].results[0].model_copy(update={"evidence_ids": []})
    assert scenarios.compare_result(request, state, expected)["passed"]
