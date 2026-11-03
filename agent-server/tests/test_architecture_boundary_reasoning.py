"""Offline reasoning-protocol regressions; live fixture results are evaluated separately.

Scripted conclusions test exploration, citations and preservation of code-backed
rationales, not the semantic accuracy of an actual language model.
"""

from pathlib import Path

import pytest
from test_architecture_boundary_citations import audit, conclusion


@pytest.mark.parametrize("private_access", [False, True])
def test_bidirectional_components_can_be_legitimate_or_contradict_an_inferred_interface(tmp_path, private_access):
    first = ("from beta.worker import render\n__all__ = ['public_label', 'start']\n"
        "_labels = {'default': 'Ready'}\ndef public_label(): return _labels['default']\n"
        "def start(): return render()\n")
    second = ("from alpha import service\n__all__ = ['render']\n"
        + ("def render(): return service._labels['default']\n" if private_access else
            "def render(): return service.public_label()\n"))
    def decide(context):
        catalog = context["reference_catalog"]
        if catalog["planned_only_relationship_ids"]:
            return {"action": "tools", "queries": [query | {"reason": "Inspect the reverse mechanism before judging this cycle."}
                for query in catalog["verification_queries"].values()]}
        assert len(catalog["examined_relationships"]) == 2
        assert all(edge["kind"] == "from_import" for edge in catalog["examined_relationships"])
        source = "\n".join(view["data"].get("content", "") for view in context["tool_results"])
        assert "__all__" in source and "def public_label" in source and "def start" in source
        if not private_access:
            assert "return service.public_label()" in source
            return conclusion(context, justification=(
                "render calls the exported public_label query, which returns an immutable string and does not call start. "
                "start invokes render through its exported operation. Both directions use the observed public contracts, "
                "without accessing peer-owned storage; the two imports are not a demonstrated boundary contradiction."))
        assert "return service._labels['default']" in source
        response = conclusion(context, "finding_candidate", summary="The reverse edge bypasses the observed export surface.",
            justification="The cycle's reverse use reads peer-owned backing state instead of the exported public_label query.")
        result = response["conclusion"]
        result["candidates"] = [{"id": "backing-state-bypass", "title": "Reverse dependency bypasses a supported interface",
            "description": "render reads _labels directly although public_label provides the same observation through the export surface.",
            "criterion_id": context["criteria"][0]["id"], "kind": "design_observation", "severity": "medium", "confidence": .8,
            "inferred_boundary": "The module owns _labels and exposes public_label and start through __all__.",
            "contradictory_dependency": "The peer's render function reads service._labels instead of public_label.",
            "technical_basis": "The export declaration, owner implementation, alternate public query and reverse read are all inspected source.",
            "justification": "The concern is the observed backing-state access, not the cycle alone or a prescribed layering pattern.",
            "modularity_impact": "The reverse access crosses the code-supported state/interface boundary.",
            "recommendation": "Use the observed public query if this observation is needed.",
            **{field: result[field] for field in ("components", "relationship_ids", "evidence_ids")}}]
        return response
    result, _, _ = audit(tmp_path, {"alpha/service.py": first, "beta/worker.py": second}, decide)
    record = result.investigation_results[0]
    assert record.status == ("finding_candidate" if private_access else "no_finding")
    assert len(record.relationship_ids) == 2 and record.evidence_ids
    assert not result.findings
    if private_access:
        assert "__all__" in result.candidates[0].inferred_boundary
        assert "service._labels" in result.candidates[0].contradictory_dependency
    else:
        assert "immutable string" in record.justification and not result.candidates


def test_additional_source_is_requested_when_initial_windows_do_not_show_the_contract(tmp_path):
    # The import is present in the first window; its implemented contract is not.
    contents = {"alpha/service.py": "from beta.worker import render\n" + "\n" * 65
        + "__all__ = ['public_label', 'start']\ndef public_label(): return 'Ready'\ndef start(): return render()\n",
        "beta/worker.py": "from alpha import service\ndef render(): return service.public_label()\n"}
    def decide(context):
        catalog = context["reference_catalog"]
        if catalog["planned_only_relationship_ids"]:
            return {"action": "tools", "queries": [query | {"reason": "Verify the other direction of the proposed cycle."}
                for query in catalog["verification_queries"].values()]}
        source = "\n".join(view["data"].get("content", "") for view in context["tool_results"])
        if "def public_label" not in source:
            located = [view for view in context["tool_results"] if view["tool_name"] == "find_symbols"]
            if not located:
                return {"action": "tools", "queries": [{"tool": "find_symbols", "arguments": {"file_path": "alpha/service.py"},
                    "reason": "The import excerpt does not show the implementation of the called public query."}]}
            symbol = next(row for row in located[0]["data"]["items"] if row["name"] == "public_label")
            return {"action": "tools", "queries": [{"tool": "get_source_excerpt", "arguments": {
                "path": "alpha/service.py", "start_line": symbol["start_line"] - 1, "end_line": symbol["end_line"] + 1},
                "reason": "Inspect the located query implementation and its export declaration before closing."}]}
        return conclusion(context, justification=("The newly inspected public_label returns an immutable value without invoking start; "
            "the peer uses that exported query rather than internal state, so the observed reciprocal imports are legitimate here."))
    result, model, tools = audit(tmp_path, contents, decide)
    assert result.investigation_results[0].status == "no_finding"
    assert result.model_calls == 5
    assert any(view["tool_name"] == "find_symbols" for context in model.contexts[1:] for view in context.get("tool_results", []))
    assert not any(item.repeated for item in tools.tool_measurements)


def test_missing_implementation_and_boundary_evidence_can_close_inconclusive(tmp_path):
    contents = {"alpha/service.py": "from beta.worker import execute\ndef start(): return execute()\n",
        "beta/worker.py": "from alpha import service\nfrom missing_plugin import validate\ndef execute(): return validate(service)\n"}
    def decide(context):
        catalog = context["reference_catalog"]
        if catalog["planned_only_relationship_ids"]:
            return {"action": "tools", "queries": [query | {"reason": "Check both directions before assessing the unresolved mechanism."}
                for query in catalog["verification_queries"].values()]}
        return conclusion(context, "inconclusive", summary="The reciprocal imports are observed, but their boundary conformance is unresolved.",
            justification="The missing plugin implements the reverse interaction; the delivered code does not show what it accesses or which interface it honors.",
            limitations=["Plugin implementation and its access contract are outside retained source; neither a contradiction nor legitimacy can be established."])
    result, _, _ = audit(tmp_path, contents, decide)
    record = result.investigation_results[0]
    assert record.status == "inconclusive" and record.evidence_ids and record.limitations
    assert not result.candidates and not result.findings


def test_investigation_prompt_requires_inference_and_positive_scoped_legitimacy_without_named_patterns_as_proof():
    prompt = (Path(__file__).parents[1] / "src/server/agents/maintainability/modularity/architecture_boundary/prompts/investigate.md").read_text(encoding="utf-8")
    inference = prompt.split("Boundary inference", 1)[1].split("Cycle reasoning", 1)[0]
    cycles = " ".join(prompt.split("Cycle reasoning", 1)[1].split("Closing the investigation", 1)[0].split())
    closure = prompt.split("Closing the investigation", 1)[1]
    assert "interfaces" in inference and "actual usage" in inference and "predominant" in inference
    assert "Clean Architecture" in inference and "not proof" in inference
    assert "both directions" in cycles and "legitimate" in cycles and "type_only" in cycles
    assert "positive" in closure and "inconclusive" in closure and "explicit prohibition" in closure
