"""Selection is scoped to registered coordinators and their investigators."""

import pytest

from server.app.errors import InvalidConfigError
from server.app.quality_audit_definition import parse_input


def payload(selection, attributes=None):
    return {"root_path": "checkout", "commit_hash": "a" * 40,
        "attributes": attributes or ["maintainability"], "maintainability_selection": selection}


def test_selection_derives_required_coordinators_without_exposing_a_manager_toggle():
    parsed = parse_input(payload({"modularity": ["responsibility"]}))
    assert parsed.request.dimensions == ["modularity"]
    assert parsed.request.investigator_selection == {"modularity": ["responsibility"]}


@pytest.mark.parametrize("selection", [
    {}, {"maintainability_manager": []}, {"modularity": ["abstraction"]},
    {"modularity": ["responsibility", "responsibility"]}, {"unknown": []},
])
def test_invalid_or_cross_coordinator_selection_is_rejected(selection):
    with pytest.raises(InvalidConfigError):
        parse_input(payload(selection))


def test_selection_requires_the_maintainability_attribute():
    with pytest.raises(InvalidConfigError):
        parse_input(payload({"modularity": []}, ["security"]))
