"""Regression checks for ResponsibilityAgent investigate validation."""

from types import SimpleNamespace

from server.agents.maintainability.v2.modularity.responsibility_doc_driven.investigation import (
    ResponsibilityInvestigation,
)


def test_turn_requires_primary_component_for_no_finding():
    from pydantic_core import PydanticCustomError

    tiny = ResponsibilityInvestigation()
    tiny.tools = SimpleNamespace(accessible_snapshot=SimpleNamespace(symbols=[], relationships=[]))
    tiny.references = list
    tiny._delivered_ids = lambda state: set()
    tiny._examined_relationships = lambda state: {}
    state = {
        "plan": SimpleNamespace(candidates=[SimpleNamespace(id="i1", primary_component="a.py",
            collaborators=[], question="?", evidence_needed=[], document_claim_ids=[])]),
        "current_investigation": 0, "active_query_keys": [], "query_cache": {},
        "task_limitations": [], "criteria": [], "commit": None,
    }
    turn = SimpleNamespace(action="close", queries=[], conclusion=SimpleNamespace(
        investigation_id="i1", status="no_finding", candidates=[], limitations=[],
        evidence_ids=[], components=[], symbol_ids=[], relationship_ids=[], claim_assessments=[]))
    try:
        tiny._validate_turn(turn, state)
        assert False
    except PydanticCustomError as error:
        assert error.type == "conclusion_requires_inspected_primary_component"
