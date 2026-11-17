"""Cross-fixture verification of all eight rules on a second synthetic project.

The project is `northwind` â€” an invented package whose layout (src/northwind,
domain/application/infrastructure layers, plugins/, core private module) differs
from the audit-140 synthetic fixture. Each rule runs RED against the violating
checkout and GREEN against the fixed one. No file or name here relates to
urbanmesh; rules must not carry fixture-specific assumptions.

The synthetic repositories are written to a temporary directory; the real
workspace checkout is never touched.
"""

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from server.agents.finding_test_generation.input_adapter import load_audit_document
from server.agents.finding_test_generation.packaging import build_suite
from server.agents.finding_test_generation.schemas import (
    RuleSource,
    ValidationRecord,
    VerificationSpec,
)

FIXTURE = Path(__file__).resolve().parents[5] / "fixtures" / "audit_140" / "findings.json"

VIOLATING = {
    "src/northwind/domain/policies.py": (
        '"""Domain policies must not know the persistence layer."""\n'
        "import os\n"
        "from northwind.infrastructure import storage\n\n"
        "CACHE_DIR = os.environ.get('NORTHWIND_CACHE')\n\n\n"
        "def sweep():\n"
        "    return storage.scan()\n"
    ),
    "src/northwind/domain/result.py": (
        '"""Mutually dependent domain modules."""\n'
        "import northwind.domain.helper\n\n\n"
        "def evaluate():\n"
        "    return True\n"
    ),
    "src/northwind/domain/helper.py": (
        '"""Imported by result.py."""\n'
        "import northwind.domain.result\n\n\n"
        "def assist():\n"
        "    return True\n"
    ),
    "src/northwind/application/order_service.py": (
        '"""Application service layer."""\n'
        "import sqlalchemy\n"
        "from northwind.infrastructure import storage\n"
        "from northwind.core import api\n"
        "from northwind.core import _cache\n\n\n"
        "def place(order):\n"
        "    return api._items, storage.save(order), _cache.read()\n"
    ),
    "src/northwind/application/discount_service.py": (
        '"""Application service layer, framework-free variant."""\n'
        "from northwind.infrastructure import storage\n\n\n"
        "def refund(order):\n"
        "    return storage.save(order)\n"
    ),
    "src/northwind/infrastructure/storage.py": (
        '"""Infrastructure layer."""\n'
        "def save(order):\n"
        "    return order\n\n"
        "def scan():\n"
        "    return 0\n"
    ),
    "src/northwind/core/api.py": (
        '"""Public core API; consumers must not touch _items."""\n'
        "_items = {}\n\n"
        "def put(key, value):\n"
        "    _items[key] = value\n"
    ),
    "src/northwind/core/_cache.py": (
        '"""Private cache; outside modules must not import this."""\n'
        "def read():\n"
        "    return {}\n"
    ),
    "src/northwind/application/refund_gate.py": (
        '"""Refund gate that side-effects through a collaborator."""\n'
        "class RefundGate:\n"
        "    def __init__(self, persistence):\n"
        '        self._persistence = persistence\n'
        "    def assess(self, order):\n"
        "        if self._persistence.save(order):\n"
        '            return "approved"\n'
        '        return "rejected"\n'
    ),
    "src/northwind/domain/helpers.py": (
        '"""A module without assess-like variants."""\n'
        "VALUE = 1\n"
    ),
    "src/northwind/domain/ghost.py": (
        '"""Requires a third-party package the suite lacks."""\n'
        "import sqlalchemy\n\n\n"
        "def summon(case):\n"
        "    return 'ok' if case else 'rejected'\n"
    ),
    "src/northwind/domain/dead_branch.py": (
        '"""Branches with distinct vocabularies; one is never reachable."""\n\n\n'
        "class GuardedRule:\n"
        "    def assess(self, case):\n"
        "        if isinstance(case, int) and case > 100:\n"
        "            return 'hold'\n"
        "        return 'accepted'\n\n\n"
        "class PlainRule:\n"
        "    def assess(self, case):\n"
        "        return 'accepted'\n"
    ),

    "src/northwind/domain/variants.py": (
        '"""Variants with disjoint state vocabularies."""\n\n\n'
        "class StrictRule:\n"
        "    def assess(self, case):\n"
        "        if case:\n"
        "            return 'ok'\n"
        "        return 'rejected'\n\n\n"
        "class LooseRule:\n"
        "    def assess(self, case):\n"
        "        if case:\n"
        "            return 'PASS'\n"
        "        return 'FAIL'\n"
    ),
}

