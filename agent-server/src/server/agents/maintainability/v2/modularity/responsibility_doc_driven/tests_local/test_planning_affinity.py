"""Capability-affinity anchors explicit documented claims to selected candidates."""

from types import SimpleNamespace

from server.agents.architecture_context.schemas import KnowledgeClaim, KnowledgeEvidence
from server.agents.maintainability.v2.modularity.responsibility_doc_driven.planning import (
    _capability_affinity,
    build_responsibility_plan,
)
from server.agents.maintainability.v2.modularity.responsibility_doc_driven.schemas import (
    AuditRequest,
    ResponsibilityCandidate,
)


def _symbol(identifier, file_id, kind="function", name="fn"):
    return SimpleNamespace(id=identifier, file_id=file_id, name=name, qualified_name=name, kind=kind, start_line=1, end_line=2)


def _file(identifier, path):
    return SimpleNamespace(id=identifier, path=path, module_name=None, project_id="p", language="python", size_bytes=1, status="processed")


def _snapshot(files, symbols, relationships=()):
    return SimpleNamespace(
        files=files, symbols=symbols, relationships=list(relationships), testing=[],
        coverage=SimpleNamespace(unsupported_source_languages=[], issues=[]),
        repository=SimpleNamespace(snapshot_hash="abc"),
        projects=[],
    )


def _claim(subject, statement, related=(), category="responsibilities", certainty="explicit"):
    return KnowledgeClaim(
        category=category,
        subject=subject,
        statement=statement,
        related_subjects=list(related),
        certainty=certainty,
        section_ids=["section-1"],
        reasoning="Extracted documentary obligation.",
        constraint="unspecified",
        evidence=[KnowledgeEvidence(section_id="section-1", start_line=1, end_line=5, quote="quote")])


def _documented(claim, index=0):
    return SimpleNamespace(knowledge=[claim], section_paths={"section-1": "docs/architecture.md"},
        document_index=None, consulted_documents=[])


def _candidate(identifier, path):
    return ResponsibilityCandidate(
        id=identifier, scope=[path], primary_component=path,
        observed_indicators=["structural signal."],
        question=f"Does {path} keep one responsibility?",
        evidence_needed=["Contrast documented purpose with implementations"],
        document_claim_ids=[])


def _system():
    files = [_file("f0", "src/metropulse/storage/alerts.py"), _file("f1", "src/metropulse/bootstrap.py")]
    symbols = [_symbol("s0", "f0", "class", "MemoryNotifications"), _symbol("s1", "f0", "class", "MemoryWorkOrders"),
        _symbol("s2", "f1", "class", "Services"), _symbol("s3", "f0", "method", "send"), _symbol("s4", "f1", "function", "build_services")]
    relationships = [SimpleNamespace(source_id="f1", target_id="f0", resolution="internal")]
    snapshot = _snapshot(files, symbols, relationships)
    return snapshot, files


def test_affinity_anchors_capability_claim_to_selected_component():
    snapshot, _files = _system()
    plan = build_responsibility_plan(
        snapshot,
        AuditRequest().model_copy(update={"documented_architecture": _documented(
            _claim("Notification and work-order adapters",
                "Notification and work-order adapters implement transport/recording, not decision logic.",
                related=["Notification adapters", "work-order adapters"]))}),
        check=lambda: None, max_investigations=21)
    storage = next(item for item in plan.candidates if item.primary_component == "src/metropulse/storage/alerts.py")
    assert storage.document_claim_ids == ["claim-0"]
    assert "claim-0" in plan.document_claims
    assert plan.document_claims["claim-0"].status == "applicable"
    assert "affinity" in plan.document_claims["claim-0"].reason


def test_affinity_anchors_strong_module_match():
    files = [_file("f0", "src/metropulse/alerts/maintenance_triage.py"), _file("f1", "src/metropulse/bootstrap.py")]
    symbols = [_symbol("s0", "f0", "function", "work_order_priority"), _symbol("s1", "f0", "function", "init"),
        _symbol("s2", "f1", "class", "Services"), _symbol("s3", "f1", "function", "build_services"),
        _symbol("s4", "f0", "function", "scale_factor")]
    relationships = [SimpleNamespace(source_id="f1", target_id="f0", resolution="internal")]
    claim = _claim("Fleet maintenance capability",
        "Fleet maintenance takes vehicle condition measurements as input and produces priority decisions and work orders.")
    _snapshot(files, symbols, relationships)
    candidates = [_candidate("i-triage", "src/metropulse/alerts/maintenance_triage.py"),
        _candidate("i-bootstrap", "src/metropulse/bootstrap.py")]
    from collections import defaultdict
    by_file = defaultdict(list)
    for symbol in symbols:
        by_file[symbol.file_id].append(symbol)
    attached = _capability_affinity(claim, candidates, {file.id: file for file in files}, by_file)
    assert [candidate_id for candidate_id, _score in attached] == ["i-triage"]


