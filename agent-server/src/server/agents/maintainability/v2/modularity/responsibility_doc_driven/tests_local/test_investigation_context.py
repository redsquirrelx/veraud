"""Checks for the refined ResponsibilityAgent investigate loop."""

from types import SimpleNamespace

from server.agents.maintainability.v2.modularity.responsibility_doc_driven.investigation import (
    ResponsibilityInvestigation,
)


def test_relationship_answers_reach_model_context():
    tiny = ResponsibilityInvestigation()
    tiny.tools = SimpleNamespace(accessible_snapshot=SimpleNamespace(
        relationships=[SimpleNamespace(id="r1", source_id="f0", target_id="f1", kind="import")],
        symbols=[SimpleNamespace(id="f0", file_id="f0"), SimpleNamespace(id="f1", file_id="f1")],
        files=[SimpleNamespace(id="f0", path="a.py"), SimpleNamespace(id="f1", path="b.py")],
        evidence=[]))
    state = {"plan": SimpleNamespace(candidates=[SimpleNamespace(id="i1", primary_component="a.py",
        collaborators=[], question="?", documented_responsibility=None, evidence_needed=[], document_claim_ids=[])]),
        "current_investigation": 0, "active_query_keys": ['["list_relationships", {"source_id": "f0", "limit": 10, "offset": 0, "project_id": null, "kind": null, "resolution": null, "target_id": null}]'],
        "query_cache": {'["list_relationships", {"source_id": "f0", "limit": 10, "offset": 0, "project_id": null, "kind": null, "resolution": null, "target_id": null}]': {
            "tool_name": "list_relationships", "status": "ok", "data": {"items": [{
                "id": "r1", "source_id": "f0", "target_id": "f1", "kind": "import"}]},
            "evidence": []}},
        "task_limitations": [], "criteria": [], "commit": None}
    tiny.config = SimpleNamespace(tools=["list_relationships"])
    tiny.tools.context = SimpleNamespace(input=SimpleNamespace(snapshot_hash="h"))
    tiny.references = list
    tiny._delivered_ids = lambda state: set()
    context = tiny._investigation_context(state)
    assert context["tool_results"][0]["tool_name"] == "list_relationships"
    assert context["tool_results"][0]["data"]["items"][0]["source_path"] == "a.py"
    assert context["tool_results"][0]["data"]["items"][0]["target_path"] == "b.py"


def test_old_fragments_reappear_via_reusable_queries():
    tiny = ResponsibilityInvestigation()
    tiny.tools = SimpleNamespace(accessible_snapshot=SimpleNamespace(relationships=[], symbols=[], files=[], evidence=[]))
    tiny.config = SimpleNamespace(tools=["get_source_excerpt"])
    tiny.tools.context = SimpleNamespace(input=SimpleNamespace(snapshot_hash="h"))
    tiny.references = list
    tiny._delivered_ids = lambda state: set()
    old_key = '["get_source_excerpt", {"path": "a.py", "start_line": 1, "end_line": 20}]'
    state = {"plan": SimpleNamespace(candidates=[SimpleNamespace(id="i1", primary_component="a.py",
        collaborators=[], question="?", documented_responsibility=None, evidence_needed=[], document_claim_ids=[])]),
        "current_investigation": 0, "active_query_keys": [old_key, old_key],
        "query_cache": {old_key: {"tool_name": "get_source_excerpt", "status": "ok",
            "data": {"path": "a.py", "start_line": 1, "end_line": 20}, "evidence": []}},
        "task_limitations": [], "criteria": [], "commit": None}
    context = tiny._investigation_context(state)
    assert context["query_inventory"][0]["arguments"]["path"] == "a.py"
