"""Validate a packaged probe suite against a checkout — never calls an LLM.

Shared implementation lives in ``server.runtimes.verification.zip_validate``.
"""

from pathlib import Path

from server.runtimes.verification import zip_validate

from .config import TestabilityProbeConfig

SUMMARY_ACTION_CREATE = zip_validate.SUMMARY_ACTION_CREATE
SUMMARY_ACTION_EXECUTE = zip_validate.SUMMARY_ACTION_EXECUTE
EXECUTION_VERIFIED = zip_validate.EXECUTION_VERIFIED
EXECUTION_PASS = zip_validate.EXECUTION_PASS
# Legacy alias: a pass at one checkout is reported as INCONCLUSIVE (never a proven fix).
EXECUTION_FIXED = zip_validate.EXECUTION_PASS
EXECUTION_NOT_VERIFIED = zip_validate.EXECUTION_NOT_VERIFIED

SuiteValidationError = zip_validate.SuiteValidationError


def validate_zip(zip_path: Path, repo_path: Path, green_control_path: Path | None,
                 config: TestabilityProbeConfig | None = None, *, target_commit: str | None = None,
                 only: list[str] | None = None) -> dict:
    """Freeze the suite bytes for this run; regeneration cannot change tests mid-execution."""
    return zip_validate.validate_zip(zip_path, repo_path, green_control_path,
                                     config or TestabilityProbeConfig(),
                                     target_commit=target_commit, only=only)


__all__ = [
    "EXECUTION_FIXED",
    "EXECUTION_NOT_VERIFIED",
    "EXECUTION_PASS",
    "EXECUTION_VERIFIED",
    "SUMMARY_ACTION_CREATE",
    "SUMMARY_ACTION_EXECUTE",
    "SuiteValidationError",
    "validate_zip",
]
