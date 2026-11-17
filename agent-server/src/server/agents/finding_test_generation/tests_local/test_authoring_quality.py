"""Regression checks for evidence-grounded authoring and bounded technical repair."""

import asyncio
import sys
from types import SimpleNamespace

from server.agents.finding_test_generation.config import FindingTestConfig
from server.agents.finding_test_generation.execution import (
    FindingTestGenerationExecution,
)
from server.agents.finding_test_generation.llm_client import (
    ProviderFindingLLMClient,
    ScriptedLLMClient,
)
from server.runtimes.verification.tools.sandbox import (
    LocalSubprocessExecutor,
    SandboxPlan,
    minimal_env,
)
from server.runtimes.verification.tools.test_runner import (
    CLASSIFICATION_TECHNICAL,
)


def test_author_receives_original_evidence_and_path_safe_instructions(tmp_path):
    client = object.__new__(ProviderFindingLLMClient)
    prompts = []

    async def invoke(prompt):
        prompts.append(prompt)
        return "```python\ndef test_property():\n    assert True\n```"

    client._invoke = invoke
    spec = SimpleNamespace(target_components=[], property="No storage deletion", title="Report deletes history",
                           rule_kind="contract_states", violation_oracle="suggestion", fixed_oracle="suggestion",
                           test_scenario_scope="report", test_name="test_property", language="python")
    asyncio.run(client.generate_test(spec, {"repo": str(tmp_path), "finding": {"description": "delete_before is forbidden"}}))
    assert "delete_before is forbidden" in prompts[0]
    assert "pathlib.Path(os.environ.get" in prompts[0]
    assert "exactly one function named test_property" in prompts[0]


def test_typescript_author_block_aligns_with_vitest_and_repo_root(tmp_path):
    client = object.__new__(ProviderFindingLLMClient)
    prompts = []

    async def invoke(prompt):
        prompts.append(prompt)
        return "```typescript\nimport { it, expect } from 'vitest';\nit('ok', () => { expect(true).toBe(true); });\n```"

    client._invoke = invoke
    spec = SimpleNamespace(target_components=["src/lib/foo.ts"], property="No forbidden import in scope",
                           title="Report emits side effects", rule_kind=None,
                           violation_oracle="", fixed_oracle="", test_scenario_scope="report",
                           test_name="test_ok", language="typescript")
    asyncio.run(client.generate_test(spec, {"repo": str(tmp_path)}))
    prompt = prompts[0]
    assert "vitest" in prompt
    assert "expect" in prompt and "it(" in prompt
    assert "process.env.TALLERCITO_REPO_ROOT" in prompt
    assert "pytest" not in prompt.lower()
    assert "python" not in prompt.lower()


def test_repair_prompt_names_typescript_error_and_inputs(tmp_path):
    client = object.__new__(ProviderFindingLLMClient)
    prompts = []

    async def invoke(prompt):
        prompts.append(prompt)
        return "```typescript\nconst good: number = 1;\n```"

    client._invoke = invoke
    spec = SimpleNamespace(target_components=["src/lib/foo.ts"], property="No forbidden import",
                           title="Test fails", rule_kind=None,
                           violation_oracle="", fixed_oracle="", test_scenario_scope="report",
                           test_name="test_ok", language="typescript")
    compiled_error = "C:/workspace/.tallercito/tests/test_foo.test.tsx:2:0: ERROR: Expected \"from\" but found \"import\""
    asyncio.run(client.repair_test(spec, "import x", compiled_error, {"repo": str(tmp_path)}))
    prompt = prompts[0]
    assert compiled_error in prompt
    assert "vitest" in prompt.lower()
    assert "Transform failed" not in prompt  # raw multi-page error output is forbidden; only the message matters
    assert "import `expect`" in prompt  # TS repair prompt asks for the vitest import



def test_llm_technical_failure_reaches_repair_and_stops_at_bound():
    client = ScriptedLLMClient(repair={"v1": ["def test_property():\n    assert 1 == 2\n"]})
    config = FindingTestConfig(max_repairs_per_verification=1)
    execution = FindingTestGenerationExecution(config, client)
    spec = SimpleNamespace(verification_id="v1")
    state = {"specs": [spec], "request": SimpleNamespace(repo_path="unused")}
    candidate = {"verification_id": "v1", "classification": CLASSIFICATION_TECHNICAL,
                 "generated_by": "llm", "content": "broken", "detail": "TypeError"}
    repaired = asyncio.run(execution._attempt_repair([candidate], None, config, state))
    assert repaired[0]["attempts"] == 1
    assert len(client.calls) == 1
    repaired[0]["classification"] = CLASSIFICATION_TECHNICAL
    asyncio.run(execution._attempt_repair(repaired, None, config, state))
    assert len(client.calls) == 1


def test_dependency_context_reads_real_local_symbols_without_importing(tmp_path):
    package = tmp_path / "src" / "sample"
    package.mkdir(parents=True)
    (package / "subject.py").write_text("from sample.port import Port\n", encoding="utf-8")
    (package / "port.py").write_text("raise RuntimeError('must not execute')\nclass Port: pass\n", encoding="utf-8")
    context = ProviderFindingLLMClient._dependency_context(str(tmp_path), "src/sample/subject.py")
    assert "class Port" in context
    assert ProviderFindingLLMClient._dependency_context(str(tmp_path), "../outside.py") == ""


def test_subprocess_non_utf8_output_does_not_crash_the_evaluation(tmp_path):
    outcome = LocalSubprocessExecutor().run(SandboxPlan(
        command=[sys.executable, "-c", "import os; os.write(1, bytes([151]))"], cwd=tmp_path,
        env=minimal_env(tmp_path, tmp_path), timeout_seconds=5, max_output_bytes=100))
    assert outcome.exit_code == 0
    assert outcome.stdout == "\ufffd"
