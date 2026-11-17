"""Parsing and validation of testability-investigation result exports.

Accepts the JSON persisted by the investigation runners
(``artifacts/test-isolation-*.json`` / ``test-controllability-*.json``), i.e.
``{repository_id, commit, snapshot_hash, objective, findings: [...], ...}``.
Unlike the audit-export adapter, this one never requires an audit id; the
repository id and commit identify the run.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from server.runtimes.verification.checkout import check_checkout  # noqa: F401  (re-exported for callers)

from .schemas import ProbeDocument

_COMMIT_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")


@dataclass
class InputDiagnostics:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _finding_report(finding, diagnostics: InputDiagnostics) -> None:
    if not finding.components:
        diagnostics.errors.append(f"finding {finding.id}: 'components' is empty; at least one component path is required.")
    for component in finding.components:
        if Path(component).is_absolute():
            diagnostics.warnings.append(f"finding {finding.id}: absolute component path {component!r}; the runner expects repository-relative paths.")
    if not finding.evidence_ids:
        diagnostics.warnings.append(f"finding {finding.id}: no evidence_ids; the verifier will be weaker.")
    if not finding.evidence:
        diagnostics.limitations.append(f"finding {finding.id}: no embedded evidence records; the agent will rely on components and ids only.")
    if not finding.justification.strip():
        diagnostics.warnings.append(f"finding {finding.id}: empty justification.")
    if not finding.recommendation.strip():
        diagnostics.warnings.append(f"finding {finding.id}: empty recommendation.")


def parse_probe_payload(payload: dict) -> tuple[ProbeDocument | None, InputDiagnostics]:
    diagnostics = InputDiagnostics()
    if not isinstance(payload, dict):
        diagnostics.errors.append("The findings document must be a JSON object.")
        return None, diagnostics
    if "findings" not in payload:
        diagnostics.errors.append(
            "The findings document has no 'findings' list. Expected a TestIsolationAgent/TestControllabilityAgent "
            "result export (repository_id, commit, findings[])."
        )
        return None, diagnostics
    if "auditId" in payload and "repository_id" not in payload:
        diagnostics.errors.append(
            "This looks like an audit-export (auditId/commitHash), not a testability-investigation export. "
            "Feed this agent the investigation result JSON instead."
        )
        return None, diagnostics
    try:
        document = ProbeDocument.model_validate(payload)
    except ValidationError as error:
        diagnostics.errors.append(
            f"Invalid findings document: {error.error_count()} validation error(s). "
            f"First: {error.errors()[0]['loc']} {error.errors()[0]['msg']}"
        )
        return None, diagnostics

    if not document.commit:
        diagnostics.warnings.append("No commit in the findings document; the manifest source_commit will be empty.")
    elif not _COMMIT_PATTERN.match(document.commit):
        diagnostics.warnings.append(f"commit {document.commit!r} is not a 40-character hexadecimal commit.")

    seen: set[str] = set()
    for finding in document.findings:
        if finding.id in seen:
            diagnostics.errors.append(f"Duplicate finding id: {finding.id}")
        seen.add(finding.id)
        _finding_report(finding, diagnostics)
    return document, diagnostics


def load_probe_document(path: str | Path) -> tuple[ProbeDocument | None, InputDiagnostics]:
    path = Path(path)
    diagnostics = InputDiagnostics()
    if not path.is_file():
        diagnostics.errors.append(f"Findings file not found: {path}")
        return None, diagnostics
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        diagnostics.errors.append(f"Findings file is not valid JSON: {error}")
        return None, diagnostics
    return parse_probe_payload(payload)


def architecture_context_digest(path: str | Path | None, *, max_chars: int = 2000) -> str:
    """Compact, bounded digest of architecture_context.json; never the whole file."""

    if not path:
        return ""
    source = Path(path)
    if not source.is_file():
        return f"architecture_context.json not found at {source}."
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return "architecture_context.json unreadable; ignore it."

    parts: list[str] = [f"schema_version={payload.get('schema_version')}",
                        f"execution_status={payload.get('execution_status')}"]
    knowledge = payload.get("knowledge") or []
    parts.append(f"knowledge_entries={len(knowledge)}")
    covered = payload.get("covered_categories") or []
    pending = payload.get("pending_categories") or []
    if covered:
        parts.append("covered_categories=" + ",".join(str(item)[:40] for item in covered[:12]))
    if pending:
        parts.append("pending_categories=" + ",".join(str(item)[:40] for item in pending[:12]))
    titles = []
    for entry in knowledge[:8]:
        if isinstance(entry, dict):
            title = entry.get("title") or entry.get("category") or entry.get("source") or ""
            if title:
                titles.append(str(title)[:90])
    if titles:
        parts.append("knowledge_sample=" + " | ".join(titles))
    digest = "; ".join(parts)
    return digest[:max_chars]
