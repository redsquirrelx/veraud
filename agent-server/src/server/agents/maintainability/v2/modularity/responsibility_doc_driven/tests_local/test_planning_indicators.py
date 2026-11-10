"""Local checks for ResponsibilityAgent planning indicators."""

from types import SimpleNamespace

from server.agents.maintainability.v2.modularity.responsibility_doc_driven.planning import (
    build_responsibility_plan,
)
from server.agents.maintainability.v2.modularity.responsibility_doc_driven.schemas import (
    AuditRequest,
)


def _symbol(identifier, file_id, kind="function", name="fn"):
    return SimpleNamespace(id=identifier, file_id=file_id, name=name, qualified_name=name, kind=kind, start_line=1, end_line=2)


def _file(identifier, path):
    return SimpleNamespace(id=identifier, path=path, module_name=None, project_id="p", language="python", size_bytes=1, status="processed")


def test_indicators_are_whole_strings_not_characters():
    files = [_file("f0", "api/handlers.py"), _file("f1", "other/x.py"), _file("f2", "third/y.py")]
    symbols = [_symbol(f"s{i}", "f0", "function", f"fn{i}") for i in range(4)] + [
        _symbol("t0", "f1", "function", "g"), _symbol("u0", "f2", "function", "h")]
    relations = [
        SimpleNamespace(source_id="f0", target_id="f1", resolution="internal"),
        SimpleNamespace(source_id="f0", target_id="f2", resolution="internal"),
    ]
    snapshot = SimpleNamespace(
        files=files, symbols=symbols, relationships=relations, testing=[],
        coverage=SimpleNamespace(unsupported_source_languages=[], issues=[]),
        repository=SimpleNamespace(snapshot_hash="abc"),
        projects=[],
    )
    plan = build_responsibility_plan(snapshot, AuditRequest(), check=lambda: None, max_investigations=8)
    assert plan.candidates
    for candidate in plan.candidates:
        for indicator in candidate.observed_indicators:
            assert isinstance(indicator, str)
            assert len(indicator) > 1
            assert indicator != indicator[0]
        assert "Functional group" not in " ".join(candidate.observed_indicators)
    current = plan.candidates[0]
    assert any(item.startswith("Symbol composition:") for item in current.observed_indicators)
