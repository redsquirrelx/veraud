"""Local checks for TestControllabilityAgent deterministic planning indicators.

The scan flags exploratory signals only; these checks pin the generalized
categories so refactors keep distinguishing controlability-relevant signals
from test files and domain value constructors.
"""

from server.agents.maintainability.v2.testability.test_controllability_doc_driven.planning import (
    _scan_source,
    nonproduction_path,
)

SOURCE = """
import secrets
from datetime import date
import threading

class ReportService:
    def generate(self, submitted_on):
        if submitted_on > date.today():
            raise ValueError("future_submission")
        return secrets.token_hex(4)

def schedule(job):
    timer = threading.Timer(60, job)
    timer.start()
"""

JS_SOURCE = """
export function mintId() {
  return crypto.randomUUID();
}
"""

BENIGN_SOURCE = """
from civitaspermit.domain.models import Permit

def make(category):
    return Permit(category=category)
"""


def test_scan_flags_time_randomness_and_scheduling():
    hits = _scan_source("src/service.py", SOURCE, language="python")
    categories = {category for category, _line, _snippet in hits}
    assert "uncontrolled-time" in categories
    assert "nondeterminism" in categories
    assert "async-control" in categories


def test_scan_flags_javascript_randomness():
    hits = _scan_source("src/service.ts", JS_SOURCE, language="typescript")
    categories = {category for category, _line, _snippet in hits}
    assert "nondeterminism" in categories


def test_scan_ignores_domain_value_constructors():
    hits = _scan_source("src/domain/service.py", BENIGN_SOURCE, domain_names={"Permit"}, language="python")
    assert not [hit for hit in hits if hit[0] == "construction-coupling" or hit[0] == "global-state"]


def test_test_paths_are_not_production_candidates():
    assert nonproduction_path("tests/test_service.py")
    assert nonproduction_path("src/pkg/fixtures/service.py")
    assert not nonproduction_path("src/pkg/application/service.py")
