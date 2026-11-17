"""Validate an already-built portable verification suite against a checkout.

Thin wrapper kept for backwards compatibility; the implementation lives in
``server.runtimes.verification.zip_validate`` and is shared with the
testability probe's ZIP validation. This module never calls an LLM.
"""

from pathlib import Path

from server.runtimes.verification import zip_validate

from .config import FindingTestConfig

SUMMARY_ACTION_CREATE = zip_validate.SUMMARY_ACTION_CREATE
SUMMARY_ACTION_EXECUTE = zip_validate.SUMMARY_ACTION_EXECUTE
FILE_SCRIPT_ENTRY = zip_validate.FILE_SCRIPT_ENTRY
SUMMARY_REPORT = zip_validate.SUMMARY_REPORT
EXECUTION_VERIFIED = zip_validate.EXECUTION_VERIFIED
EXECUTION_PASS = zip_validate.EXECUTION_PASS
# Legacy alias: a pass at one checkout is reported as INCONCLUSIVE (never a proven fix).
EXECUTION_FIXED = zip_validate.EXECUTION_PASS
EXECUTION_NOT_VERIFIED = zip_validate.EXECUTION_NOT_VERIFIED


class ValidationError(zip_validate.SuiteValidationError):
    """Kept as a subclass for backwards compatibility with existing callers."""


def _safe_extract(zip_path: Path, destination: Path) -> None:
    from server.runtimes.verification.zip_pack import safe_extract

    try:
        safe_extract(zip_path, destination)
    except Exception as error:
        raise ValidationError(str(error)) from error


def validate_zip(zip_path: Path, repo_path: Path, green_control_path: Path | None,
                 config: FindingTestConfig | None = None, *, target_commit: str | None = None,
                 only: list[str] | None = None) -> dict:
    """Freeze the suite bytes for this run; regeneration cannot change tests mid-execution."""
    resolved = config or FindingTestConfig()
    try:
        return zip_validate.validate_zip(zip_path, repo_path, green_control_path, resolved,
                                         target_commit=target_commit, only=only)
    except zip_validate.SuiteValidationError as error:
        raise ValidationError(str(error)) from error


__all__ = [
    "EXECUTION_FIXED",
    "EXECUTION_NOT_VERIFIED",
    "EXECUTION_PASS",
    "EXECUTION_VERIFIED",
    "FILE_SCRIPT_ENTRY",
    "SUMMARY_ACTION_CREATE",
    "SUMMARY_ACTION_EXECUTE",
    "SUMMARY_REPORT",
    "ValidationError",
    "validate_zip",
]
