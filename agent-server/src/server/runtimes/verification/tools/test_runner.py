"""pytest execution inside the disposable copy + result classification."""

import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .sandbox import LocalSubprocessExecutor, SandboxPlan, minimal_env

CLASSIFICATION_PASS = "pass"                  # condition not observed (at RED baseline this is unexpected)
CLASSIFICATION_VIOLATION = "violation"        # assertion failed: the denunciated condition persists
CLASSIFICATION_TECHNICAL = "technical_failure"  # import/fixture/environment problem; never repaired
CLASSIFICATION_TIMEOUT = "timeout"
CLASSIFICATION_TRIVIAL = "trivial"            # assertion verifies nothing (empty, tautology or skip)
CLASSIFICATION_ERROR = "execution_error"

SKIP_PATTERNS = ("@pytest.mark.skip", "@pytest.mark.xfail", "pytest.skip(")
TAUTOLOGY_PATTERNS = ("assert True", "assert_true")


def trivial_reason(source: str | None) -> str | None:
    """Static check: does this test module verify anything at all?"""
    if not source or not source.strip():
        return "empty test module"
    if any(pattern in source for pattern in SKIP_PATTERNS):
        return "test module marks its checks as skip/xfail; the verification would never run"
    if "assert " not in source:
        return "no assertion found in the test module"
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped.startswith("assert "):
            continue
        if any(pattern in stripped for pattern in TAUTOLOGY_PATTERNS):
            return f"tautological assertion: {stripped}"
    return None


@dataclass
class TestRunOutcome:
    classification: str
    detail: str
    executor_available: bool
    exit_code: int | None = None
    timeout: bool = False
    tests: list[dict] = field(default_factory=list)


def _parse_junit(junit_path: Path) -> list[dict]:
    cases: list[dict] = []
    if not junit_path.is_file():
        return cases
    try:
        root = ET.parse(junit_path).getroot()
    except ET.ParseError:
        return cases
    for case in root.iter("testcase"):
        failure = case.find("failure")
        error = case.find("error")
        kind = "passed"
        message = ""
        if error is not None:
            kind = "error"
            message = ((error.get("message") or "") + "\n" + (error.text or "")).strip()[:2000]
        elif failure is not None:
            kind = "failed"
            message = ((failure.get("message") or "") + "\n" + (failure.text or "")).strip()[:2000]
        cases.append({"classname": case.get("classname"), "name": case.get("name"),
                      "kind": kind, "message": message})
    return cases


class WorkspaceRunner:
    """Runs pytest for one candidate test file inside the workspace copy."""

    def __init__(self, workspace_root: Path, *, executor, timeout_seconds: float = 120, max_output_bytes: int = 64_000):
        self.root = Path(workspace_root).resolve()
        self.executor = executor
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes

    def run_pytest(self, test_path: str) -> TestRunOutcome:
        """Executes `pytest <test_path>` inside the workspace; classifies the outcome."""

        if not isinstance(self.executor, LocalSubprocessExecutor):
            plan = SandboxPlan(command=[sys.executable, "-m", "pytest", test_path, "-q"],
                               cwd=self.root, env={}, timeout_seconds=self.timeout_seconds,
                               max_output_bytes=self.max_output_bytes)
            result = self.executor.run(plan)
            return TestRunOutcome(classification=CLASSIFICATION_ERROR,
                                  detail=result.reason or "No sandbox backend is available.",
                                  executor_available=result.available)
        junit_rel = Path(".tallercito") / "results" / "junit.xml"
        (self.root / junit_rel).parent.mkdir(parents=True, exist_ok=True)
        repo_src = self.root / "src"
        command = [sys.executable, "-m", "pytest", test_path, "-q", f"--junitxml={junit_rel.as_posix()}"]
        result = self.executor.run(SandboxPlan(
            command=command, cwd=self.root, env=minimal_env(repo_src, self.root),
            timeout_seconds=self.timeout_seconds, max_output_bytes=self.max_output_bytes))
        if result.timeout:
            return TestRunOutcome(classification=CLASSIFICATION_TIMEOUT,
                                  detail="pytest exceeded the configured timeout.",
                                  executor_available=True, timeout=True)
        if result.exit_code is None and result.reason:
            return TestRunOutcome(classification=CLASSIFICATION_ERROR, detail=result.reason,
                                  executor_available=result.available)
        cases = _parse_junit(self.root / junit_rel)
        if not cases:
            return TestRunOutcome(classification=CLASSIFICATION_TECHNICAL,
                                  detail="pytest produced no tests (collection failure or import error). " + (result.stderr or result.stdout)[:500],
                                  executor_available=True, exit_code=result.exit_code)
        first = cases[0]
        if first["kind"] == "passed":
            return TestRunOutcome(classification=CLASSIFICATION_PASS,
                                  detail="Test passed within the declared scope.",
                                  executor_available=True, exit_code=result.exit_code, tests=cases)
        if first["kind"] == "error":
            return TestRunOutcome(classification=CLASSIFICATION_TECHNICAL,
                                  detail=first["message"],
                                  executor_available=True, exit_code=result.exit_code, tests=cases)
        # Only an AssertionError proves the denunciated condition; any other exception means the test could not run.
        if "AssertionError" in first["message"]:
            return TestRunOutcome(classification=CLASSIFICATION_VIOLATION,
                                  detail=first["message"],
                                  executor_available=True, exit_code=result.exit_code, tests=cases)
        return TestRunOutcome(classification=CLASSIFICATION_TECHNICAL,
                              detail=first["message"],
                              executor_available=True, exit_code=result.exit_code, tests=cases)


__all__ = [
    "CLASSIFICATION_ERROR",
    "CLASSIFICATION_PASS",
    "CLASSIFICATION_TECHNICAL",
    "CLASSIFICATION_TIMEOUT",
    "CLASSIFICATION_TRIVIAL",
    "CLASSIFICATION_VIOLATION",
    "TestRunOutcome",
    "WorkspaceRunner",
    "trivial_reason",
]