def test_affinity_anchors_directory_segment_only_match():
    files = [_file("f0", "src/metropulse/fares/quote.py"), _file("f1", "src/metropulse/bootstrap.py")]
    symbols = [_symbol("s0", "f0", "class", "FareQuoteEngine"), _symbol("s1", "f0", "method", "quote"),
        _symbol("s2", "f1", "class", "Services"), _symbol("s3", "f1", "function", "build_services")]
    relationships = [SimpleNamespace(source_id="f1", target_id="f0", resolution="internal")]
    claim = _claim("Fares rules", "Fares rules.", related=()) # Only the directory-segment token can match fares/.
    _snapshot(files, symbols, relationships)
    candidates = [_candidate("i-quote", "src/metropulse/fares/quote.py"),
        _candidate("i-bootstrap", "src/metropulse/bootstrap.py")]
    from collections import defaultdict
    by_file = defaultdict(list)
    for symbol in symbols:
        by_file[symbol.file_id].append(symbol)
    attached = _capability_affinity(claim, candidates, {file.id: file for file in files}, by_file)
    assert [candidate_id for candidate_id, _score in attached] == ["i-quote"]


def test_capability_affinity_respects_per_candidate_cap():
    files = [_file("f0", "src/metropulse/alerts/dispatcher.py"), _file("f1", "src/metropulse/bootstrap.py")]
    symbols = [_symbol("s0", "f0", "class", "AlertDispatcher"), _symbol("s1", "f0", "method", "dispatch"),
        _symbol("s2", "f1", "class", "Services"), _symbol("s3", "f1", "function", "build_services"),
        _symbol("s4", "f0", "method", "init")]
    relationships = [SimpleNamespace(source_id="f1", target_id="f0", resolution="internal")]
    plan = build_responsibility_plan(
        _snapshot(files, symbols, relationships),
        AuditRequest().model_copy(update={"documented_architecture": SimpleNamespace(
            knowledge=[
                _claim("Logistics coordination",
                    "Coordinate dispatch of disruption alerts for passengers."),
                _claim("Driver support",
                    "Passenger alerts for drivers."),
            ],
            section_paths={"section-1": "docs/architecture.md"}, document_index=None,
            consulted_documents=[])}),
        check=lambda: None, max_investigations=21, max_documentary_claims_per_candidate=1)
    dispatcher = next(item for item in plan.candidates if item.primary_component == "src/metropulse/alerts/dispatcher.py")
    assert dispatcher.document_claim_ids == ["claim-0"]
    assert any("dropped by per-candidate cap 1" in item for item in plan.limitations)


def test_affinity_does_not_invent_an_owner_for_unrelated_words():
    files = [_file("f0", "src/metropulse/fares/quote.py")]
    symbols = [_symbol("s0", "f0", "class", "FareQuoteEngine"), _symbol("s1", "f0", "method", "quote")]
    claim = _claim("Lunar navigation", "Fully unrelated phrase with no index intersection.")
    candidates = [_candidate("i-quote", "src/metropulse/fares/quote.py")]
    from collections import defaultdict
    by_file = defaultdict(list)
    for symbol in symbols:
        by_file[symbol.file_id].append(symbol)
    attached = _capability_affinity(claim, candidates, {file.id: file for file in files}, by_file)
    assert attached == []


def test_unanchored_explicit_claim_is_visible_in_limitations():
    snapshot, _files = _system()
    plan = build_responsibility_plan(
        snapshot,
        AuditRequest().model_copy(update={"documented_architecture": _documented(
            _claim("Lunar navigation", "Fully unrelated phrase with no index intersection."))}),
        check=lambda: None, max_investigations=21)
    assert any("Documentation diagnostics" in item for item in plan.limitations)
