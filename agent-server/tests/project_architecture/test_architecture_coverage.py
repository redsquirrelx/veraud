"""Monorepo coverage and source recovery before architectural closure."""

import asyncio
import json

import pytest

from server.agents.project_analysis.project_architecture import ProjectArchitectureAgent
from server.agents.project_analysis.project_architecture.projection import representation_view
from server.runtimes.repository import (
    RepositoryContext,
    RepositoryInput,
    RepositoryToolset,
    ToolLimits,
)
from server.services.repository_analysis import RepositoryAnalysisService


@pytest.fixture
def tools(tmp_path):
    root = tmp_path / "selected"
    for project in ("backend", "frontend"):
        directory = root / project / "src"
        directory.mkdir(parents=True)
        (directory.parent / "package.json").write_text(
            json.dumps({"name": project}), encoding="utf-8"
        )
    (root / "backend/src/app.ts").write_text(
        "export function app() { return 42; }", encoding="utf-8"
    )
    (root / "backend/src/service.ts").write_text(
        "export function execute() { return 42; }", encoding="utf-8"
    )
    (root / "frontend/src/App.tsx").write_text(
        "import { load } from './api';\nexport function App() { return load(); }",
        encoding="utf-8",
    )
    (root / "frontend/src/api.ts").write_text(
        "export function load() { return fetch('/api'); }", encoding="utf-8"
    )
    snapshot = RepositoryAnalysisService().analyze_sync(root)
    return RepositoryToolset(
        RepositoryContext(
            snapshot=snapshot,
            input=RepositoryInput(snapshot_hash=snapshot.repository.snapshot_hash),
        ),
        workspace_root=tmp_path,
        limits=ToolLimits(compact=True),
    )


@pytest.mark.parametrize("recover", [True, False])
@pytest.mark.parametrize("initial_frontend", [True, False])
def test_frontend_is_investigated_or_explicitly_left_pending(
    tools, recover, initial_frontend
):
    view = representation_view(tools)
    assert {item["path"] for item in view["application_targets"]} == {
        "frontend",
        "backend",
    }
    assert "frontend/src/App.tsx" in {item["path"] for item in view["candidate_files"]}
    events = []

    class Model:
        def __init__(self):
            self.calls = 0

        async def generate(self, prompt):
            self.calls += 1
            data = json.loads(prompt.split("\nARCHITECTURE_DATA\n", 1)[1])

            def read(path):
                return {
                    "id": path,
                    "name": "get_source_excerpt",
                    "arguments": {"path": path},
                }

            if self.calls == 1:
                return json.dumps(
                    {
                        "tool_calls": [
                            read("backend/src/app.ts"),
                            read("backend/src/service.ts"),
                        ]
                        + ([read("frontend/src/App.tsx")] if initial_frontend else [])
                    }
                )
            if self.calls == 3 and recover:
                assert data["validation_errors"]
                assert any(
                    item["path"] == "frontend" and item["status"] != "explained"
                    for item in data["application_coverage"]
                )
                return json.dumps(
                    {
                        "tool_calls": [
                            read("frontend/src/api.ts"),
                        ]
                        + ([] if initial_frontend else [read("frontend/src/App.tsx")])
                    }
                )
            units = []
            for project in ("backend", "frontend"):
                records = [
                    record
                    for record in data["source_evidence_ledger"]
                    if record["path"].startswith(project + "/")
                ]
                if not records or (
                    project == "frontend" and self.calls >= 3 and not recover
                ):
                    if project == "frontend" and self.calls >= 3 and not recover:
                        source = next(
                            source
                            for source in tools.accessible_snapshot.files
                            if source.path == "frontend/src/App.tsx"
                        )
                        units.append(
                            {
                                "name": project,
                                "file_ids": [source.id],
                                "responsibility": {
                                    "statement": "Frontend responsibility remains unverified.",
                                    "scope": "frontend",
                                    "status": "unresolved",
                                    "limitations": [
                                        "Frontend implementation coverage remains incomplete."
                                    ],
                                },
                            }
                        )
                    continue
                units.append(
                    {
                        "name": project,
                        "file_ids": list(
                            dict.fromkeys(record["file_id"] for record in records)
                        ),
                        "responsibility": {
                            "statement": "Implements the backend function."
                            if project == "backend"
                            else "App delegates loading to an API client using fetch.",
                            "scope": project,
                            "status": "supported",
                            "evidence_ids": [record["id"] for record in records],
                        },
                    }
                )
            unresolved = {
                "statement": "No pattern is established by this focused coverage test.",
                "scope": "Inspected application functions",
                "status": "unresolved",
                "limitations": ["Pattern analysis is outside this coverage fixture."],
            }
            return json.dumps(
                {
                    "architecture": {
                        "organization": units,
                        "relationship_investigations": [
                            {
                                "unit_name": unit["name"],
                                "status": "unresolved",
                                "resolution_blocker": "evidence_inconclusive",
                                "blocker_reason": "This fixture establishes application responsibilities but does not interpret the cross-application runtime contract.",
                                "assessment": unresolved
                                | {
                                    "evidence_ids": [
                                        record["id"]
                                        for record in data["source_evidence_ledger"]
                                        if record["path"].startswith(unit["name"] + "/")
                                    ]
                                },
                                "examined_file_ids": list(
                                    dict.fromkeys(
                                        record["file_id"]
                                        for record in data["source_evidence_ledger"]
                                        if record["path"].startswith(unit["name"] + "/")
                                    )
                                ),
                            }
                            for unit in units
                        ],
                        "closest_architecture": {
                            "pattern": "No clear pattern established",
                            "assessment": unresolved,
                        },
                        "explanation": unresolved,
                    }
                }
            )

    model = Model()
    result = asyncio.run(
        ProjectArchitectureAgent(
            model, on_event=lambda name, values: events.append((name, values))
        ).run(tools)
    )
    assert any(name == "architecture_relationship_recovery" for name, _ in events)
    assert not result.execution_issues
    coverage = {item.path: item for item in result.application_coverage}
    assert coverage["backend"].status == "explained"
    if recover:
        assert model.calls >= 4 and result.usage.tool_calls >= 4
        assert coverage["frontend"].status == "explained"
        assert {citation.path for citation in result.citations} >= {
            "frontend/src/App.tsx",
            "frontend/src/api.ts",
        }
    else:
        assert result.completion_status == "partial"
        assert coverage["frontend"].status == "inspected"
        assert any("frontend" in item for item in result.architecture.uncertainties)
    assert not any(record.correction for record in result.telemetry.model_calls)
