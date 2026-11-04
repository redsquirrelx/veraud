"""Six controlled semantic cases over a small retained implementation fixture."""

from pathlib import Path

from server.project_analysis.project_architecture.schemas import (
    ArchitectureReport,
    ArchitectureResult,
)

from ..runtimes.repository import (
    RepositoryContext,
    RepositoryInput,
    RepositoryToolset,
)
from ..runtimes.repository.schemas import BudgetUsage
from ..runtimes.repository.telemetry import ExecutionTelemetry
from ..services.repository_analysis import RepositoryAnalysisService

FILES = {
    "service.py": "from port import RepositoryPort\n\nclass Service:\n    def __init__(self, repo: RepositoryPort):\n        self.repo = repo\n    def execute(self):\n        return self.repo.load()\n",
    "port.py": "from abc import ABC, abstractmethod\n\nclass RepositoryPort(ABC):\n    @abstractmethod\n    def load(self):\n        raise NotImplementedError\n",
    "adapter.py": "import sqlite3\nfrom port import RepositoryPort\n\nclass SqlAdapter(RepositoryPort):\n    def load(self):\n        with sqlite3.connect(':memory:') as db:\n            return db.execute('SELECT 42').fetchone()[0]\n",
    "bootstrap.py": "import os\nfrom service import Service\nfrom adapter import SqlAdapter\n\ndef build_service():\n    if os.getenv('BACKEND') == 'sqlite':\n        return Service(SqlAdapter())\n    raise RuntimeError('Configure BACKEND')\n",
    "worker.py": "import sqlite3\n\ndef run_job():\n    with sqlite3.connect(':memory:') as db:\n        return db.execute('SELECT 1').fetchone()[0]\n",
    "compose.yaml": "services:\n  database:\n    image: postgres:16\n    ports:\n      - '5432:5432'\n",
}

EXPECTED = {
    "/organization/0/responsibility": {"supported"},
    "/organization/1/responsibility": {"contradicted", "overstated"},
    "/connections/0/description": {"contradicted", "overstated"},
    "/closest_architecture/assessment": {"overstated", "contradicted"},
    "/supporting_evidence/0": {"insufficient_evidence", "overstated"},
    "/infrastructure/0/configured": {"overstated", "insufficient_evidence"},
}


def build_semantic_cases(workspace: Path):
    """Create an isolated new checkout; no existing files are overwritten."""
    root = workspace / "semantic-cases"
    root.mkdir(parents=True)
    for path, content in FILES.items():
        (root / path).write_text(content, encoding="utf-8")
    snapshot = RepositoryAnalysisService().analyze_sync(root)
    tools = RepositoryToolset(
        RepositoryContext(
            snapshot=snapshot,
            input=RepositoryInput(snapshot_hash=snapshot.repository.snapshot_hash),
        ),
        workspace_root=workspace,
    )
    files = {source.path: source.id for source in tools.accessible_snapshot.files}
    evidence = {}
    for index, path in enumerate(FILES):
        response = tools.execute(
            "get_source_excerpt",
            {"path": path},
            tool_call_id=f"fixture-architect-{index}",
        )
        evidence[path] = response.evidence[0].id

    def claim(statement, *paths, scope="Inspected fixture"):
        return {
            "statement": statement,
            "scope": scope,
            "status": "supported",
            "evidence_ids": [evidence[path] for path in paths],
        }

    def edge(source, target, statement, *paths):
        return {
            "source_unit": source,
            "target_unit": target,
            "description": claim(statement, *paths),
        }

    report = ArchitectureReport.model_validate(
        {
            "organization": [
                {
                    "name": "Service",
                    "file_ids": [files["service.py"]],
                    "responsibility": claim(
                        "Service.execute delegates loading to its injected RepositoryPort.",
                        "service.py",
                    ),
                },
                {
                    "name": "Notifications",
                    "file_ids": [files["service.py"]],
                    "responsibility": claim(
                        "Service.execute sends an SMTP email before loading data.",
                        "service.py",
                    ),
                },
                {
                    "name": "Port",
                    "file_ids": [files["port.py"]],
                    "responsibility": claim(
                        "RepositoryPort defines an abstract load operation.", "port.py"
                    ),
                },
                {
                    "name": "SQL Adapter",
                    "file_ids": [files["adapter.py"]],
                    "responsibility": claim(
                        "SqlAdapter implements the port using SQLite.", "adapter.py"
                    ),
                },
            ],
            "connections": [
                edge(
                    "Port",
                    "Service",
                    "RepositoryPort imports Service and calls Service.execute.",
                    "port.py",
                    "service.py",
                )
            ],
            "closest_architecture": {
                "pattern": "Hexagonal",
                "scope_kind": "local",
                "assessment": claim(
                    "Every component in the entire repository accesses databases exclusively through ports and adapters, with no direct SQL access outside adapters.",
                    "service.py",
                    "port.py",
                    "adapter.py",
                    scope="Entire repository",
                ),
                "observed_dependencies": [
                    edge(
                        "Service",
                        "Port",
                        "Service imports and consumes RepositoryPort.",
                        "service.py",
                        "port.py",
                    ),
                    edge(
                        "SQL Adapter",
                        "Port",
                        "SqlAdapter inherits RepositoryPort.",
                        "adapter.py",
                        "port.py",
                    ),
                ],
                "contrast_question": "Does the service import SQLite or the concrete adapter?",
                "contrast_result": claim(
                    "Service imports the port, not SQLite or SqlAdapter.", "service.py"
                ),
            },
            "supporting_evidence": [
                claim(
                    "In production BACKEND is set to sqlite, so production selects SqlAdapter.",
                    "bootstrap.py",
                    scope="Actual production environment",
                )
            ],
            "infrastructure": [
                {
                    "name": "Database",
                    "kind": "state",
                    "configured": claim(
                        "compose.yaml proves the PostgreSQL database container is currently running in production.",
                        "compose.yaml",
                        scope="Actual production deployment",
                    ),
                }
            ],
        }
    )
    original = ArchitectureResult(
        snapshot_hash=snapshot.repository.snapshot_hash,
        completion_status="partial",
        architecture=report,
        retrieved_evidence=tools.retrieved_evidence,
        inspected_file_ids=tuple(files.values()),
        usage=BudgetUsage(),
        telemetry=ExecutionTelemetry(),
    )
    return snapshot, original, EXPECTED
