"""Connected port discovery and non-linear dependency-inversion evidence."""

import json

import pytest

from server.agents.project_analysis.project_architecture.context import (
    normalize_source_references,
    retain_valid_sections,
    validate_report,
)
from server.agents.project_analysis.project_architecture.projection import (
    representation_view,
)
from server.agents.project_analysis.project_architecture.schemas import (
    ArchitectureReport,
)
from server.runtimes.repository import (
    RepositoryContext,
    RepositoryInput,
    RepositoryToolset,
    ToolLimits,
)
from server.runtimes.repository.working_context import WorkingContext
from server.services.repository_analysis import RepositoryAnalysisService


@pytest.fixture
def tools(tmp_path):
    root = tmp_path / "selected"
    root.mkdir()
    sources = {
        "repository_port.py": "from abc import ABC, abstractmethod\nclass RepositoryPort(ABC):\n    @abstractmethod\n    def save(self, value): pass\n",
        "client_service.py": "from repository_port import RepositoryPort\nclass ClientService:\n    def __init__(self, repository: RepositoryPort): self.repository = repository\n    def create(self, value): self.repository.save(value)\n",
        "storage_adapter.py": "from repository_port import RepositoryPort\nclass StorageAdapter(RepositoryPort):\n    def save(self, value): self.value = value\n",
        "unrelated_repository.py": "from repository_port import RepositoryPort\nclass UnrelatedRepository:\n    def __init__(self, port: RepositoryPort): self.port = port\n",
        "bootstrap.py": "from client_service import ClientService\nfrom storage_adapter import StorageAdapter\nservice = ClientService(StorageAdapter())\n",
        ".dependency-check.js": "module.exports = {};\n",
    }
    for name, content in sources.items():
        (root / name).write_text(content, encoding="utf-8")
    snapshot = RepositoryAnalysisService().analyze_sync(root)
    return RepositoryToolset(
        RepositoryContext(
            snapshot=snapshot,
            input=RepositoryInput(snapshot_hash=snapshot.repository.snapshot_hash),
        ),
        workspace_root=tmp_path,
        limits=ToolLimits(compact=True),
    )


def test_connected_candidates_require_adapter_implementation_not_only_import(tools):
    view = representation_view(tools)
    assert len(view["investigation_bundles"]) == 1
    bundle = view["investigation_bundles"][0]
    assert {item["role_hint"]: item["path"] for item in bundle["files"]} == {
        "use_case": "client_service.py",
        "port": "repository_port.py",
        "adapter": "storage_adapter.py",
        "composition": "bootstrap.py",
    }
    assert {item["path"] for item in bundle["files"]} <= {
        item["path"] for item in view["candidate_files"]
    }
    assert ".dependency-check.js" not in {
        item["path"] for item in view["candidate_files"]
    }
    assert any(
        item["source_path"] == "storage_adapter.py"
        and item["target_path"] == "repository_port.py"
        for item in view["relationship_signals"]
    )
    assert (
        not tools.retrieved_evidence
    )  # Navigation hints never become accepted source.


def test_primary_connected_source_set_survives_context_fitting():
    messages = [
        {
            "signature": str(index),
            "content": json.dumps(
                {"data": {"file_id": f"file:{index}", "content": "inspected source"}}
            ),
        }
        for index in range(5)
    ]
    working = WorkingContext(
        {}, messages, protected_file_ids=[f"file:{index}" for index in range(4)]
    )
    assert not working.reduce()
    assert len(working.responses) == 5


@pytest.mark.parametrize("ranges", [0, 1, 2])
def test_file_shaped_citation_alias_requires_one_inspected_source_range(tools, ranges):
    source = next(
        source
        for source in tools.accessible_snapshot.files
        if source.path == "repository_port.py"
    )
    for index in range(ranges):
        tools.execute(
            "get_source_excerpt",
            {"path": source.path, "start_line": 1, "end_line": index + 1},
            tool_call_id=str(index),
        )
    alias = "retrieval:" + source.id.removeprefix("file:")
    raw = {"assessment": {"evidence_ids": [alias, "retrieval:invented"]}}
    normalized, repairs = normalize_source_references(tools, raw)
    assert raw["assessment"]["evidence_ids"][0] == alias
    if ranges == 1:
        record = next(
            record for record in tools.retrieved_evidence if record.kind == "source"
        )
        assert normalized["assessment"]["evidence_ids"] == [
            record.id,
            "retrieval:invented",
        ]
        assert repairs == {alias: record.id}
    else:
        assert normalized == raw and not repairs


