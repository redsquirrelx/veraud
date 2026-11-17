"""Rule selection: prompt rendering, response validation and manifest provenance."""

import asyncio
import json
from pathlib import Path

from server.agents.finding_test_generation.input_adapter import load_audit_document
from server.agents.finding_test_generation.llm_client import ScriptedLLMClient
from server.agents.finding_test_generation.packaging import build_suite
from server.agents.finding_test_generation.planning import plan_verifications
from server.agents.finding_test_generation.rules import applicable_rules
from server.agents.finding_test_generation.schemas import ValidationRecord
from server.agents.finding_test_generation.selector import (
    apply_selection,
    build_selection_prompt,
    parse_selection,
    select_boundary_verification,
)
from server.agents.finding_test_generation.test_templates import render_test_file

FIXTURE = Path(__file__).resolve().parents[5] / "fixtures" / "audit_140" / "findings.json"


def _specs():
    document, _ = load_audit_document(FIXTURE)
    specs, _ = plan_verifications(document)
    return document, specs


def test_prompt_substitutes_every_placeholder():
    document, specs = _specs()
    spec = specs[0]
    finding = next(item for item in document.findings if item.id == spec.finding_id)
    allowed = [rule.rule_id for rule in applicable_rules(spec)]
    prompt = build_selection_prompt(spec, document, finding, allowed)
    assert "{{" not in prompt and "}}" not in prompt
    assert finding.justification.split("\n", 1)[0][:40] in prompt
    assert "`layer_import`" in prompt


def test_prompt_with_missing_documentary_fields_renders_empty():
    document, specs = _specs()
    spec = specs[0]
    finding = next(item for item in document.findings if item.id == spec.finding_id)
    for reference in finding.technical_details.documentary_references:
        reference.statement = ""
        reference.subject = ""
        reference.constraint = ""
        reference.document_claim_id = ""
    prompt = build_selection_prompt(spec, document, finding, ["layer_import"])
    assert "{{" not in prompt
    reference_line = next(line for line in prompt.splitlines() if line.startswith("Documentary references: "))
    parsed = json.loads(reference_line.split(": ", 1)[1])
    assert parsed and all(set(item) == {"id", "subject", "statement", "constraint"} for item in parsed)


def _selection_json(rule_id, parameters, confidence="high", reason="matches the architecture boundary"):
    return json.dumps({"rule_id": rule_id, "parameters": parameters, "confidence": confidence, "reason": reason})


def test_high_confidence_selection_is_applied():
    document, specs = _specs()
    spec = specs[0]
    finding = next(item for item in document.findings if item.id == spec.finding_id)
    assert spec.rule_kind == "layer_import"
    client = ScriptedLLMClient(
        selections=[_selection_json("restricted_import", {"allowed_roots": ["urbanmesh.presentation"]})])

    result = asyncio.run(select_boundary_verification(spec, document, finding, client))

    assert result.applied is True
    assert result.applied_spec is not None
    assert result.applied_spec.rule_kind == "restricted_import"
    assert result.applied_spec.rule_params["allowed_roots"] == ["urbanmesh.presentation"]
    assert result.confidence == "high"
    content = render_test_file(result.applied_spec)[1]
    assert "restricted_import_check" in content


def test_low_confidence_selection_keeps_deterministic_plan():
    document, specs = _specs()
    spec = specs[0]
    finding = next(item for item in document.findings if item.id == spec.finding_id)
    client = ScriptedLLMClient(selections=[_selection_json("restricted_import", {"allowed_roots": ["urbanmesh"]}, confidence="low")])

    result = asyncio.run(select_boundary_verification(spec, document, finding, client))

    assert result.applied is False
    assert result.applied_spec is None
    assert result.reportable is False
    assert spec.rule_kind == "layer_import"


def test_malformed_json_keeps_deterministic_plan():
    document, specs = _specs()
    spec = specs[0]
    finding = next(item for item in document.findings if item.id == spec.finding_id)
    client = ScriptedLLMClient(selections=["not json at all"])

    result = asyncio.run(select_boundary_verification(spec, document, finding, client))

    assert result.applied is False
    assert "no JSON object" in result.reason


def test_unknown_rule_id_keeps_deterministic_plan():
    document, specs = _specs()
    spec = specs[0]
    finding = next(item for item in document.findings if item.id == spec.finding_id)
    client = ScriptedLLMClient(selections=[_selection_json("made_up_rule", {})])

    result = asyncio.run(select_boundary_verification(spec, document, finding, client))

    assert result.applied is False
    assert "made_up_rule" in result.reason


def test_restricted_import_without_roots_is_rejected():
    document, specs = _specs()
    spec = specs[0]
    finding = next(item for item in document.findings if item.id == spec.finding_id)
    client = ScriptedLLMClient(selections=[_selection_json("restricted_import", {})])

    result = asyncio.run(select_boundary_verification(spec, document, finding, client))

    assert result.applied is False
    assert "allowed_roots" in result.reason


def test_parse_selection_extracts_json_inside_prose():
    response, problem = parse_selection(
        "Here is the selection:\n```json\n{\"rule_id\": \"layer_import\", \"parameters\": {}, \"confidence\": \"high\", \"reason\": \"ok\"}\n```",
        ["layer_import"],
    )
    assert problem is None
    assert response is not None and response.rule_id == "layer_import"


def test_apply_selection_merges_parameters():
    from server.agents.finding_test_generation.selector import LLMSelectionResponse

    _, specs = _specs()
    spec = specs[0]
    updated = apply_selection(spec, LLMSelectionResponse(
        rule_id="restricted_import", parameters={"allowed_roots": ["urbanmesh"]},
        confidence="high", reason="x"))
    assert updated.rule_params["allowed_roots"] == ["urbanmesh"]
    assert updated.rule_kind == "restricted_import"


def test_manifest_carries_rule_provenance(tmp_path):
    document, specs = _specs()
    spec = specs[0]
    specs[0] = spec.model_copy(update={"rule_kind": "restricted_import",
                                       "rule_params": {"allowed_roots": ["urbanmesh.presentation"]}})
    output = tmp_path / "suite.zip"
    records = [ValidationRecord(verification_id=item.verification_id, status="generated") for item in specs]
    build_suite(document, specs, records, [], output)

    import zipfile

    with zipfile.ZipFile(output) as archive:
        manifest_data = json.loads(archive.read(".tallercito/manifest.json"))
        report = archive.read(".tallercito/docs/verification-report.md").decode("utf-8")
    entry = next(item for item in manifest_data["verifications"] if item["verification_id"] == spec.verification_id)
    assert entry["rule_id"] == "restricted_import"
    assert entry["rule_params"]["allowed_roots"] == ["urbanmesh.presentation"]
    assert "Regla" in report
    assert "`restricted_import`" in report
    assert '"allowed_roots": ["urbanmesh.presentation"]' in report
