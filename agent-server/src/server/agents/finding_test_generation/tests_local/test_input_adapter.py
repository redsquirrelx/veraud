"""Contracts for the audit-140 input adapter."""

import json
from pathlib import Path

from server.agents.finding_test_generation.input_adapter import (
    load_audit_document,
    parse_audit_payload,
)

FIXTURE = Path(__file__).resolve().parents[5] / "fixtures" / "audit_140" / "findings.json"


def _payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_parses_and_preserves_originals():
    document, diagnostics = load_audit_document(FIXTURE)
    assert document is not None, diagnostics.errors
    assert document.audit_id == 140
    assert document.commit_hash == "52b23bc085b55b00d340620ad2055d69672469bb"
    assert len(document.findings) == 5
    # Consolidated id and candidate id stay separate.
    first = document.findings[0]
    assert first.id == "a8b28bba-84cb-5411-bf74-1f956b157fc8"
    assert first.technical_details.id == "candidate:boundary_violation_001"
    # Original review states are preserved verbatim.
    statuses = sorted(finding.verification_status for finding in document.findings)
    assert statuses == ["inconclusive"] + ["unreviewed"] * 4


def test_fixture_records_unresolved_evidence_as_limitation():
    document, diagnostics = load_audit_document(FIXTURE)
    assert document is not None
    assert any("evidence reference(s) point to" in item for item in diagnostics.limitations)


def test_fixture_keeps_documentary_references():
    document, _ = load_audit_document(FIXTURE)
    boundary = document.findings[0]
    references = boundary.technical_details.documentary_references
    assert references and references[0].document_claim_id.startswith("document_claim_")
    assert references[0].quotes[0]["path"] == "docs/architecture/03-layer-rules.md"
    assert references[0].quotes[0]["start_line"] == 11


def test_duplicate_finding_id_is_rejected():
    payload = _payload()
    payload["findings"][1]["id"] = payload["findings"][0]["id"]
    document, diagnostics = parse_audit_payload(payload)
    assert document is None or not diagnostics.ok
    assert any("Duplicate finding id" in error for error in diagnostics.errors)


def test_malformed_commit_is_rejected():
    payload = _payload()
    payload["commitHash"] = "not-a-commit"
    document, diagnostics = parse_audit_payload(payload)
    assert document is None
    assert diagnostics.errors


def test_missing_components_is_rejected():
    payload = _payload()
    payload["findings"][0]["components"] = []
    document, diagnostics = parse_audit_payload(payload)
    assert document is not None
    assert any("components" in error for error in diagnostics.errors)