@pytest.mark.parametrize("missing_endpoint", [False, True])
@pytest.mark.parametrize("reuse_responsibilities", [False, True])
def test_local_pattern_supports_converging_dependency_links_without_fake_runtime_chain(
    tools, missing_endpoint, reuse_responsibilities
):
    evidence = {}
    for path in (
        "client_service.py",
        "repository_port.py",
        "storage_adapter.py",
        "bootstrap.py",
    ):
        response = tools.execute(
            "get_source_excerpt", {"path": path}, tool_call_id=path
        )
        evidence[path] = next(
            record for record in response.evidence if record.kind == "source"
        )

    def claim(text, paths):
        return {
            "statement": text,
            "scope": "Inspected client module",
            "status": "supported",
            "evidence_ids": [evidence[path].id for path in paths],
        }

    raw = {
        "organization": [
            {
                "name": name,
                "file_ids": [evidence[path].file_id],
                "responsibility": claim(text, [path]),
            }
            for name, path, text in (
                ("Application", "client_service.py", "Calls the repository port."),
                ("Port", "repository_port.py", "Defines the storage contract."),
                ("Adapter", "storage_adapter.py", "Implements storage."),
            )
        ],
        "closest_architecture": {
            "pattern": "Hexagonal",
            "assessment": claim(
                "The inspected module uses a port and replaceable adapter.",
                list(evidence),
            ),
            "observed_dependencies": [
                {
                    "source_unit": "Application",
                    "target_unit": "Port",
                    "description": claim(
                        "ClientService consumes RepositoryPort.",
                        ["client_service.py", "repository_port.py"],
                    ),
                },
                {
                    "source_unit": "Adapter",
                    "target_unit": "Port",
                    "description": claim(
                        "StorageAdapter implements RepositoryPort.",
                        ["storage_adapter.py"]
                        if missing_endpoint
                        else ["storage_adapter.py", "repository_port.py"],
                    ),
                },
            ],
            "contrast_question": "Does the application instantiate its concrete storage adapter?",
            "contrast_result": claim(
                "The application consumes the port; bootstrap selects StorageAdapter.",
                ["client_service.py", "bootstrap.py"],
            ),
        },
    }
    report = ArchitectureReport.model_validate(raw)
    if reuse_responsibilities:
        for edge in raw["closest_architecture"]["observed_dependencies"]:
            edge["description"]["evidence_ids"] = edge["description"]["evidence_ids"][
                :1
            ]
        report = ArchitectureReport.model_validate(raw)
    if missing_endpoint:
        raw["organization"][1]["responsibility"].update(
            status="hypothesis",
            limitations=["The port responsibility is not established."],
        )
        report = ArchitectureReport.model_validate(raw)
        with pytest.raises(ValueError, match="both responsibilities"):
            validate_report(tools, report)
        retained = retain_valid_sections(tools, raw)
        assert retained.closest_architecture.assessment.status == "hypothesis"
        assert retained.closest_architecture.assessment_origin == "host_downgrade"
    else:
        validate_report(tools, report)
        retained = retain_valid_sections(tools, raw)
        assert retained.closest_architecture.assessment.status == "supported"
        assert retained.closest_architecture.assessment_origin == "model"
        assert not retained.closest_architecture.observed_paths
        assert len(retained.closest_architecture.observed_dependencies) == 2


def test_endpoint_citations_do_not_establish_an_unresolved_or_reversed_connection(
    tools,
):
    records = []
    for path in ("client_service.py", "storage_adapter.py"):
        response = tools.execute(
            "get_source_excerpt", {"path": path}, tool_call_id=path
        )
        records.append(
            next(record for record in response.evidence if record.kind == "source")
        )

    def claim(text, identifiers):
        return {
            "statement": text,
            "scope": "Inspected functions",
            "status": "supported",
            "evidence_ids": identifiers,
        }

    report = ArchitectureReport.model_validate(
        {
            "organization": [
                {
                    "name": name,
                    "file_ids": [record.file_id],
                    "responsibility": claim("Inspected implementation.", [record.id]),
                }
                for name, record in zip(
                    ("Application", "Adapter"), records, strict=True
                )
            ],
            "connections": [
                {
                    "source_unit": "Application",
                    "target_unit": "Adapter",
                    "description": claim(
                        "Application directly constructs the storage adapter.",
                        [records[0].id],
                    ),
                }
            ],
        }
    )
    with pytest.raises(ValueError, match="both responsibilities"):
        validate_report(tools, report)
