"""Capability-affinity anchors explicit documented claims to selected candidates."""

from types import SimpleNamespace

from server.agents.maintainability.v2.reusability.abstraction_doc_driven.planning import (
    _capability_affinity,
    build_abstraction_plan,
)
from server.agents.maintainability.v2.reusability.abstraction_doc_driven.schemas import (
    AbstractionRequest,
)


def _claim(subject, statement, related=(), category="architectural_style", certainty="explicit"):
    return {
        "category": category,
        "subject": subject,
        "statement": statement,
        "related_subjects": list(related),
        "certainty": certainty,
        "section_ids": ["section-1"],
        "reasoning": "Documented architectural obligation.",
        "constraint": "unspecified",
        "evidence": [{"section_id": "section-1", "start_line": 1, "end_line": 5, "quote": "quote"}],
    }


def _documented(claims):
    return {
        "schema_version": "1",
        "document_index": None,
        "knowledge": claims if isinstance(claims, list) else [claims],
        "knowledge_issues": [],
        "covered_categories": [],
        "pending_categories": [],
        "evaluated_categories": [],
        "coverage_assessment_status": "not_run",
        "consulted_documents": [],
        "section_paths": {"section-1": "docs/architecture.md"},
        "validation_errors": [],
        "execution_status": "partial",
        "finalization_reason": "test",
    }


def _symbol(identifier, file_id, kind="function", name="fn", base_names=()):
    return SimpleNamespace(id=identifier, file_id=file_id, name=name, qualified_name=name,
        kind=kind, base_names=tuple(base_names), start_line=1, end_line=2)


def _file(identifier, path):
    return SimpleNamespace(id=identifier, path=path, module_name=None, project_id="p",
        language="python", size_bytes=1, status="processed")


def _snapshot(files, symbols, relationships=()):
    return SimpleNamespace(
        files=files, symbols=symbols, relationships=list(relationships), testing=[],
        coverage=SimpleNamespace(unsupported_source_languages=[], issues=[]),
        repository=SimpleNamespace(snapshot_hash="abc", root_path=".", commit="abc123"),
        projects=[],
    )


def _request(claims):
    return AbstractionRequest.model_validate({"documented_architecture": _documented(claims)})


def _system():
    files = [_file("f0", "src/metropulse/storage/alerts.py"),
        _file("f1", "src/metropulse/bootstrap.py"),
        _file("f2", "src/metropulse/notify.py"),
        _file("f3", "src/metropulse/workorders.py")]
    symbols = [
        _symbol("s0", "f0", "class", "MemoryNotifications", base_names=("Protocol",)),
        _symbol("s1", "f0", "class", "MemoryWorkOrders", base_names=("Protocol",)),
        _symbol("s2", "f1", "class", "Services"),
        _symbol("s3", "f2", "class", "SmtpNotifications", base_names=("MemoryNotifications",)),
        _symbol("s4", "f3", "class", "EmailWorkOrders", base_names=("MemoryWorkOrders",))]
    relationships = [
        SimpleNamespace(source_id="f1", target_id="f0", resolution="internal",
            id="r0", kind="import", specifier="", evidence_ids=()),
        SimpleNamespace(source_id="f2", target_id="f0", resolution="internal",
            id="r1", kind="import", specifier="", evidence_ids=()),
        SimpleNamespace(source_id="f3", target_id="f0", resolution="internal",
            id="r2", kind="import", specifier="", evidence_ids=()),
    ]
    snapshot = _snapshot(files, symbols, relationships)
    return snapshot, files


def test_affinity_anchors_capability_claim_to_selected_component():
    snapshot, _files = _system()
    plan = build_abstraction_plan(
        snapshot,
        _request(_claim("Notification and work-order adapters",
            "Notification and work-order adapters implement transport/recording, not decision logic.",
            related=["Notification adapters", "work-order adapters"])),
        check=lambda: None, max_investigations=21)
    storage = next(item for item in plan.candidates if item.primary_component == "src/metropulse/storage/alerts.py")
    assert storage.document_claim_ids == ["claim-0"]
    assert "claim-0" in plan.document_claims
    assert plan.document_claims["claim-0"].status == "applicable"
    assert "affinity" in plan.document_claims["claim-0"].reason


