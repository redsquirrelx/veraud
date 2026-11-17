"""Deterministic verification-spec derivation."""

import json
from pathlib import Path

from server.agents.finding_test_generation.input_adapter import (
    load_audit_document,
    parse_audit_payload,
)
from server.agents.finding_test_generation.planning import plan_verifications

FIXTURE = Path(__file__).resolve().parents[5] / "fixtures" / "audit_140" / "findings.json"


def _document():
    document, diagnostics = load_audit_document(FIXTURE)
    assert document is not None, diagnostics.errors
    return document


def test_audit_140_yields_six_specs_with_unique_ids():
    specs, _limitations = plan_verifications(_document())
    assert len(specs) == 6
    assert len({spec.verification_id for spec in specs}) == 6
    assert [spec.rule_kind for spec in specs] == [
        "layer_import", "layer_import", "private_module_access", "layer_import", "contract_states", "contract_states_dynamic",
    ]


def test_boundary_specs_bind_to_cited_components():
    specs, _ = plan_verifications(_document())
    first = specs[0]
    assert first.strategy == "static_ast"
    assert first.target_components == [
        "src/urbanmesh/application/inventory/allocator.py",
        "src/urbanmesh/infrastructure/storage/memory.py",
    ]
    assert "urbanmesh.infrastructure" in first.violation_oracle
    assert first.rule_source.document_claim_ids


def test_domain_finding_preserves_documentary_claims():
    specs, _ = plan_verifications(_document())
    domain = specs[1]
    assert "document_claim_65bc324030d74938d9480e35407b7684f0696ee2a6c8e226cda4f9f46ba758a7" in domain.rule_source.document_claim_ids


def test_unknown_criterion_is_reported_not_invented():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["findings"][0]["criterion"]["id"] = "unknown-criterion"
    clone, diagnostics = parse_audit_payload(payload)
    assert clone is not None, diagnostics.errors
    specs, limitations = plan_verifications(clone)
    assert len(specs) == 5
    assert any("NOT_VERIFIABLE" in limitation for limitation in limitations)
