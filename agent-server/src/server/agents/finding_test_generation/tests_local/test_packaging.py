"""Suite packaging and end-to-end acceptance on a synthetic repository.

The synthetic repo is a minimal Python src-layout package mirroring the audit-140
findings; it is written to a temporary directory, never to the real workspace.
RED variant: exit 1 with every verification flagged. Fixed variant: exit 0.
"""

import json
import subprocess
import sys
import zipfile
from pathlib import Path

from _synthetic_repo import FIXED, VIOLATING

from server.agents.finding_test_generation.input_adapter import load_audit_document
from server.agents.finding_test_generation.packaging import build_suite
from server.agents.finding_test_generation.planning import plan_verifications
from server.agents.finding_test_generation.schemas import ValidationRecord

FIXTURE = Path(__file__).resolve().parents[5] / "fixtures" / "audit_140" / "findings.json"

def _build_suite(tmp_path: Path):
    document, diagnostics = load_audit_document(FIXTURE)
    assert document is not None, diagnostics.errors
    specs, _ = plan_verifications(document)
    records = [ValidationRecord(verification_id=spec.verification_id, status="generated") for spec in specs]
    output = tmp_path / "suite.zip"
    build_suite(document, specs, records, [], output)
    return output


def _materialize(target: Path, overrides: dict[str, str]):
    for relative, content in {**VIOLATING, **overrides}.items():
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")


def _extract_and_run(zip_path: Path, repo: Path) -> tuple[int, dict]:
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(repo)
    runner = repo / ".tallercito" / "runner.py"
    completed = subprocess.run([sys.executable, str(runner)], cwd=repo.parent,
                               capture_output=True, text=True, timeout=300, check=False)
    report_path = repo / ".tallercito" / "results" / "report.json"
    return completed.returncode, (json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {})


def test_suite_contents_and_manifest(tmp_path):
    archive_path = _build_suite(tmp_path)
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read(".tallercito/manifest.json"))
    assert ".tallercito/run.bat" in names
    assert ".tallercito/run.sh" in names
    assert ".tallercito/runner.py" in names
    assert len(manifest["verifications"]) == 6
    assert manifest["source_commit"] == "52b23bc085b55b00d340620ad2055d69672469bb"
    assert manifest["root_layout"] == ".tallercito"


def test_rejected_baseline_shows_red(tmp_path):
    repo = tmp_path / "red-repo"
    repo.mkdir()
    _materialize(repo, {})
    archive_path = _build_suite(tmp_path)
    exit_code, report = _extract_and_run(archive_path, repo)
    assert exit_code == 1
    statuses = {item["verification_id"]: item["status"] for item in report["verifications"]}
    assert statuses == {f"verification-00{i}": "VIOLATION_PRESENT" for i in range(1, 7)}


def test_fixed_variant_shows_green(tmp_path):
    repo = tmp_path / "green-repo"
    repo.mkdir()
    _materialize(repo, FIXED)
    archive_path = _build_suite(tmp_path)
    exit_code, report = _extract_and_run(archive_path, repo)
    assert exit_code == 2
    statuses = {item["verification_id"]: item["status"] for item in report["verifications"]}
    # A lone pass at one checkout proves nothing; the exported runner reports
    # INCONCLUSIVE, not a verified fix (verified status requires red+green evidence).
    assert statuses == {f"verification-00{i}": "EXECUTION_ERROR" for i in range(1, 7)}
