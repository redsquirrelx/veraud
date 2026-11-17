"""Durable artifacts produced by the quality-audit report phase.

The transport contract only carries the manifest. Artifact bytes remain in a
shared local directory so polling/restarting either side never copies a Word
document or full report through the HTTP layer again.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from server.config.settings import resolve_workspace_root

ARTIFACT_FORMAT = "veraud.audit.artifacts.v1"
ARTIFACT_DIRECTORY_NAME = ".veraud-artifacts"
_SECTIONS = (
    "identification", "executive_summary", "objectives_and_scope", "methodology_and_criteria",
    "software_description", "quality_results", "consolidated_risks", "general_conclusions",
    "recommendations_and_improvement_plan", "annexes_and_traceability",
)

_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


@dataclass(frozen=True)
class AuditArtifactManifest:
    format: str
    run_id: str
    report_bytes: int
    docx_bytes: int
    sections: tuple[str, ...]

    def model_dump(self) -> dict:
        return asdict(self)


def _safe_run_id(run_id: str) -> str:
    if _SAFE_RUN_ID.fullmatch(run_id) is None:
        raise ValueError("Audit run id is not a safe artifact key")
    return run_id

def artifact_root() -> Path:
    return Path(os.environ.get("VERAUD_ARTIFACT_DIR", resolve_workspace_root() / ARTIFACT_DIRECTORY_NAME))

def read_audit_artifacts(run_id: str) -> AuditArtifactManifest:
    safe_run_id = _safe_run_id(run_id)
    root = artifact_root() / safe_run_id
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        report_size = (root / "report.json").stat().st_size
        docx_size = (root / "report.docx").stat().st_size
    except (OSError, json.JSONDecodeError) as error:
        raise FileNotFoundError("Audit artifacts are not available for this run") from error
    if not isinstance(manifest, dict) or manifest.get("format") != ARTIFACT_FORMAT or manifest.get("run_id") != safe_run_id:
        raise ValueError("Audit artifact manifest is invalid")
    sections = manifest.get("sections")
    if not isinstance(sections, list) or any(section not in _SECTIONS for section in sections):
        raise ValueError("Audit artifact manifest contains an unknown section")
    report_bytes = manifest.get("report_bytes")
    docx_bytes = manifest.get("docx_bytes")
    if not isinstance(report_bytes, int) or report_bytes != report_size or not isinstance(docx_bytes, int) or docx_bytes != docx_size:
        raise ValueError("Audit artifact manifest does not match the stored files")
    return AuditArtifactManifest(ARTIFACT_FORMAT, safe_run_id, report_bytes, docx_bytes, tuple(sections))

def publish_audit_artifacts(run_id: str, report, document: bytes) -> AuditArtifactManifest:
    safe_run_id = _safe_run_id(run_id)
    report_bytes = report.model_dump_json().encode("utf-8")
    root = artifact_root()
    final = root / safe_run_id
    root.mkdir(parents=True, exist_ok=True)
    if final.exists():
        return read_audit_artifacts(safe_run_id)
    temporary = root / f".{safe_run_id}-{hashlib.sha256(report_bytes).hexdigest()[:12]}-tmp"
    if temporary.exists():
        shutil.rmtree(temporary)
    sections = temporary / "sections"
    sections.mkdir(parents=True)
    (temporary / "report.json").write_bytes(report_bytes)
    (temporary / "report.docx").write_bytes(document)
    for section in _SECTIONS:
        value = getattr(report, section)
        dumped = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        payload = json.dumps(dumped, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        (sections / f"{section}.json").write_bytes(payload)
    manifest = AuditArtifactManifest(
        format=ARTIFACT_FORMAT,
        run_id=safe_run_id,
        report_bytes=len(report_bytes),
        docx_bytes=len(document),
        sections=_SECTIONS,
    )
    (temporary / "manifest.json").write_text(json.dumps(manifest.model_dump(), separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, final)
    return manifest
