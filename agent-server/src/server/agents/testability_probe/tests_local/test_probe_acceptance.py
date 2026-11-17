"""Acceptance tests for the TestabilityProbeAgent (offline, scripted LLM)."""

import json
import zipfile
from pathlib import Path

import pytest
from _probe_fixture import (
    BROKEN_TEST,
    COMMIT,
    PLAN_REPLY,
    REPAIRED_TEST,
    VIOLATION_TEST,
    make_findings,
    make_repo,
)

from server.agents.testability_probe.agent import TestabilityProbeAgent
from server.agents.testability_probe.config import TestabilityProbeConfig
from server.agents.testability_probe.input_adapter import (
    load_probe_document,
    parse_probe_payload,
)
from server.agents.testability_probe.llm_client import ScriptedProbeLLMClient
from server.agents.testability_probe.schemas import ProbeRequest


def _repo_and_findings(tmp_path: Path):
    repo = make_repo(tmp_path / "repo")
    findings = make_findings(tmp_path / "findings.json")
    return repo, findings


def test_readme_loads():
    from server.agents.testability_probe.llm_client import load_prompt

    assert "planning" in load_prompt("plan_verification.md")


def test_input_adapter_parses_investigation_export(tmp_path):
    findings = make_findings(tmp_path / "findings.json")
    document, diagnostics = load_probe_document(findings)
    assert diagnostics.ok
    assert document is not None
    assert document.repository_id == "synthetic-repo"
    assert document.commit == COMMIT
    assert len(document.findings) == 1
    assert document.findings[0].evidence[0].path == "src/syntheticproj/mod.py"


def test_input_adapter_rejects_audit_export(tmp_path):
    payload = {"auditId": 140, "commitHash": COMMIT, "attributes": [], "exportedAt": "2026-11-01T00:00:00Z",
               "findings": []}
    document, diagnostics = parse_probe_payload(payload)
    assert document is None
    assert not diagnostics.ok
    assert any("audit" in error for error in diagnostics.errors)


def test_input_adapter_empty_findings_is_valid(tmp_path):
    findings = make_findings(tmp_path / "findings.json", count=0)
    document, diagnostics = load_probe_document(findings)
    assert diagnostics.ok
    assert document is not None and document.findings == []


def test_cli_shim_exists():
    import ast

    shim = Path(__file__).resolve().parents[4] / "test-agents" / "run_testability_probe.py"
    assert shim.is_file()
    ast.parse(shim.read_text(encoding="utf-8"))


def test_empty_findings_finish_validly(tmp_path):
    repo = make_repo(tmp_path / "repo")
    findings = make_findings(tmp_path / "empty.json", count=0)
    llm = ScriptedProbeLLMClient()
    agent = TestabilityProbeAgent(TestabilityProbeConfig(max_model_calls=10), llm)
    request = ProbeRequest(findings_path=str(findings), repo_path=str(repo),
                           architecture_context_path=None, output_path=str(tmp_path / "out"))
    result = agent.run_sync(request)
    assert result.ok
    assert result.termination_reason == "no_findings"
    assert result.total_findings == 0
    assert result.verifications == []
    assert result.output_zip and Path(result.output_zip).is_file()
    with zipfile.ZipFile(result.output_zip) as archive:
        manifest = json.loads(archive.read(".tallercito/manifest.json"))
    assert manifest["verifications"] == []
    assert manifest["generator"] == "testability-probe"


def test_scripted_end_to_end_red_violation(tmp_path):
    repo, findings = _repo_and_findings(tmp_path)
    llm = ScriptedProbeLLMClient({
        "plan": [PLAN_REPLY],
        "generate": [f"```python\n{VIOLATION_TEST}```"],
        "evaluate": ['{"verdict": "violation_present", "reason": "AssertionError on the oracle confirms the direct wall-clock reference."}'],
    })
    agent = TestabilityProbeAgent(TestabilityProbeConfig(allow_local_unsafe_execution=True), llm)
    request = ProbeRequest(findings_path=str(findings), repo_path=str(repo),
                           architecture_context_path=None, output_path=str(tmp_path / "out"))
    result = agent.run_sync(request)
    assert result.ok
    assert result.termination_reason == "suite_packaged"
    assert len(result.verifications) == 1
    verdict = result.verifications[0]
    assert verdict.outcome == "violation_present"
    assert result.validation_records[0].status == "validated_red"
    assert result.output_zip and Path(result.output_zip).is_file()
    with zipfile.ZipFile(result.output_zip) as archive:
        manifest = json.loads(archive.read(".tallercito/manifest.json"))
        tests = [name for name in archive.namelist() if name.startswith(".tallercito/tests/")]
    assert len(manifest["verifications"]) == 1
    verification = manifest["verifications"][0]
    assert verification["finding_id"] == "barrier:clock-1"
    assert verification["generation_status"] == "validated_red"
    assert verification["language"] == "python"
    assert verification["framework"] == "pytest"
    assert tests == [verification["test_path"].replace("/", "/")] or tests == [f".tallercito/{verification['test_path']}"]


