"""Synthetic inputs for the probe acceptance tests: a tiny repo and findings export."""

import json
from pathlib import Path

COMMIT = "a" * 40

MODULE_BODY = '''"""Synthetic example module with a denounced condition."""

import datetime


def tag() -> str:
    return f"ts:{datetime.datetime.now().isoformat()}"


def upper(value: str) -> str:
    return value.upper()
'''

PYPROJECT = '''[project]
name = "synthetic-probe-fixture"
version = "0.1.0"
requires-python = ">=3.11"

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
'''


def make_repo(root: Path) -> Path:
    (root / "src" / "syntheticproj").mkdir(parents=True)
    (root / "src" / "syntheticproj" / "mod.py").write_text(MODULE_BODY, encoding="utf-8")
    (root / "src" / "syntheticproj" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_smoke.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    return root


def make_findings(path: Path, *, count: int = 1) -> Path:
    findings = []
    for index in range(1, count + 1):
        findings.append({
            "id": f"barrier:clock-{index}",
            "title": "Direct dependency on the system clock",
            "description": "mod.tag reads the wall clock directly; tests cannot control time.",
            "criterion_id": "test-controllability",
            "kind": "violation",
            "components": ["src/syntheticproj/mod.py"],
            "evidence_ids": [f"retrieval:{index:024d}"],
            "justification": "tag() calls datetime.datetime.now() internally; there is no way to inject a clock.",
            "modularity_impact": "Tests of time-dependent behaviour cannot be made independent of the host clock.",
            "severity": "medium",
            "confidence": 0.9,
            "recommendation": "Accept a clock/time provider via the constructor.",
            "document_claim_ids": [],
            "evidence": [{
                "id": f"retrieval:{index:024d}",
                "kind": "source",
                "path": "src/syntheticproj/mod.py",
                "start_line": 7,
                "end_line": 8,
                "content_hash": "c" * 64,
                "commit": COMMIT,
                "snapshot_hash": "d" * 64,
            }],
            "validation_status": "insufficient_evidence",
        })
    payload = {
        "repository_id": "synthetic-repo",
        "commit": COMMIT,
        "snapshot_hash": "d" * 64,
        "objective": "Investigate test controllability",
        "findings": findings,
        "hypotheses": [],
        "missing_information": [],
        "limitations": [],
        "termination_reason": "investigations_completed",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


PLAN_REPLY = """{
  "verifications": [
    {
      "title": "Clock source is directly the system clock",
      "condition": "mod.tag() calls datetime.datetime.now() directly without an injectable clock",
      "strategy": "static_ast",
      "target_components": ["src/syntheticproj/mod.py"],
      "property": "The module binds the wall clock at call time with no injection seam",
      "scenarios": ["inspect the source of syntheticproj.mod"],
      "violation_oracle": "the source references datetime.datetime.now() with no injected time provider",
      "fixed_oracle": "a time provider can be supplied by the caller and used by tag()",
      "limits": ["static check; does not prove the absence of other clocks"],
      "test_name": "test_mod_clock_dependency"
    }
  ],
  "notes": []
}"""

VIOLATION_TEST = '''"""Verification: mod.tag must not read the wall clock without a seam.

The finding ids are recorded in manifest.json; this assertion measures the
condition, not the auditor's recommended fix.
"""
import os
from pathlib import Path


def test_mod_clock_dependency():
    root = Path(os.environ.get("TALLERCITO_REPO_ROOT", Path(__file__).resolve().parents[2]))
    source = (root / "src/syntheticproj/mod.py").read_text(encoding="utf-8")
    assert "datetime.datetime.now()" not in source, "tag() reads the wall clock directly"
'''

BROKEN_TEST = "import syntheticproj_does_not_exist_xyz\n\ndef test_mod_clock_dependency():\n    assert False\n"

REPAIRED_TEST = '''"""Verification: mod.tag binds the wall clock at call time."""
import os
from pathlib import Path


def test_mod_clock_dependency():
    root = Path(os.environ.get("TALLERCITO_REPO_ROOT", Path(__file__).resolve().parents[2]))
    source = (root / "src/syntheticproj/mod.py").read_text(encoding="utf-8")
    assert "datetime.datetime.now()" in source, "expected the current call pattern to be present"
'''
