"""End-to-end checks: deterministic verification contract in final output."""

import json

import pytest
from pydantic import ValidationError
from test_architecture_boundary_doc_driven_investigation import (
    assess_all,
    close,
    run,
    verified_tools,
)
from test_architecture_boundary_doc_driven_planning import claim, context

from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.schemas import (
    BoundaryFinding,
    ProhibitedImportDirective,
)
from server.blackboard.identity import AuditIdentity
from server.blackboard.impls.memory import MemoryBlackboard
from server.blackboard.publication import Publication
from server.reporting.knowledge import report_findings


def ts_fixture(tmp_path, first=True):
    return verified_tools(tmp_path, {
        "tsconfig.json": '{"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["./*"]}}}',
        "lib/prisma.ts": "export class PrismaClient {}\n",
        "app/orders-route.ts": 'import { prisma } from "@/lib/prisma";\n'
                               "export const orders = prisma;\n",
        "app/accounting-periods-route.ts": 'import { prisma } from "@/lib/prisma";\n'
                                          "export const periods = prisma;\n",
    })


def prohibition(subject):
    return claim(f"{subject} MUST NOT import @/lib/prisma directly.",
                 subject=subject, related_subjects=["@/lib/prisma"],
                 constraint="prohibited",
                 evidence=[{"section_id": "s1", "start_line": 1, "end_line": 1,
                           "quote": f"{subject} must never import @/lib/prisma; use the service layer.\n"}])


def run_ts_claim(tmp_path, route):
    tools = ts_fixture(tmp_path)
    source = context(tools, [prohibition(route)])

    def decide(payload):
        if "opportunities" in payload:
            task_id = next(t["id"] for t in payload["opportunities"] if route in t["scope"] or route in t["question"])
            return {"opportunity_ids": [task_id]}
        return assess_all(payload, "contradicted", status="finding_candidate", candidate=True)

    state, _, execution = run(tools, source, decide)
    state.update(execution.synthesis(state))
    state.update(execution.finalize(state))
    return state["result"]


@pytest.mark.parametrize("route", ["app/orders-route.ts", "app/accounting-periods-route.ts"])
def test_prohibited_import_directive_matches_imported_specifier_and_route(tmp_path, route):
    result = run_ts_claim(tmp_path, route)
    assert len(result.findings) == 1
    finding = result.findings[0]
    claim_ids = result.plan.document_claims.keys()
    assert finding.document_claim_ids and set(finding.document_claim_ids) <= set(claim_ids)
    directive = finding.verification.directives[0]
    assert directive.kind == "prohibited_import"
    assert directive.targets == ["@/lib/prisma"]
    assert directive.scope == [route]
    assert set(directive.claim_ids) == set(finding.document_claim_ids)
    assert directive.basis == "explicit-document-claim"
    assert route in finding.components
    assert "@/lib/prisma" not in finding.components


def test_non_verifiable_candidate_surfaces_limitation_and_no_directive(tmp_path):
    tools = verified_tools(tmp_path, {"app/api.py": "from .store import Store\n",
                                     "app/store.py": "class Store: pass\n"})
    # Claim prohibits a dependency generally but names no literal specifier.
    source = context(tools, [claim("app/api.py must not import anything outside the API.",
                                   subject="app/api.py", related_subjects=[".store"],
                                   constraint="prohibited")])

    def decide(payload):
        if "opportunities" in payload:
            return {"opportunity_ids": [payload["opportunities"][0]["id"]]}
        return assess_all(payload, "contradicted", status="finding_candidate", candidate=True)

    state, _, execution = run(tools, source, decide)
    state.update(execution.synthesis(state))
    state.update(execution.finalize(state))
    result = state["result"]
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.verification is None
    assert any("verification:" in item for item in finding.verification_limitations)
    assert any("verification:" in item for item in result.limitations)
    assert set(result.findings[0].verification_limitations) <= set(result.limitations)
    assert set(finding.components) <= {"app/api.py", "app/store.py"}
    assert "@/lib/prisma" not in json.dumps(finding.model_dump())


def test_claim_without_enforceable_specifier_or_source_blocks_directive(tmp_path):
    tools = verified_tools(tmp_path, {"app/api.py": "from .store import Store\n",
                                     "app/store.py": "class Store: pass\n"})
    source = context(tools, [prohibition("app/api")])

    # Model selects but never names a candidate and instead closes as no_finding.
    def decide(payload):
        if "opportunities" in payload:
            return {"opportunity_ids": [payload["opportunities"][0]["id"]]}
        return close(payload, {key: "supported" for key in payload.get("documentary_context", {}).get("claims", {})})

    state, _, execution = run(tools, source, decide)
    state.update(execution.synthesis(state))
    state.update(execution.finalize(state))
    result = state["result"]
    assert not result.findings


