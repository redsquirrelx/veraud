"""Execution backends for candidate tests.

``NullSandbox`` is the default and rejects every execution: without a real
isolation boundary, generated code must not run on this machine.

``LocalSubprocessExecutor`` is a development escape hatch. It is NOT a security
sandbox: it runs pytest in a disposable copy of the audited repository on
this machine. It is intended only for trusted fixtures and local validation;
the caller must opt in explicitly via configuration.
"""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class SandboxResult:
    available: bool
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    timeout: bool = False
    reason: str | None = None


class SandboxExecutor(Protocol):
    def run(self, plan: "SandboxPlan") -> SandboxResult: ...


@dataclass
class SandboxPlan:
    command: list[str]
    cwd: Path
    env: dict[str, str]
    timeout_seconds: float
    max_output_bytes: int


class NullSandbox:
    """Default backend: execution is refused with an explicit reason."""

    def run(self, plan: SandboxPlan) -> SandboxResult:
        return SandboxResult(
            available=False,
            reason="No sandbox backend is configured. Enable allow_local_unsafe_execution for trusted local validation.",
        )


class LocalSubprocessExecutor:
    """Development escape hatch; explicitly NOT a security boundary."""

    def run(self, plan: SandboxPlan) -> SandboxResult:
        try:
            completed = subprocess.run(
                plan.command,
                cwd=str(plan.cwd),
                env=plan.env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=plan.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(available=True, timeout=True, reason="Execution exceeded the configured timeout.")
        except OSError as error:
            return SandboxResult(available=True, exit_code=-1, reason=f"Could not start pytest: {error}")

        def cap(data: str) -> str:
            if len(data.encode("utf-8", errors="replace")) > plan.max_output_bytes:
                return data.encode("utf-8", errors="replace")[: plan.max_output_bytes].decode("utf-8", errors="replace")
            return data

        return SandboxResult(
            available=True,
            exit_code=completed.returncode,
            stdout=cap(completed.stdout),
            stderr=cap(completed.stderr),
        )


def minimal_env(repo_src: Path, repo_root: Path) -> dict[str, str]:
    """Environment for the child pytest: no host secrets, just what Python needs."""

    path_value = os.environ.get("PATH", "")
    env = {"PATH": path_value, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "TALLERCITO_REPO_ROOT": str(repo_root)}
    pythonpath = str(repo_src) if repo_src.is_dir() else str(repo_root)
    env["PYTHONPATH"] = pythonpath
    if os.name == "nt":
        for variable in ("SystemRoot", "SystemDrive", "TEMP", "TMP"):
            if variable in os.environ:
                env[variable] = os.environ[variable]
    return env
