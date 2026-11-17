"""Authoring-aware acceptance tests.

The generation loop may author the test via the LLM client (provider or
scripted), keep the deterministic templates as a fallback, and still never
touch production code. These tests pin behavioral outcomes for the failure
modes and the no-repair/test-can-fail-rigourously invariants.
"""

import asyncio
from pathlib import Path

from _synthetic_repo import FIXED, VIOLATING

from server.agents.finding_test_generation.agent import FindingTestGenerationAgent
from server.agents.finding_test_generation.config import FindingTestConfig
from server.agents.finding_test_generation.llm_client import ScriptedLLMClient
from server.agents.finding_test_generation.schemas import FindingTestGenerationRequest

FIXTURE = Path(__file__).resolve().parents[5] / "fixtures" / "audit_140" / "findings.json"


def _write_repo(root: Path, overrides: dict[str, str]) -> None:
    for relative, content in {**VIOLATING, **overrides}.items():
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")


def _request(repo: Path, output: Path):
    return FindingTestGenerationRequest(findings_path=str(FIXTURE), repo_path=str(repo), output_path=str(output))


def test_fixed_fixture_all_green_after_run(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo, FIXED)
    config = FindingTestConfig(allow_local_unsafe_execution=True)
    agent = FindingTestGenerationAgent(config=config)

    result = asyncio.run(agent.run(_request(repo, tmp_path / "out")))
    assert result.ok is True
    statuses = {item.verification_id: item.status for item in result.verification_results}
    # A pass at the fixed fixture proves nothing by itself (no discrimination
    # evidence was bundled); INCONCLUSIVE is the only honest status.
    assert statuses == {f"verification-00{i}": "INCONCLUSIVE" for i in range(1, 7)}
    assert result.validation_status == "partial"


def test_null_sandbox_blocks_execution_but_packages(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo, {})
    config = FindingTestConfig()  # allow_local_unsafe_execution defaults to False
    agent = FindingTestGenerationAgent(config=config)

    result = asyncio.run(agent.run(_request(repo, tmp_path / "out")))
    assert result.ok is True
    assert result.validation_status == "environment_blocked"
    assert any("Local execution is disabled" in limitation for limitation in result.limitations)
    assert result.output_zip and Path(result.output_zip).is_file()
    # The audited repository is untouched by the blocked run.
    assert not (repo / ".tallercito").exists()


def test_scripted_client_can_select_and_author(tmp_path):
    """A scripted client ships pre-baked tests and exercises the full accept loop."""
    from server.agents.finding_test_generation.llm_client import (
        ScriptedLLMClient as _Client,
    )

    for _name in ("select_rule", "generate_test", "repair_test", "plan_verifications"):
        assert hasattr(_Client, _name), f"ScriptedLLMClient must expose {_name}"

    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo, {})
    client = ScriptedLLMClient()
    config = FindingTestConfig(allow_local_unsafe_execution=True)
    agent = FindingTestGenerationAgent(config=config, llm_client=client)

    result = asyncio.run(agent.run(_request(repo, tmp_path / "out")))
    assert result.ok is True
    called_nodes = {call["node"] for call in client.calls}
    assert "select_rule" in called_nodes


def test_technical_failure_is_not_repaired(tmp_path):
    """A rendered test that fails for non-violation reasons stays EXECUTION_ERROR.

    verification-005 probes ``assess`` implementations; deleting the module makes
    the rendered test fail its own precondition. Nothing retries or rewrites it.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo, {})
    target = repo / "src/urbanmesh/domain/policies/quality.py"
    assert target.is_file()
    target.unlink()
    config = FindingTestConfig(allow_local_unsafe_execution=True)
    agent = FindingTestGenerationAgent(config=config)

    result = asyncio.run(agent.run(_request(repo, tmp_path / "out")))
    assert result.ok is True
    by_id = {item.verification_id: item for item in result.verification_results}
    assert by_id["verification-005"].status == "EXECUTION_ERROR"
    records = {record.verification_id: record for record in result.validation_records}
    assert records["verification-005"].status == "environment_blocked"
    assert any("never repaired" in limitation for limitation in result.limitations)



def test_workspace_escape_is_blocked(tmp_path):
    from server.runtimes.verification.tools.repo_reader import PathSafetyError
    from server.runtimes.verification.tools.workspace_writer import (
        WorkspaceWriter,
    )

    writer = WorkspaceWriter(str(tmp_path), max_test_file_bytes=1024, max_written_bytes=4096)
    with __import__('pytest').raises(PathSafetyError):
        writer.write_test_file("../escape.py", "content")
    assert not (tmp_path.parent / "escape.py").exists()


def test_run_leaves_no_artifacts_in_repo(tmp_path):
    """After a run, the audited repository itself is never touched."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo, {})
    config = FindingTestConfig(allow_local_unsafe_execution=True)
    agent = FindingTestGenerationAgent(config=config)

    result = asyncio.run(agent.run(_request(repo, tmp_path / "out")))
    assert result.ok is True
    assert not (repo / ".tallercito").exists()


def test_tool_call_budget_exhaustion_downgrades_to_diagnosis(tmp_path):
    """Per-verification tool-call budget is enforced and reported as diagnosis."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo, {})
    config = FindingTestConfig(allow_local_unsafe_execution=True, max_tool_calls_per_verification=1)
    agent = FindingTestGenerationAgent(config=config)

    result = asyncio.run(agent.run(_request(repo, tmp_path / "out")))
    assert result.ok is True  # packaging still produces an artifact
    assert result.validation_status in {"partial", "invalid", "environment_blocked"}
    assert any("budget" in limitation.lower() for limitation in result.limitations)
    stats = {item.verification_id: item.status for item in result.verification_results}
    assert set(stats.values()) == {"EXECUTION_ERROR"}
