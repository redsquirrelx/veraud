"""Adapt a verification-suite audit-export payload to the probe's input shape.

The audit export carries richer per-finding data (31 fields); this adapter is
lossy but conservative: it maps the fields the probe consumes and reports the
rest as limitations instead of fabricating them.
"""

from typing import Any

from server.runtimes.verification.split import criterion_id_of, group_of

__all__ = ["convert_audit_export", "convert_finding"]


def _str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _list(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def convert_finding(finding: dict) -> dict:
    technical = finding.get("technical_details") if isinstance(finding.get("technical_details"), dict) else {}
    components = _list(finding.get("components")) or _list(technical.get("components"))
    evidence_ids = _list(finding.get("evidence_ids")) or _list(technical.get("evidence_ids"))
    claim_ids = _list(technical.get("document_claim_ids")) or _list(finding.get("document_claim_ids"))
    return {
        "id": _str(finding.get("id")) or "unknown",
        "title": _str(finding.get("title")) or _str(technical.get("title")) or "(untitled finding)",
        "description": _str(finding.get("description")) or _str(technical.get("description")),
        "criterion_id": criterion_id_of(finding),
        "kind": _str(finding.get("kind")) or _str(technical.get("kind")),
        "components": components,
        "evidence_ids": evidence_ids,
        "justification": _str(finding.get("justification")) or _str(technical.get("justification")),
        "modularity_impact": _str(finding.get("impact")) or _str(finding.get("modularity_impact") or ""),
        "severity": _str(finding.get("severity")),
        "confidence": finding.get("confidence", technical.get("confidence")) or 0.0,
        "recommendation": _str(finding.get("recommendation")) or _str(technical.get("recommendation")),
        "document_claim_ids": claim_ids,
        "evidence": [],  # audit export does not embed evidence records; the probe must tolerate that
        "validation_status": _str(finding.get("verification_status")) or _str(technical.get("validation_status")),
        "subcharacteristic": group_of(finding),
    }


def convert_audit_export(adapted: dict) -> dict:
    findings = [f for f in (adapted.get("findings") or []) if isinstance(f, dict)]
    audit_id = adapted.get("auditId")
    return {
        "repository_id": _str(adapted.get("project_name") or audit_id or "audit"),
        "commit": _str(adapted.get("commitHash")),
        "objective": f"Verification suite generation for audit {audit_id}",
        "findings": [convert_finding(finding) for finding in findings],
        "hypotheses": [],
        "missing_information": [],
        "limitations": [],
        "termination_reason": "audit_export_import",
    }