FIXED = {
    "src/northwind/application/refund_gate.py": (
        '"""Refund gate without collaborator invocation."""\n'
        "class RefundGate:\n"
        "    def __init__(self, persistence):\n"
        '        self._persistence = persistence\n'
        "    def assess(self, order):\n"
        '        return "rejected"\n'
    ),
    "src/northwind/domain/policies.py": (
        '"""Dependency injected via the composition root."""\n'
        "\n\n"
        "def sweep(storage):\n"
        "    return storage.scan()\n"
    ),
    "src/northwind/domain/result.py": (
        '"""Domain module with no mutual imports."""\n'
        "\n\n"
        "def evaluate():\n"
        "    return True\n"
    ),
    "src/northwind/application/order_service.py": (
        '"""Application service layer."""\n'
        "from northwind.core import api\n\n\n"
        "def place(order):\n"
        "    return api.count()\n"
    ),
    "src/northwind/application/discount_service.py": (
        '"""Application service layer."""\n'
        "from northwind.domain.result import evaluate\n\n\n"
        "def refund(order):\n"
        "    return evaluate()\n"
    ),
    "src/northwind/domain/variants.py": (
        '"""Variants sharing a state vocabulary."""\n\n\n'
        "class StrictRule:\n"
        "    def assess(self, case):\n"
        "        if case:\n"
        "            return 'ok'\n"
        "        return 'rejected'\n\n\n"
        "class LooseRule:\n"
        "    def assess(self, case):\n"
        "        if case:\n"
        "            return 'ok'\n"
        "        return 'rejected'\n"
    ),
    "src/northwind/core/api.py": (
        '"""Public core API."""\n'
        "_items = {}\n\n\n"
        "def put(key, value):\n"
        "    _items[key] = value\n\n\n"
        "def count():\n"
        "    return len(_items)\n"
    ),
}

STRUCTURAL = {
    "pyproject.toml": '[project]\nname = "northwind"\nversion = "0.1.0"\nrequires-python = ">=3.10"\n',
}


