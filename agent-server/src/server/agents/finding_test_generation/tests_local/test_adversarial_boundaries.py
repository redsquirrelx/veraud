"""Adversarial boundary fixtures: none of these may pass by accident.

The audit-140 findings all point at one file per violation; these tests confirm
detection survives alias imports, renamed modules and moved targets, and that
the documented composition-root exception (bootstrap.py) is honoured.
"""

from pathlib import Path

from _synthetic_repo import FIXED, VIOLATING

from server.agents.finding_test_generation.input_adapter import load_audit_document
from server.agents.finding_test_generation.planning import plan_verifications
from server.agents.finding_test_generation.test_templates import render_test_file
from server.runtimes.verification.tools.sandbox import LocalSubprocessExecutor
from server.runtimes.verification.tools.test_runner import (
    CLASSIFICATION_PASS,
    CLASSIFICATION_VIOLATION,
    WorkspaceRunner,
)

FIXTURE = Path(__file__).resolve().parents[5] / "fixtures" / "audit_140" / "findings.json"


def _write_repo(root: Path, overrides: dict[str, str]) -> None:
    for relative, content in {**VIOLATING, **overrides}.items():
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")


def _run_suite(repo: Path, spec_index: int):
    document, diagnostics = load_audit_document(FIXTURE)
    assert document is not None, diagnostics.errors
    specs, _ = plan_verifications(document)
    spec = specs[spec_index]
    test_path, content = render_test_file(spec)
    destination = repo / ".tallercito" / test_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")
    runner = WorkspaceRunner(repo, executor=LocalSubprocessExecutor(), timeout_seconds=120, max_output_bytes=16_000)
    # _suite_helpers.py must also exist or the import fails (a fixture concern, not a finding).
    from server.agents.finding_test_generation.test_templates import render_helper

    helper_name, helper_content = render_helper()
    (repo / ".tallercito" / helper_name).parent.mkdir(parents=True, exist_ok=True)
    (repo / ".tallercito" / helper_name).write_text(helper_content, encoding="utf-8")
    outcome = runner.run_pytest(f".tallercito/{test_path}")
    return outcome


def test_alias_import_is_still_detected(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo, {"src/urbanmesh/application/inventory/allocator.py": (
        '"""Reserve depot stock."""\n'
        "import urbanmesh.infrastructure.storage.memory as mem\n\n"
        "class StockAllocator:\n"
        "    def __init__(self): self._impl = mem.MemoryInventoryCatalog([])\n"
    )})
    outcome = _run_suite(repo, 0)
    assert outcome.classification == CLASSIFICATION_VIOLATION


def test_renamed_adapter_is_still_detected(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo, {
        "src/urbanmesh/infrastructure/storage/memory.py": "",  # husk left behind
        "src/urbanmesh/infrastructure/storage/telemetry_store.py": VIOLATING["src/urbanmesh/infrastructure/storage/memory.py"],
        "src/urbanmesh/application/inventory/allocator.py": (
            '"""Reserve depot stock."""\n'
            "from urbanmesh.infrastructure.storage import telemetry_store\n\n"
            "class StockAllocator:\n"
            "    def __init__(self): self._impl = telemetry_store.MemoryInventoryCatalog([])\n"
        ),
    })
    outcome = _run_suite(repo, 0)
    assert outcome.classification == CLASSIFICATION_VIOLATION


def test_moved_domain_module_is_still_detected(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    moved = "src/urbanmesh/domain/reporting/recommendations.py"
    _write_repo(repo, {"src/urbanmesh/domain/recommendations.py": "", moved: VIOLATING["src/urbanmesh/domain/recommendations.py"]})
    outcome = _run_suite(repo, 1)
    assert outcome.classification == CLASSIFICATION_VIOLATION


def test_composition_root_bootstrap_is_not_flagged(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo, {
        "src/urbanmesh/application/inventory/allocator.py": (
            '"""Reserve depot stock for internal supply requests."""\n'
            "from urbanmesh.domain.errors import NotFound, Conflict\n\n"
            "class StockAllocator:\n"
            "    def __init__(self, inventory): self.inventory = inventory\n\n"
            "    def reserve(self, sku: str, quantity: int) -> int:\n"
            "        record = self.inventory.find(sku)\n"
            "        if record is None: raise NotFound('sku missing')\n"
            "        if quantity <= 0 or record.stock < quantity: raise Conflict('insufficient stock')\n"
            "        record.stock -= quantity\n"
            "        return record.stock\n"
        ),
        "src/urbanmesh/bootstrap.py": (
            '"""Composition root: the documented exception."""\n'
            "from urbanmesh.infrastructure.storage.memory import MemoryInventoryCatalog\n\n"
            "def build(items): return MemoryInventoryCatalog(items)\n"
        ),
    })
    outcome = _run_suite(repo, 0)
    assert outcome.classification == CLASSIFICATION_PASS


def test_fixed_layer_passes(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo, FIXED)
    outcome = _run_suite(repo, 0)
    assert outcome.classification == CLASSIFICATION_PASS