def test_directive_lists_only_explicitly_prohibited_specifiers(tmp_path):
    # No delimited specifier appears in the documented prohibition.
    tools = ts_fixture(tmp_path)
    source = context(tools, [claim("Persistence access must go through service abstractions.",
                                   subject="app/orders-route.ts", related_subjects=["prisma"],
                                   constraint="prohibited")])

    def decide(payload):
        if "opportunities" in payload:
            return {"opportunity_ids": [payload["opportunities"][0]["id"]]}
        return assess_all(payload, "contradicted", status="finding_candidate", candidate=True)

    state, _, execution = run(tools, source, decide)
    state.update(execution.synthesis(state))
    state.update(execution.finalize(state))
    result = state["result"]
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.verification is None
    assert finding.verification_limitations


def test_diagnostic_incorrect_verifier_is_not_allowed(tmp_path):
    # Directives must be derived, never invented by generic dev tooling.
    directive = ProhibitedImportDirective(scope=["app/orders-route.ts"],
                                          targets=["@/lib/prisma"], claim_ids=["x"])
    assert directive.basis == "explicit-document-claim"
    with pytest.raises(ValidationError):
        ProhibitedImportDirective(scope=["app/orders-route.ts"],
                                  targets=["@/lib/prisma"], claim_ids=["x"], basis="anything")


def test_verification_references_components_strictly():
    finding = BoundaryFinding.model_validate({
        "id": "candidate-1", "title": "T", "description": "D", "criterion_id": "architectural-boundaries",
        "kind": "violation", "components": ["app/orders-route.ts"], "evidence_ids": ["e1"],
        "criterion": {"id": "architectural-boundaries", "description": "d", "origin": "inferred",
                      "provenance": "Extracted from index."},
        "evidence": [{"id": "e1", "snapshot_hash": "snap", "commit": "commit",
                      "path": "app/orders-route.ts", "file_id": "file",
                      "content_hash": "hash", "kind": "source", "start_line": 1, "end_line": 3,
                      "tool_call_id": "c", "commit_verification": "exact"}],
        "justification": "Source shows direct import of @/lib/prisma.",
        "modularity_impact": "Concrete use case couples to persistence.",
        "severity": "medium", "confidence": 0.9,
        "recommendation": "Move import to service layer.",
        "document_claim_ids": ["claim-1"],
        "verification": {"directives": [{"kind": "prohibited_import",
                                         "scope": ["app/orders-route.ts"],
                                         "targets": ["@/lib/prisma"],
                                         "claim_ids": ["claim-1"],
                                         "basis": "explicit-document-claim"}]},
        "verification_limitations": []})
    with pytest.raises(ValidationError):
        BoundaryFinding.model_validate(
            finding.model_dump() | {"verification": {"directives": [{"kind": "prohibited_import",
                "scope": ["lib/prisma.ts"], "targets": ["@/lib/prisma"],
                "claim_ids": ["claim-1"], "basis": "explicit-document-claim"}]}})
    with pytest.raises(ValidationError):
        BoundaryFinding.model_validate(
            finding.model_dump() | {"verification": {"directives": [{"kind": "prohibited_import",
                "scope": ["app/orders-route.ts"], "targets": ["@/lib/prisma"],
                "claim_ids": ["claim-1", "other"], "basis": "explicit-document-claim"}]}})


def test_blackboard_and_report_preserve_verification_and_provenance(tmp_path):
    result = run_ts_claim(tmp_path, "app/orders-route.ts")
    assert result.findings and result.findings[0].verification
    identity = AuditIdentity(run_id="run", invocation_id="inv")
    board = MemoryBlackboard()
    publication = Publication(board, "architecture-boundary", run_id=identity.run_id,
                              invocation_id=identity.invocation_id)
    publication.publish_investigation(result, result.findings[0].evidence,)
    stored = board.query_findings(identity.run_id, identity.invocation_id)
    assert stored and stored[0].details["verification"]["directives"] == (
        result.findings[0].verification.model_dump(mode="json")["directives"])
    assert stored[0].details["document_claim_ids"] == result.findings[0].document_claim_ids
    reports, _, _ = report_findings(stored, board.query_evidence(identity.run_id, identity.invocation_id), [])
    assert reports and reports[0].technical_details["verification"]["directives"] == (
        stored[0].details["verification"]["directives"])
    assert "document_claim_ids" in reports[0].technical_details
    assert "@/lib/prisma" not in reports[0].technical_details.get("components", [])


def test_no_verification_survives_old_shape_blackboard(tmp_path):
    result = run_ts_claim(tmp_path, "app/orders-route.ts")
    legacy = result.model_dump(mode="json")
    assert list(legacy["findings"][0]) == list(result.findings[0].model_dump().keys())
    assert result.findings[0].model_dump_json()
