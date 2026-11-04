"""Model responses heal deterministically: unknown keys are pruned and audited."""

import warnings

from server.project_analysis.project_architecture.schemas import (
    ArchitectureDiagram,
)
from server.runtimes.repository.responses import normalize_record_arrays
from server.services.repository_analysis import RepositoryAnalysisService


def test_prunes_nested_and_array_extras_with_paths():
    schema = {
        "properties": {
            "name": {"type": "string"},
            "tags": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"label": {"type": "string"}},
                },
            },
            "meta": {
                "type": "object",
                "properties": {"level": {"type": "integer"}},
            },
        }
    }
    value = {
        "name": "core",
        "comment": "looks layered",
        "tags": [{"label": "a", "score": 1}, {"label": "b"}],
        "meta": {"level": 2, "hint": "x"},
    }
    pruned, dropped = normalize_record_arrays(value, schema)
    assert pruned == {
        "name": "core",
        "tags": [{"label": "a"}, {"label": "b"}],
        "meta": {"level": 2},
    }
    assert set(dropped) == {"comment", "tags[0].score", "meta.hint"}


def test_keeps_free_form_maps_and_singleton_arrays():
    schema = {
        "properties": {
            "repairs": {"type": "object"},
            "calls": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
            },
        }
    }
    value = {"repairs": {"a.py": "b.py"}, "calls": {"name": "read"}}
    pruned, dropped = normalize_record_arrays(value, schema)
    assert pruned == {"repairs": {"a.py": "b.py"}, "calls": [{"name": "read"}]}
    assert dropped == ()


def test_diagram_with_extras_validates():
    value, dropped = normalize_record_arrays(
        {
            "title": "Components",
            "scope": "repo",
            "nodes": [{"id": "core", "unit_ref": "/organization/0", "weight": 3}],
            "summary": "one service",
        },
        ArchitectureDiagram.model_json_schema(),
    )
    assert set(dropped) == {"nodes[0].weight", "summary"}
    diagram = ArchitectureDiagram.model_validate(value)
    assert diagram.title == "Components" and len(diagram.nodes) == 1


def test_snapshot_ignores_invalid_escape_warnings(tmp_path):
    (tmp_path / "regex_tools.py").write_text(
        'import re\nPATTERN = "\\d+\\.\\%_done"\nSPACE = "a\\ b"\n',
        encoding="utf-8",
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        snapshot = RepositoryAnalysisService().analyze_sync(tmp_path)
    assert [w for w in caught if issubclass(w.category, SyntaxWarning)] == []
    assert any(source.path == "regex_tools.py" for source in snapshot.files)