def test_technical_failure_is_repaired_once_then_kept(tmp_path):
    repo, findings = _repo_and_findings(tmp_path)
    llm = ScriptedProbeLLMClient({
        "plan": [PLAN_REPLY],
        "generate": [f"```python\n{BROKEN_TEST}```"],
        "repair": [f"```python\n{REPAIRED_TEST}```"],
        # The repaired test passes at the RED baseline, so its oracle cannot
        # distinguish the denounced condition; no LLM verdict is consumed.
    })
    agent = TestabilityProbeAgent(TestabilityProbeConfig(allow_local_unsafe_execution=True, max_repairs_per_verification=1), llm)
    request = ProbeRequest(findings_path=str(findings), repo_path=str(repo),
                           architecture_context_path=None, output_path=str(tmp_path / "out"))
    result = agent.run_sync(request)
    assert result.ok
    verdict = result.verifications[0]
    assert verdict.outcome == "invalid_test"
    repair_calls = [call for call in llm.calls if call["node"] == "repair"]
    assert len(repair_calls) == 1
    assert result.validation_records[0].attempts == 2


def test_trivial_test_is_rejected_without_execution(tmp_path):
    repo, findings = _repo_and_findings(tmp_path)
    trivial = "def test_mod_clock_dependency():\n    assert True\n"
    llm = ScriptedProbeLLMClient({
        "plan": [PLAN_REPLY],
        "generate": [f"```python\n{trivial}```"],
    })
    agent = TestabilityProbeAgent(TestabilityProbeConfig(allow_local_unsafe_execution=True), llm)
    request = ProbeRequest(findings_path=str(findings), repo_path=str(repo),
                           architecture_context_path=None, output_path=str(tmp_path / "out"))
    result = agent.run_sync(request)
    assert result.ok
    assert result.verifications[0].outcome == "invalid_test"
    assert result.validation_records[0].status == "invalid"
    with zipfile.ZipFile(result.output_zip) as archive:
        manifest = json.loads(archive.read(".tallercito/manifest.json"))
        assert len(manifest["verifications"]) == 1
        assert archive.read(".tallercito/" + manifest["verifications"][0]["test_path"]).decode().splitlines() == trivial.splitlines()


@pytest.mark.parametrize("initial,classification", [
    (REPAIRED_TEST, "pass"),
    ("def test_mod_clock_dependency():\n    assert True\n", "trivial"),
])
def test_presence_oracle_is_repaired_and_history_preserved(tmp_path, initial, classification):
    repo, findings = _repo_and_findings(tmp_path)
    llm = ScriptedProbeLLMClient({
        "plan": [PLAN_REPLY],
        "generate": [f"```python\n{initial}```"],
        "repair": [f"```python\n{VIOLATION_TEST}```"],
        "evaluate": ['{"verdict":"violation_present","reason":"The direct clock oracle fails."}'],
    })
    output = tmp_path / "out"
    result = TestabilityProbeAgent(TestabilityProbeConfig(
        allow_local_unsafe_execution=True, max_repairs_per_verification=1), llm).run_sync(
            ProbeRequest(findings_path=str(findings), repo_path=str(repo), output_path=str(output)))
    assert result.verifications[0].outcome == "violation_present"
    assert result.validation_records[0].attempts == 2
    candidates = json.loads((output / "candidates.json").read_text(encoding="utf-8"))
    assert candidates[0]["history"][0]["content"] == initial
    assert candidates[0]["history"][0]["classification"] == classification
    with zipfile.ZipFile(result.output_zip) as archive:
        manifest = json.loads(archive.read(".tallercito/manifest.json"))
        assert manifest["verifications"][0]["generation_status"] == "validated_red"


