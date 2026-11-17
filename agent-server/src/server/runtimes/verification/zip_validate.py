"""Execute an already-built verification suite against a checkout — no LLM.

The create path produces the deliverable ZIP; this module runs that exact ZIP
against a disposable copy of the repository (or an immutable snapshot of a
target commit), and optionally against a corrected "green control" checkout,
so the same artefact handed to a developer can be validated before delivery.

The suite runner is stdlib-only; this module is offline apart from invoking
that runner in a subprocess. Any failure raises SuiteValidationError and is
never reported as a finding result.
"""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from server.runtimes.repository.git_snapshot import materialize_commit

from .tools.repo_copy import copy_repository
from .tools.sandbox import minimal_env
from .zip_pack import SuitePackError, safe_extract

SUMMARY_ACTION_CREATE = "create"
SUMMARY_ACTION_EXECUTE = "execute"
FILE_SCRIPT_ENTRY = ".tallercito/runner.py"
SUMMARY_REPORT = ".tallercito/results/report.json"
EXECUTION_VERIFIED = "VIOLATION_PRESENT"
EXECUTION_PASS = "INCONCLUSIVE"  # A pass at one checkout is inconclusive, never a proof of a fix.
EXECUTION_NOT_VERIFIED = "NOT_VERIFIABLE"

__all__ = [
    "EXECUTION_NOT_VERIFIED",
    "EXECUTION_PASS",
    "EXECUTION_VERIFIED",
    "SUMMARY_ACTION_CREATE",
    "SUMMARY_ACTION_EXECUTE",
    "SuiteValidationError",
    "validate_zip",
]


class SuiteValidationError(SuitePackError):
    """The suite could not be executed — never reported as a finding result."""


