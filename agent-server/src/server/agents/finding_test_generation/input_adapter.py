"""Parsing and validation of audit-export JSON documents.

The adapter never re-interprets the audit: it validates structure, preserves
the original ``finding.id`` and ``technical_details.id`` separately, keeps the
original ``verification_status`` and records, as explicit limitations, every
piece of evidence whose contents are not included in the export.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from .schemas import AuditDocument, Finding

_COMMIT_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")


@dataclass
class InputDiagnostics:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _finding_report(finding: Finding, diagnostics: InputDiagnostics) -> None:
    if not finding.components:
        diagnostics.errors.append(f"finding {finding.id}: 'components' is empty; at least one target path is required.")
    if not finding.evidence_ids:
        diagnostics.warnings.append(f"finding {finding.id}: no evidence_ids; the specification will be weaker.")
    if not finding.justification.strip():
        diagnostics.warnings.append(f"finding {finding.id}: empty justification.")
    # Evidence contents are not embedded in the export; never pretend they were read.
    unresolved = [*finding.evidence_ids, *finding.technical_details.evidence_ids]
    if unresolved:
        diagnostics.limitations.append(
            f"finding {finding.id}: {len(set(unresolved))} evidence reference(s) point to audit-internal artifacts "
            f"not shipped in the exported audit; their contents were not inspected."
        )


def parse_audit_payload(payload: dict) -> tuple[AuditDocument | None, InputDiagnostics]:
    diagnostics = InputDiagnostics()
    if not isinstance(payload, dict):
        diagnostics.errors.append("The audit export must be a JSON object.")
        return None, diagnostics
    try:
        document = AuditDocument.model_validate(payload)
    except ValidationError as error:
        diagnostics.errors.append(f"Invalid audit export: {error.error_count()} validation error(s). First: {error.errors()[0]['loc']} {error.errors()[0]['msg']}")
        return None, diagnostics
    if not _COMMIT_PATTERN.match(document.commit_hash):
        diagnostics.errors.append(f"commitHash {document.commit_hash!r} is not a 40-character hexadecimal commit.")
        return None, diagnostics

    seen_ids: set[str] = set()
    seen_technical_ids: set[str] = set()
    for finding in document.findings:
        if finding.id in seen_ids:
            diagnostics.errors.append(f"Duplicate finding id: {finding.id}")
        seen_ids.add(finding.id)
        if finding.technical_details.id in seen_technical_ids:
            diagnostics.warnings.append(f"Duplicate technical_details id: {finding.technical_details.id}")
        seen_technical_ids.add(finding.technical_details.id)
        if finding.verification_status not in {"unreviewed", "inconclusive", "reviewed"}:
            diagnostics.warnings.append(
                f"finding {finding.id}: unexpected verification_status {finding.verification_status!r}; it is preserved verbatim."
            )
        _finding_report(finding, diagnostics)

    for reference_document in document.findings:
        for reference in reference_document.technical_details.documentary_references:
            if reference.commit and reference.commit.lower() != document.commit_hash.lower():
                diagnostics.warnings.append(
                    f"finding {reference_document.id}: documentary reference {reference.document_claim_id} "
                    f"is pinned to commit {reference.commit}, not the audit commit {document.commit_hash}."
                )
    return document, diagnostics


def load_audit_document(path: str | Path) -> tuple[AuditDocument | None, InputDiagnostics]:
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
    return parse_audit_payload(payload)


def check_checkout(repo_path: str | Path | None, expected_commit: str) -> tuple[bool, list[str]]:
    """Compare a local checkout with the audited commit, when possible."""

    from server.runtimes.verification.checkout import check_checkout as _check

    return _check(repo_path, expected_commit)