def test_repaired_oracle_passes_corrected_control_without_llm(tmp_path):
    from server.agents.testability_probe.validate import validate_zip

    repo, findings = _repo_and_findings(tmp_path)
    green = make_repo(tmp_path / "green")
    (green / "src/syntheticproj/mod.py").write_text(
        "def tag(clock):\n    return f'ts:{clock().isoformat()}'\n", encoding="utf-8")
    llm = ScriptedProbeLLMClient({
        "plan": [PLAN_REPLY], "generate": [f"```python\n{REPAIRED_TEST}```"],
        "repair": [f"```python\n{VIOLATION_TEST}```"],
        "evaluate": ['{"verdict":"violation_present","reason":"Direct clock dependency reached."}'],
    })
    config = TestabilityProbeConfig(allow_local_unsafe_execution=True)
    result = TestabilityProbeAgent(config, llm).run_sync(ProbeRequest(
        findings_path=str(findings), repo_path=str(repo), output_path=str(tmp_path / "out"),
        green_control_dir=str(green)))
    assert result.validation_records[0].status == "validated_red_green"
    calls_before = len(llm.calls)
    red_report = validate_zip(Path(result.output_zip), repo, green, config)
    green_report = validate_zip(Path(result.output_zip), green, None, config)
    assert red_report["verifications"][0]["status"] == "VIOLATION_PRESENT"
    assert red_report["verifications"][0]["validated_red_green"] is True
    assert green_report["verifications"][0]["status"] == "VERIFIED_FIXED"
    assert len(llm.calls) == calls_before


def test_repair_context_preserves_nested_assignment_target_structure(tmp_path):
    from server.agents.testability_probe.execution import TestabilityProbeExecution

    (tmp_path / "subject.py").write_text("def apply(config):\n    config.runtime['mode'] = 'test'\n", encoding="utf-8")
    context = TestabilityProbeExecution()._python_structure_context(str(tmp_path), ["subject.py"])
    assert "Subscript(value=Attribute(value=Name(id='config'" in context
    assert "attr='runtime'" in context


def test_repair_context_includes_relevant_function_beyond_head_excerpt(tmp_path):
    from server.agents.testability_probe.execution import TestabilityProbeExecution

    (tmp_path / "subject.py").write_text(
        "# unrelated prelude\n" * 1000 + "def execute(config):\n    config.runtime['mode'] = 'test'\n",
        encoding="utf-8")
    context = TestabilityProbeExecution()._python_structure_context(str(tmp_path), ["subject.py"], "execute")
    assert "def execute(config):" in context
    assert "config.runtime['mode'] = 'test'" in context


def test_packaged_suite_executes_without_llm(tmp_path):
    """The exported ZIP must re-run against another checkout without any LLM."""
    repo, findings = _repo_and_findings(tmp_path)
    llm = ScriptedProbeLLMClient({
        "plan": [PLAN_REPLY],
        "generate": [f"```python\n{VIOLATION_TEST}```"],
        "evaluate": ['{"verdict": "violation_present", "reason": "oracle failed as declared."}'],
    })
    agent = TestabilityProbeAgent(TestabilityProbeConfig(allow_local_unsafe_execution=True), llm)
    request = ProbeRequest(findings_path=str(findings), repo_path=str(repo),
                           architecture_context_path=None, output_path=str(tmp_path / "out"))
    result = agent.run_sync(request)
    assert result.output_zip

    from server.agents.testability_probe.validate import validate_zip

    report = validate_zip(Path(result.output_zip), Path(repo), None,
                          TestabilityProbeConfig(), target_commit=None)
    entries = report["verifications"]
    assert len(entries) == 1
    # The same RED test must fail on the audited commit when re-run LLM-free.
    assert entries[0]["status"] == "VIOLATION_PRESENT"


def test_budget_exhaustion_degrades_instead_of_fabricating(tmp_path):
    repo, findings = _repo_and_findings(tmp_path)

    class FailingClient(ScriptedProbeLLMClient):
        async def complete(self, node, prompt):
            raise RuntimeError("provider unavailable")

    agent = TestabilityProbeAgent(TestabilityProbeConfig(), FailingClient())
    request = ProbeRequest(findings_path=str(findings), repo_path=str(repo),
                           architecture_context_path=None, output_path=str(tmp_path / "out"))
    result = agent.run_sync(request)
    assert result.ok
    assert result.verifications == []
    assert result.metrics["planned_verifications"] == 0
    assert any("planning failed" in item for item in result.limitations)


def test_input_invalid_never_packages(tmp_path):
    agent = TestabilityProbeAgent(TestabilityProbeConfig(), ScriptedProbeLLMClient())
    request = ProbeRequest(findings_path=str(tmp_path / "missing.json"), repo_path=str(tmp_path),
                           architecture_context_path=None, output_path=str(tmp_path / "out"))
    result = agent.run_sync(request)
    assert not result.ok
    assert result.termination_reason == "input_invalid"
    assert result.output_zip is None
