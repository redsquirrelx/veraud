"""Code-first variation seeds: structural surface discovery without documentation."""

from types import SimpleNamespace

from server.agents.maintainability.v2.reusability.reuse_parametrization_doc_driven.planning import (
    build_parametrization_plan,
)
from server.agents.maintainability.v2.reusability.reuse_parametrization_doc_driven.schemas import (
    ReuseParametrizationDocDrivenRequest,
)


def _symbol(identifier, file_id, kind, name, qualified_name=None, base_names=()):
    return SimpleNamespace(
        id=identifier, file_id=file_id, name=name,
        qualified_name=qualified_name if qualified_name is not None else name,
        kind=kind, start_line=1, end_line=3, base_names=list(base_names))


def _file(identifier, path):
    return SimpleNamespace(id=identifier, path=path, module_name=None, project_id="p", language="python",
        size_bytes=1, status="processed")


def _snapshot(files, symbols, relationships=()):
    return SimpleNamespace(
        files=files, symbols=symbols, relationships=list(relationships), testing=[],
        coverage=SimpleNamespace(unsupported_source_languages=[], issues=[]),
        repository=SimpleNamespace(snapshot_hash="abc"),
        projects=[],
    )


def _system():
    files = [
        _file("f-gates", "src/app/ports/gates.py"),
        _file("f-adapters", "src/app/integrations/adapters.py"),
        _file("f-worker", "src/app/services/worker.py"),
        _file("f-root", "src/app/bootstrap.py"),
    ]
    symbols = [
        _symbol("s-gate", "f-gates", "class", "Gate", base_names=("Protocol",)),
        _symbol("s-gate-m", "f-gates", "method", "send", qualified_name="Gate.send"),
        _symbol("s-adapter", "f-adapters", "class", "RawGateAdapter", base_names=[]),
        _symbol("s-adapter-m", "f-adapters", "method", "send", qualified_name="RawGateAdapter.send"),
        _symbol("s-clean", "f-adapters", "class", "ManagedGateAdapter", base_names=[]),
        _symbol("s-clean-m", "f-adapters", "method", "send", qualified_name="ManagedGateAdapter.send"),
        _symbol("s-worker", "f-worker", "class", "Worker"),
        _symbol("s-worker-m", "f-worker", "method", "run", qualified_name="Worker.run"),
        _symbol("s-root-m", "f-root", "function", "build_app"),
    ]
    relationships = [
        SimpleNamespace(source_id="f-worker", target_id="f-adapters", resolution="internal", kind="from_import"),
        SimpleNamespace(source_id="f-root", target_id="f-adapters", resolution="internal", kind="from_import"),
    ]
    return _snapshot(files, symbols, relationships)


def test_code_first_seeds_adapter_and_consumer_without_documentation():
    snapshot = _system()
    request = ReuseParametrizationDocDrivenRequest()

    plan = build_parametrization_plan(snapshot, request, check=lambda: None,
        max_investigations=32, max_documentary_claims_per_candidate=6)

    by_primary = {candidate.primary_component: candidate for candidate in plan.candidates}
    adapter = by_primary["src/app/integrations/adapters.py"]
    consumer = by_primary["src/app/services/worker.py"]
    assert adapter.variation_mechanism == "Gate substitution"
    assert adapter.variation_basis == "inferred"
    assert sorted(adapter.alternatives) == ["ManagedGateAdapter", "RawGateAdapter"]
    assert adapter.document_claim_ids == []
    assert consumer.variation_mechanism == "Gate substitution"
    assert sorted(consumer.alternatives) == ["ManagedGateAdapter", "RawGateAdapter"]
    assert consumer.document_claim_ids == []
    # Composition roots only wire concrete adapters; they are never substituted.
    assert "src/app/bootstrap.py" not in by_primary


def test_code_first_seeds_without_any_documentation_still_find_variation_points():
    snapshot = _system()
    request = ReuseParametrizationDocDrivenRequest()  # No documented_architecture at all.

    plan = build_parametrization_plan(snapshot, request, check=lambda: None,
        max_investigations=32, max_documentary_claims_per_candidate=6)

    assert any(candidate.variation_basis == "inferred" for candidate in plan.candidates)