def _run_runner(root: Path, *, timeout_seconds: float, only: list[str] | None = None,
                install: bool = True) -> dict:
    entrypoint = root / FILE_SCRIPT_ENTRY
    if not entrypoint.is_file():
        raise SuiteValidationError(f"Suite runner is missing at {entrypoint}")
    argv = [sys.executable, str(entrypoint)]
    if not install:
        argv.append("--no-install")
    for group in only or []:
        argv.extend(["--only", group])
    try:
        completed = subprocess.run(argv, cwd=entrypoint.parent,
                                   capture_output=True, text=True, encoding="utf-8", errors="replace",
                                   env=minimal_env(root / "src", root), timeout=timeout_seconds, check=False)
    except subprocess.TimeoutExpired as error:
        raise SuiteValidationError(f"Runner exceeded {timeout_seconds}s") from error
    except OSError as error:
        raise SuiteValidationError(f"Could not launch the suite runner: {error}") from error
    report = root / SUMMARY_REPORT
    if not report.is_file():
        tail = (completed.stdout + "\n" + completed.stderr).strip()[-500:]
        raise SuiteValidationError(f"Runner did not produce {SUMMARY_REPORT} (exit {completed.returncode}): {tail}")
    try:
        return json.loads(report.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SuiteValidationError(f"Runner report is not valid JSON: {error}") from error


def _execute_on_copy(repo_path: Path, zip_path: Path, config, label: str,
                     target_commit: str | None = None, only: list[str] | None = None) -> tuple[dict, list[str]]:
    if not repo_path.is_dir():
        raise SuiteValidationError(f"Repository path does not exist: {repo_path}")
    work = Path(tempfile.mkdtemp(prefix=f"tallercito-{label}-"))
    try:
        resolved = None
        if target_commit:
            try:
                resolved = materialize_commit(repo_path, work, target_commit,
                    max_files=config.max_repo_copy_files, max_bytes=config.max_repo_copy_bytes)
            except (ValueError, OSError, subprocess.SubprocessError) as error:
                raise SuiteValidationError(str(error)) from error
            copy_report = {"files": sum(1 for path in work.rglob("*") if path.is_file())}
        else:
            copy_report = copy_repository(repo_path, work,
                                          max_files=config.max_repo_copy_files, max_bytes=config.max_repo_copy_bytes)
        try:
            safe_extract(zip_path, work)
        except SuitePackError as error:
            raise SuiteValidationError(str(error)) from error
        install = getattr(config, "auto_install_node_dependencies", True)
        allowance = config.max_test_run_seconds + (2 * getattr(config, "install_timeout_seconds", 240) if install else 0)
        report = _run_runner(work, timeout_seconds=allowance, only=only, install=install)
        if resolved:
            report["checkout_commit"] = resolved
            report["limitations"] = [note for note in report.get("limitations", [])
                                      if note != ".git metadata was not found; the checkout commit could not be verified."]
            report["limitations"].append("Executed an immutable Git-object snapshot of the verified target commit; uncommitted changes were excluded.")
        return report, copy_report.get("files") and [f"copied {copy_report['files']} files"] or []
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _group_of(verification: dict) -> str:
    return str(verification.get("group") or "other").strip().lower() or "other"


def _verification_entries(manifest: dict, baseline: dict, green: dict | None,
                          only: list[str] | None = None) -> list[dict]:
    source = manifest.get("verifications", [])
    if only:
        wanted = {item.strip().lower() for item in only}
        source = [item for item in source if _group_of(item) in wanted]
    generated_by = {item["verification_id"]: item.get("generated_by") for item in source}
    base_by_id = {item["verification_id"]: item for item in baseline.get("verifications", [])}
    green_by_id = {item["verification_id"]: item for item in (green or {}).get("verifications", [])}
    entries = []
    for verification in source:
        vid = verification["verification_id"]
        base_item = base_by_id.get(vid, {})
        entry = {
            "verification_id": vid,
            "rule_id": verification.get("rule_kind"),
            "condition": verification.get("condition"),
            "strategy": verification.get("strategy"),
            "covered_property": verification.get("covered_property"),
            "target_components": verification.get("target_components"),
            "generation_status": verification.get("generation_status", "generated"),
            "status": base_item.get("status", EXECUTION_NOT_VERIFIED),
            "summary": base_item.get("detail", ""),
            "generated_by": generated_by.get(vid),
        }
        if green is not None:
            green_item = green_by_id.get(vid, {})
            entry["green_status"] = green_item.get("status", EXECUTION_NOT_VERIFIED)
            entry["validated_red_green"] = (base_item.get("status") == EXECUTION_VERIFIED
                                            and (green_item.get("execution_passed") is True
                                                 or green_item.get("status") == "VERIFIED_FIXED"))
        entries.append(entry)
    return entries


def _overall(entries: list[dict], green: dict | None) -> str:
    if green is not None:
        validated = sum(1 for item in entries if item.get("validated_red_green"))
        failed = len(entries) - validated
        if validated and not failed:
            return "validated_red_green"
        if validated:
            return "partial"
        if any(item["status"] == "EXECUTION_ERROR" for item in entries):
            return "execution_error"
        return "not_verifiable"
    statuses = [item["status"] for item in entries]
    if any(s == "VIOLATION_PRESENT" for s in statuses):
        return "partial"  # Red side confirmed; green side not measured (no control checkout).
    if any(s == "EXECUTION_ERROR" for s in statuses):
        return "execution_error"
    if all(s == "NOT_VERIFIABLE" for s in statuses):
        return "not_verifiable"
    return "inconclusive"


def _validate_zip_snapshot(zip_path: Path, repo_path: Path, green_control_path: Path | None,
                           config, *, target_commit: str | None = None,
                           only: list[str] | None = None) -> dict:
    if not zip_path.is_file():
        raise SuiteValidationError(f"Suite ZIP does not exist yet: {zip_path}. Build the suite first.")
    with zipfile.ZipFile(zip_path) as archive:
        try:
            manifest = json.loads(archive.read(".tallercito/manifest.json"))
        except (KeyError, json.JSONDecodeError) as error:
            raise SuiteValidationError(f"Suite manifest missing or invalid: {error}") from error
    limitations = list(manifest.get("limitations", []))
    baseline, copy_notes = _execute_on_copy(repo_path, zip_path, config, "target", target_commit, only)
    limitations += baseline.get("limitations", []) + copy_notes
    green = None
    if green_control_path is not None:
        green, green_copy_notes = _execute_on_copy(green_control_path, zip_path, config, "green", None, only)
        limitations += green.get("limitations", []) + green_copy_notes
    entries = _verification_entries(manifest, baseline, green, only)
    overall = _overall(entries, green)
    limitations = list(dict.fromkeys(limitations))
    return {
        "action": SUMMARY_ACTION_EXECUTE,
        "suite_id": manifest.get("suite_id"),
        "suite_sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
        "baseline_commit": manifest.get("source_commit"),
        "target_commit": target_commit,
        "checkout_commit": baseline.get("checkout_commit"),
        "verifications": entries,
        "verification_results": entries,
        "validation_status": overall,
        "overall_status": baseline.get("overall_status"),
        "green_control": None if green is None else str(green_control_path),
        "selection": [item.strip().lower() for item in only] if only else ["all"],
        "groups_present": sorted({_group_of(item) for item in manifest.get("verifications", [])}),
        "limitations": limitations,
    }


def validate_zip(zip_path: Path, repo_path: Path, green_control_path: Path | None,
                 config, *, target_commit: str | None = None, only: list[str] | None = None) -> dict:
    """Freeze the suite bytes for this run; regeneration cannot change tests mid-execution."""
    if not zip_path.is_file():
        raise SuiteValidationError("Suite ZIP does not exist yet; create it first")
    with tempfile.TemporaryDirectory(prefix="tallercito-suite-") as temporary:
        snapshot = Path(temporary) / "suite.zip"
        shutil.copyfile(zip_path, snapshot)
        return _validate_zip_snapshot(snapshot, repo_path, green_control_path, config, target_commit=target_commit, only=only)