def test_affinity_anchors_strong_module_match():
    files = [_file("f0", "src/metropulse/alerts/maintenance_triage.py"), _file("f1", "src/metropulse/bootstrap.py")]
    symbols = [_symbol("s0", "f0", "class", "WorkOrderTriage", base_names=("Protocol",)),
        _symbol("s1", "f0", "class", "ScaleFactor", base_names=("Protocol",)),
        _symbol("s2", "f1", "class", "Services")]
    claim = _claim("Fleet maintenance capability",
        "Fleet maintenance takes vehicle condition measurements as input and produces priority decisions and work orders.")
    candidates = [SimpleNamespace(id="i-triage", primary_component="src/metropulse/alerts/maintenance_triage.py")]
    from collections import defaultdict
    by_file = defaultdict(list)
    for symbol in symbols:
        by_file[symbol.file_id].append(symbol)
    attached = _capability_affinity(claim, candidates, {file.id: file for file in files}, by_file)
    assert [candidate_id for candidate_id, _score in attached] == ["i-triage"]


def test_affinity_anchors_directory_segment_only_match():
    files = [_file("f0", "src/metropulse/fares/quote.py"), _file("f1", "src/metropulse/bootstrap.py")]
    symbols = [_symbol("s0", "f0", "class", "FareQuoteEngine", base_names=("Protocol",)),
        _symbol("s2", "f1", "class", "Services")]
    claim = _claim("Fares rules", "Fares rules.", related=())  # Only the directory-segment token can match fares/.
    candidates = [SimpleNamespace(id="i-quote", primary_component="src/metropulse/fares/quote.py")]
    from collections import defaultdict
    by_file = defaultdict(list)
    for symbol in symbols:
        by_file[symbol.file_id].append(symbol)
    attached = _capability_affinity(claim, candidates, {file.id: file for file in files}, by_file)
    assert [candidate_id for candidate_id, _score in attached] == ["i-quote"]


def test_capability_affinity_respects_per_candidate_cap():
    files = [_file("f0", "src/metropulse/alerts/dispatcher.py"), _file("f1", "src/metropulse/bootstrap.py")]
    symbols = [_symbol("s0", "f0", "class", "AlertDispatcher", base_names=("Protocol",)),
        _symbol("s2", "f1", "class", "Services"),
        _symbol("s3", "f1", "class", "VoiceAlerts", base_names=("AlertDispatcher",))]
    relationships = [SimpleNamespace(source_id="f1", target_id="f0", resolution="internal",
        id="r0", kind="import", specifier="", evidence_ids=())]
    plan = build_abstraction_plan(
        _snapshot(files, symbols, relationships),
        _request([
            _claim("Logistics coordination",
                "Coordinate dispatch of disruption alerts for passengers."),
            _claim("Driver support",
                "Passenger alerts for drivers."),
        ]),
        check=lambda: None, max_investigations=21, max_documentary_claims_per_candidate=1)
    dispatcher = next(item for item in plan.candidates if item.primary_component == "src/metropulse/alerts/dispatcher.py")
    assert dispatcher.document_claim_ids == ["claim-0"]
    assert any("dropped by per-candidate cap 1" in item for item in plan.limitations)


def test_affinity_does_not_invent_an_owner_for_unrelated_words():
    files = [_file("f0", "src/metropulse/fares/quote.py")]
    symbols = [_symbol("s0", "f0", "class", "FareQuoteEngine", base_names=("Protocol",))]
    claim = _claim("Lunar navigation", "Fully unrelated phrase with no index intersection.")
    candidates = [SimpleNamespace(id="i-quote", primary_component="src/metropulse/fares/quote.py")]
    from collections import defaultdict
    by_file = defaultdict(list)
    for symbol in symbols:
        by_file[symbol.file_id].append(symbol)
    attached = _capability_affinity(claim, candidates, {file.id: file for file in files}, by_file)
    assert attached == []


def test_unanchored_explicit_claim_is_visible_in_limitations():
    snapshot, _files = _system()
    plan = build_abstraction_plan(
        snapshot,
        _request(_claim("Lunar navigation", "Fully unrelated phrase with no index intersection.")),
        check=lambda: None, max_investigations=21)
    assert any("Documentation diagnostics" in item for item in plan.limitations)