def _write_tree(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")


def _spec(verification_id: str, rule_kind: str, components: list[str], scope: str,
          test_name: str, rule_params: dict | None = None) -> VerificationSpec:
    return VerificationSpec(
        finding_id="ns-0000",
        verification_id=verification_id,
        title=test_name.replace("_", " "),
        rule_source=RuleSource(document_claim_ids=["doc-claim-ns-1"], evidence_ids=[]),
        target_components=components,
        property="architecture boundary",
        strategy="static_ast",
        scenarios=["structural check"],
        violation_oracle="asserted by the suite",
        fixed_oracle="asserted by the suite",
        limits=["structural scope only"],
        source_scope=scope,
        test_scenario_scope=scope,
        test_path=f"tests/test_{test_name}.py",
        test_name=f"test_{test_name}",
        rule_kind=rule_kind,
        rule_params=rule_params or {},
    )


def _run_suite(tmp_path: Path, spec: VerificationSpec, fixed: bool) -> tuple[int, dict]:
    generation_status = "generated"
    if fixed:
        # Establish actual sensitivity before allowing a passing control to be approved.
        baseline_code, baseline_report = _run_suite(tmp_path, spec, False)
        if baseline_code == 1 and baseline_report["verifications"][0]["status"] == "VIOLATION_PRESENT":
            generation_status = "validated_red"
    document, _ = load_audit_document(FIXTURE)
    repo = tmp_path / ("fixed-repo" if fixed else "red-repo")
    repo.mkdir()
    tree = dict(STRUCTURAL)
    if fixed:
        tree.update(VIOLATING)
        tree.update(FIXED)
    else:
        tree.update(VIOLATING)
    _write_tree(repo, tree)
    records = [ValidationRecord(verification_id=spec.verification_id, status=generation_status)]
    zip_path = tmp_path / ("fixed.zip" if fixed else "red.zip")
    build_suite(document, [spec], records, [], zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(repo)
    result = subprocess.run([sys.executable, str(repo / ".tallercito" / "runner.py")],
                            cwd=repo, capture_output=True, text=True, check=False, timeout=300)
    report_path = repo / ".tallercito" / "results" / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    return result.returncode, report


@pytest.mark.parametrize("fixed,expected", [(False, 1), (True, 0)])
def test_layer_import_rule(tmp_path, fixed, expected):
    spec = _spec(
        "ns-001", "layer_import",
        ["src/northwind/domain/policies.py", "src/northwind/infrastructure/storage.py"],
        "src/northwind/domain", "layer_import_check",
    )
    code, report = _run_suite(tmp_path, spec, fixed)
    assert code == expected, report


@pytest.mark.parametrize("fixed,expected", [(False, 1), (True, 0)])
def test_forbidden_framework_rule(tmp_path, fixed, expected):
    spec = _spec(
        "ns-002", "forbidden_framework_in_layer",
        ["src/northwind/application/order_service.py"],
        "src/northwind/application", "framework_import_check",
        rule_params={"forbidden_roots": ["sqlalchemy"]},
    )
    code, report = _run_suite(tmp_path, spec, fixed)
    assert code == expected, report


@pytest.mark.parametrize("fixed,expected", [(False, 1), (True, 0)])
def test_restricted_import_rule(tmp_path, fixed, expected):
    spec = _spec(
        "ns-003", "restricted_import",
        ["src/northwind/application/discount_service.py"],
        "src/northwind/application", "restricted_import_check",
        rule_params={"allowed_roots": ["northwind.domain", "northwind.core"]},
    )
    code, report = _run_suite(tmp_path, spec, fixed)
    assert code == expected, report


@pytest.mark.parametrize("fixed,expected", [(False, 1), (True, 0)])
def test_private_module_rule(tmp_path, fixed, expected):
    spec = _spec(
        "ns-004", "private_module_access",
        ["src/northwind/application/order_service.py", "src/northwind/core/_cache.py"],
        "src/northwind/application", "private_module_check",
    )
    code, report = _run_suite(tmp_path, spec, fixed)
    assert code == expected, report


@pytest.mark.parametrize("fixed,expected", [(False, 1), (True, 0)])
def test_private_attribute_rule(tmp_path, fixed, expected):
    spec = _spec(
        "ns-005", "private_attribute_access",
        ["src/northwind/application/order_service.py", "src/northwind/core/api.py"],
        "src/northwind", "private_attribute_check",
        rule_params={"module_prefix": "northwind.core.api"},
    )
    code, report = _run_suite(tmp_path, spec, fixed)
    assert code == expected, report


@pytest.mark.parametrize("fixed,expected", [(False, 1), (True, 0)])
def test_no_environ_rule(tmp_path, fixed, expected):
    spec = _spec(
        "ns-006", "no_environ_in_scope",
        ["src/northwind/domain/policies.py"],
        "src/northwind/domain", "no_environ_check",
    )
    code, report = _run_suite(tmp_path, spec, fixed)
    assert code == expected, report


@pytest.mark.parametrize("fixed,expected", [(False, 1), (True, 0)])
def test_circular_import_rule(tmp_path, fixed, expected):
    spec = _spec(
        "ns-007", "circular_import",
        ["src/northwind/domain/result.py"],
        "src/northwind/domain", "circular_import_check",
    )
    code, report = _run_suite(tmp_path, spec, fixed)
    assert code == expected, report


@pytest.mark.parametrize("fixed,expected", [(False, 1), (True, 0)])
def test_contract_states_rule(tmp_path, fixed, expected):
    spec = _spec(
        "ns-008", "contract_states",
        ["src/northwind/domain/variants.py"],
        "src/northwind/domain/variants.py", "contract_states_check",
    )
    code, report = _run_suite(tmp_path, spec, fixed)
    assert code == expected, report


def test_layer_import_detects_violation_after_file_rename(tmp_path):
    """Renaming the offending module file must not hide the violation."""
    document, _ = load_audit_document(FIXTURE)
    spec = _spec(
        "ns-009", "layer_import",
        ["src/northwind/domain", "src/northwind/infrastructure/storage.py"],
        "src/northwind/domain", "layer_import_rename_check",
    )
    repo = tmp_path / "renamed-repo"
    repo.mkdir()
    tree = dict(STRUCTURAL)
    tree.update(VIOLATING)
    renamed = tree.pop("src/northwind/domain/policies.py")
    tree["src/northwind/domain/renamed_policies.py"] = renamed
    _write_tree(repo, tree)
    records = [ValidationRecord(verification_id=spec.verification_id, status="generated")]
    zip_path = tmp_path / "renamed.zip"
    build_suite(document, [spec], records, [], zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(repo)
    result = subprocess.run([sys.executable, str(repo / ".tallercito" / "runner.py")],
                            cwd=repo, capture_output=True, text=True, check=False, timeout=300)
    assert result.returncode == 1


def test_missing_scope_reports_not_verifiable_not_violation(tmp_path):
    """A scope that vanished is a configuration failure, never a proven violation."""
    document, _ = load_audit_document(FIXTURE)
    spec = _spec(
        "ns-010", "layer_import",
        ["src/northwind/domain/policies.py", "src/northwind/infrastructure/storage.py"],
        "src/northwind/absent", "layer_import_missing_scope",
    )
    repo = tmp_path / "missing-scope-repo"
    repo.mkdir()
    tree = dict(STRUCTURAL)
    tree.update(VIOLATING)
    _write_tree(repo, tree)
    records = [ValidationRecord(verification_id=spec.verification_id, status="generated")]
    zip_path = tmp_path / "missing-scope.zip"
    build_suite(document, [spec], records, [], zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(repo)
    subprocess.run([sys.executable, str(repo / ".tallercito" / "runner.py")],
                            cwd=repo, capture_output=True, text=True, check=False, timeout=300)
    report_path = repo / ".tallercito" / "results" / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    item = next(entry for entry in report["verifications"] if entry["verification_id"] == spec.verification_id)
    assert item["status"] == "EXECUTION_ERROR"


def test_alias_import_of_forbidden_layer_is_detected(tmp_path):
    """`import pkg.x as y` is not a legal way around a layer boundary."""
    document, _ = load_audit_document(FIXTURE)
    spec = _spec(
        "ns-011", "layer_import",
        ["src/northwind/domain/policies.py", "src/northwind/infrastructure/storage.py"],
        "src/northwind/application", "layer_import_alias_check",
    )
    repo = tmp_path / "alias-layer-repo"
    repo.mkdir()
    tree = dict(STRUCTURAL)
    tree.update(VIOLATING)
    tree["src/northwind/application/alias_layer.py"] = (
        "import northwind.infrastructure.storage as store\n\n\n"
        "def probe():\n"
        "    return store.scan()\n"
    )
    _write_tree(repo, tree)
    records = [ValidationRecord(verification_id=spec.verification_id, status="generated")]
    zip_path = tmp_path / "alias-layer.zip"
    build_suite(document, [spec], records, [], zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(repo)
    subprocess.run([sys.executable, str(repo / ".tallercito" / "runner.py")],
                            cwd=repo, capture_output=True, text=True, check=False, timeout=300)
    report_path = repo / ".tallercito" / "results" / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    item = next(entry for entry in report["verifications"] if entry["verification_id"] == spec.verification_id)
    assert item["status"] == "VIOLATION_PRESENT"


def test_alias_import_of_private_attribute_is_detected(tmp_path):
    """`from pkg import api as a` then `a._items` is still a private access."""
    document, _ = load_audit_document(FIXTURE)
    spec = _spec(
        "ns-012", "private_attribute_access",
        ["src/northwind/application/alias_attr.py", "src/northwind/core/api.py"],
        "src/northwind", "private_attribute_alias_check",
        rule_params={"module_prefix": "northwind.core.api"},
    )
    repo = tmp_path / "alias-attr-repo"
    repo.mkdir()
    tree = dict(STRUCTURAL)
    tree.update(VIOLATING)
    tree["src/northwind/application/alias_attr.py"] = (
        "from northwind.core import api as core_api\n\n\n"
        "def peek():\n"
        "    return core_api._items\n"
    )
    _write_tree(repo, tree)
    records = [ValidationRecord(verification_id=spec.verification_id, status="generated")]
    zip_path = tmp_path / "alias-attr.zip"
    build_suite(document, [spec], records, [], zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(repo)
    subprocess.run([sys.executable, str(repo / ".tallercito" / "runner.py")],
                            cwd=repo, capture_output=True, text=True, check=False, timeout=300)
    report_path = repo / ".tallercito" / "results" / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    item = next(entry for entry in report["verifications"] if entry["verification_id"] == spec.verification_id)
    assert item["status"] == "VIOLATION_PRESENT"


@pytest.mark.parametrize("fixed,expected", [(False, 1), (True, 0)])
def test_dynamic_contract_states_rule(tmp_path, fixed, expected):
    spec = _spec(
        "ns-013", "contract_states_dynamic",
        ["src/northwind/domain/variants.py"],
        "src/northwind/domain", "dynamic_contract_check",
        rule_params={"method": "assess"},
    )
    code, report = _run_suite(tmp_path, spec, fixed)
    assert code == expected, report


@pytest.mark.parametrize("fixed,expected", [(False, 1), (True, 0)])
def test_dynamic_forbidden_collaborator_rule(tmp_path, fixed, expected):
    spec = _spec(
        "ns-014", "contract_states_dynamic",
        ["src/northwind/application/refund_gate.py"],
        "src/northwind/application", "dynamic_forbidden_collaborator_check",
        rule_params={"method": "assess", "forbidden_collaborators": ["persistence.save"]},
    )
    code, report = _run_suite(tmp_path, spec, fixed)
    assert code == expected, report


def test_dynamic_no_assess_variants_is_not_verifiable(tmp_path):
    """No classes exposing assess: configuration diagnosis, never a violation."""
    document, _ = load_audit_document(FIXTURE)
    spec = _spec(
        "ns-015", "contract_states_dynamic",
        ["src/northwind/domain/helpers.py"],
        "src/northwind/domain", "dynamic_no_variants_check",
        rule_params={"method": "assess"},
    )
    repo = tmp_path / "no-variants-repo"
    repo.mkdir()
    tree = dict(STRUCTURAL)
    tree.update(VIOLATING)
    _write_tree(repo, tree)
    records = [ValidationRecord(verification_id=spec.verification_id, status="generated")]
    zip_path = tmp_path / "no-variants.zip"
    build_suite(document, [spec], records, [], zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(repo)
    subprocess.run([sys.executable, str(repo / ".tallercito" / "runner.py")],
                   cwd=repo, capture_output=True, text=True, check=False, timeout=300)
    report_path = repo / ".tallercito" / "results" / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    item = next(entry for entry in report["verifications"] if entry["verification_id"] == spec.verification_id)
    assert item["status"] == "EXECUTION_ERROR"


def test_dynamic_missing_dependency_is_not_verifiable(tmp_path):
    """Suite's runner lacks sqlalchemy: EXECUTION_ERROR, never a correction."""
    document, _ = load_audit_document(FIXTURE)
    spec = _spec(
        "ns-016", "contract_states_dynamic",
        ["src/northwind/domain/ghost.py"],
        "src/northwind/domain", "dynamic_missing_dependency_check",
        rule_params={"method": "summon"},
    )
    repo = tmp_path / "missing-dep-repo"
    repo.mkdir()
    tree = dict(STRUCTURAL)
    tree.update(VIOLATING)
    _write_tree(repo, tree)
    records = [ValidationRecord(verification_id=spec.verification_id, status="generated")]
    zip_path = tmp_path / "missing-dep.zip"
    build_suite(document, [spec], records, [], zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(repo)
    subprocess.run([sys.executable, str(repo / ".tallercito" / "runner.py")],
                   cwd=repo, capture_output=True, text=True, check=False, timeout=300)
    report_path = repo / ".tallercito" / "results" / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    item = next(entry for entry in report["verifications"] if entry["verification_id"] == spec.verification_id)
    assert item["status"] == "EXECUTION_ERROR"


def test_suite_executes_in_paths_with_spaces(tmp_path):
    """Paths with spaces must behave identically to normal paths."""
    document, _ = load_audit_document(FIXTURE)
    spec = _spec(
        "ns-017", "layer_import",
        ["src/northwind/domain", "src/northwind/infrastructure/storage.py"],
        "src/northwind/domain", "layer_import_space_check",
    )
    repo = tmp_path / "h6 path with spaces repo"
    repo.mkdir()
    tree = dict(STRUCTURAL)
    tree.update(VIOLATING)
    _write_tree(repo, tree)
    records = [ValidationRecord(verification_id=spec.verification_id, status="generated")]
    zip_path = tmp_path / "space.zip"
    build_suite(document, [spec], records, [], zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(repo)
    subprocess.run([sys.executable, str(repo / ".tallercito" / "runner.py")],
                   cwd=repo, capture_output=True, text=True, check=False, timeout=300)
    report_path = repo / ".tallercito" / "results" / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    item = next(entry for entry in report["verifications"] if entry["verification_id"] == spec.verification_id)
    assert item["status"] == "VIOLATION_PRESENT"


@pytest.mark.parametrize("fixed,expected", [(False, 2), (True, 2)])
def test_never_executed_branch_is_not_a_correction(tmp_path, fixed, expected):
    """The dead branch's vocabulary is unobservable with the synthesized input.
    The suite cannot prove the invariant holds nor that the violation persists:
    status quo is 'passes both', and the gate does not ship this as proven."""
    spec = _spec(
        "ns-018", "contract_states_dynamic",
        ["src/northwind/domain/dead_branch.py"],
        "src/northwind/domain", "dynamic_dead_branch_check",
        rule_params={"method": "assess"},
    )
    code, report = _run_suite(tmp_path, spec, fixed)
    assert code == expected, report


@pytest.mark.parametrize("fixed,expected", [(False, 2), (True, 2)])
def test_never_executed_branch_static_sibling_also_passes(tmp_path, fixed, expected):
    spec = _spec(
        "ns-019", "contract_states",
        ["src/northwind/domain/dead_branch.py"],
        "src/northwind/domain", "static_dead_branch_check",
    )
    code, report = _run_suite(tmp_path, spec, fixed)
    assert code == expected, report
