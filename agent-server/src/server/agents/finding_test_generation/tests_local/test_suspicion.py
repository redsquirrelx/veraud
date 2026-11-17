"""Heuristic suspicions about generated tests.

Flags are advisory diagnostics only; the pipeline never lets them invalidate
or delete a test by themselves. Final validity always depends on execution
and the declared oracle.
"""

from pathlib import Path

from server.agents.finding_test_generation.input_adapter import load_audit_document
from server.agents.finding_test_generation.planning import plan_verifications
from server.agents.finding_test_generation.test_templates import render_test_file
from server.runtimes.verification.tools.suspicion import suspicion_flags

FIXTURE = Path(__file__).resolve().parents[5] / "fixtures" / "audit_140" / "findings.json"


def _planned_specs():
    document, _ = load_audit_document(FIXTURE)
    specs, _ = plan_verifications(document)
    return specs


def test_templates_never_trip_suspicion():
    """The deterministic renderers must never produce suspected tests."""
    for spec in _planned_specs():
        content = render_test_file(spec)[1]
        flags = suspicion_flags(content, [spec.target_components[0]] if spec.target_components else [])
        assert flags == [], f"template tripped suspicion for {spec.verification_id}: {flags}"


def test_patching_the_subject_is_flagged():
    source = (
        "from unittest.mock import patch\n\n"
        "def test_subject():\n"
        "    with patch('urbanmesh.domain.policies.quality.ThresholdQualityRule.assess') as mocked:\n"
        "        mocked.return_value = 'accepted'\n"
        "        assert True\n"
    )
    flags = suspicion_flags(source, ["src/urbanmesh/domain/policies/quality.py"])
    assert any("patch" in flag for flag in flags)


def test_asserts_on_mocks_alone_are_flagged():
    source = (
        "from unittest.mock import MagicMock\n\n"
        "def test_subject():\n"
        "    store = MagicMock()\n"
        "    store.save(1)\n"
        "    assert store.save.call_count == 1\n"
        "    assert store.save.called\n"
    )
    flags = suspicion_flags(source, ["src/northwind/application/order_service.py"])
    assert any("mock behaviour" in flag for flag in flags)


def test_test_never_touching_subject_is_flagged():
    source = "from unittest.mock import MagicMock\n\ndef test_x():\n    m = MagicMock()\n    assert bool(m)\n"
    flags = suspicion_flags(source, ["src/northwind/domain/policies.py"])
    assert flags


def test_clean_template_variant_is_not_flagged():
    source = (
        "from _suite_helpers import scan_scope\n\n"
        "SCOPE = 'src/northwind/domain'\n"
        "FORBIDDEN_ROOTS = ('northwind.infrastructure',)\n\n"
        "def test_northwind_scan():\n"
        "    offenders = scan_scope(SCOPE, FORBIDDEN_ROOTS)\n"
        "    assert not offenders, f'Boundary violated: {offenders}'\n"
    )
    flags = suspicion_flags(source, ["src/northwind/domain"])
    assert flags == []
