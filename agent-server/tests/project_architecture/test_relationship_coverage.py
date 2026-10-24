"""Relationship omissions are investigation gaps, not diagram-composition work."""

import asyncio
import json

import pytest

from server.agents.project_analysis.project_architecture import ProjectArchitectureAgent
from server.agents.project_analysis.project_architecture.context import validate_report
from server.agents.project_analysis.project_architecture.coverage import (
    EvidenceGap,
    relationship_coverage,
    validate_closure,
)
from server.agents.project_analysis.project_architecture.schemas import (
    ArchitectureReport,
    ArchitectureResult,
)
from server.agents.project_analysis.project_semantic_validation.context import (
    review_targets,
    validate_finding,
)
from server.agents.project_analysis.project_semantic_validation.schemas import (
    SemanticFinding,
)
from server.runtimes.repository import (
    ExecutionBudget,
    RepositoryContext,
    RepositoryInput,
    RepositoryToolset,
)
from server.runtimes.repository.schemas import BudgetUsage
from server.runtimes.repository.telemetry import ExecutionTelemetry
from server.services.repository_analysis import RepositoryAnalysisService


@pytest.fixture
def modules(tmp_path):
    workspace = tmp_path / "workspace"
    root = workspace / "checkout"
    root.mkdir(parents=True)
    for path, text in {
        "entry.py": "from service import run\ndef main():\n    return run()\n",
        "service.py": "from store import load\ndef run():\n    return load()\n",
        "store.py": "def load():\n    return 42\n",
    }.items():
        (root / path).write_text(text, encoding="utf-8")
    snapshot = RepositoryAnalysisService().analyze_sync(root)

    def fresh():
        return RepositoryToolset(
            RepositoryContext(
                snapshot=snapshot,
                input=RepositoryInput(
                    snapshot_hash=snapshot.repository.snapshot_hash,
                    budget=ExecutionBudget(),
                ),
            ),
            workspace_root=workspace,
        )

    tools = fresh()
    records = {
        path: tools.execute(
            "get_source_excerpt", {"path": path}, tool_call_id=path
        ).evidence[0]
        for path in ("entry.py", "service.py", "store.py")
    }

    def claim(statement, paths):
        return {
            "statement": statement,
            "scope": "Three inspected modules",
            "status": "supported",
            "evidence_ids": [records[path].id for path in paths],
        }

    units = [
        {
            "name": name,
            "file_ids": [records[path].file_id],
            "responsibility": claim(statement, [path]),
        }
        for name, path, statement in (
            ("Entry", "entry.py", "Entry invokes the service."),
            ("Service", "service.py", "Service invokes the store."),
            ("Store", "store.py", "Store returns the loaded result."),
        )
    ]
    raw = {
        "organization": units,
        "connections": [
            {
                "source_unit": "Entry",
                "target_unit": "Service",
                "kind": "calls",
                "description": claim(
                    "Entry delegates to Service.run.", ["entry.py", "service.py"]
                ),
            }
        ],
        "relationship_investigations": [
            {
                "unit_name": unit["name"],
                "status": "connected",
                "assessment": unit["responsibility"],
                "examined_file_ids": unit["file_ids"],
            }
            for unit in units
        ],
        "closest_architecture": {
            "pattern": "Local layered hypothesis",
            "assessment": {
                "statement": "The inspected modules suggest a layered flow.",
                "scope": "Inspected modules",
                "status": "hypothesis",
                "limitations": ["A complete dependency map is required."],
            },
        },
        "explanation": claim(
            "Entry delegates to Service, which invokes Store.",
            ["entry.py", "service.py", "store.py"],
        ),
    }
    return tools, fresh, raw, records


def test_one_supported_connection_does_not_cover_other_module_boundaries(modules):
    tools, _, raw, _ = modules
    report = ArchitectureReport.model_validate(raw)
    validate_report(tools, report)
    coverage = {
        item["unit_name"]: item for item in relationship_coverage(tools, report)
    }
    assert coverage["Entry"]["status"] == "connected"
    assert coverage["Service"]["pending_paths"] == ["store.py"]
    assert coverage["Store"]["pending_units"] == ["Service"]
    with pytest.raises(EvidenceGap, match="store.py"):
        validate_closure(tools, report)


def test_explicit_unresolved_boundaries_close_as_uncertainty_without_invented_edges(
    modules,
):
    tools, _, raw, _ = modules
    for entry in raw["relationship_investigations"][1:]:
        entry["status"] = "unresolved"
        entry["assessment"] = {
            **entry["assessment"],
            "status": "unresolved",
            "limitations": ["The Service-to-Store boundary remains unverified."],
        }
    report = ArchitectureReport.model_validate(raw)
    validate_closure(tools, report)
    assert len(report.connections) == 1
    assert [item["status"] for item in relationship_coverage(tools, report)] == [
        "connected",
        "unresolved",
        "unresolved",
    ]


def test_supported_missing_edge_resolves_coverage_and_false_isolation_is_rejected(
    modules,
):
    tools, _, raw, records = modules
    raw["relationship_investigations"][2]["status"] = "isolated"
    with pytest.raises(EvidenceGap):
        validate_closure(tools, ArchitectureReport.model_validate(raw))
    raw["relationship_investigations"][2]["status"] = "connected"
    raw["connections"].append(
        {
            "source_unit": "Service",
            "target_unit": "Store",
            "kind": "calls",
            "description": {
                "statement": "Service.run calls Store.load.",
                "scope": "service.py and store.py",
                "status": "supported",
                "evidence_ids": [records["service.py"].id, records["store.py"].id],
            },
        }
    )
    report = ArchitectureReport.model_validate(raw)
    validate_report(tools, report)
    validate_closure(tools, report)
    assert all(
        item["status"] == "connected" for item in relationship_coverage(tools, report)
    )


def test_omitted_investigations_become_review_targets_and_cannot_be_approved(modules):
    tools, fresh, raw, _ = modules
    raw["relationship_investigations"] = []
    report = ArchitectureReport.model_validate(raw)
    result = ArchitectureResult(
        snapshot_hash=tools.context.input.snapshot_hash,
        completion_status="partial",
        architecture=report,
        retrieved_evidence=tools.retrieved_evidence,
        usage=BudgetUsage(),
        telemetry=ExecutionTelemetry(),
    )
    validator = fresh()
    selected = {target.id: target for target in review_targets(validator, result)}
    target = selected["/organization/1/relationship_coverage"]
    assert target.context["pending_paths"] == ["store.py"]
    evidence = validator.execute(
        "get_source_excerpt", {"path": "service.py"}, tool_call_id="independent"
    ).evidence[0]
    finding = SemanticFinding(
        target_id=target.id,
        checked_statement=target.claim.statement,
        verdict="supported",
        reason="The responsibility is correct.",
        counterevidence_check="Only the service body was inspected.",
        evidence_ids=(evidence.id,),
    )
    with pytest.raises(ValueError, match="cannot be approved"):
        validate_finding(validator, finding, selected)


def test_receipts_cannot_claim_uninspected_files(modules):
    tools, _, raw, _ = modules
    raw["relationship_investigations"][0]["examined_file_ids"] = ["file:invented"]
    with pytest.raises(ValueError, match="must have been inspected"):
        validate_report(tools, ArchitectureReport.model_validate(raw))


class RecoveryModel:
    def __init__(self, raw, records, *, resolve=True):
        self.raw, self.records, self.resolve = raw, records, resolve
        self.prompts = []

    async def generate(self, prompt):
        self.prompts.append(str(prompt))
        data = json.loads(str(prompt).split("\nARCHITECTURE_DATA\n", 1)[1])
        ledger = {
            record["file_id"]: record for record in data["source_evidence_ledger"]
        }
        if not ledger:
            return json.dumps(
                {
                    "tool_calls": [
                        {
                            "id": path,
                            "name": "get_source_excerpt",
                            "arguments": {"path": path},
                        }
                        for path in ("entry.py", "service.py")
                    ]
                }
            )
        raw = json.loads(json.dumps(self.raw))
        aliases = {
            record.id: ledger[record.file_id]["id"]
            for record in self.records.values()
            if record.file_id in ledger
        }

        def remap(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == "evidence_ids":
                        value[key] = [
                            aliases[identifier]
                            for identifier in child
                            if identifier in aliases
                        ]
                    else:
                        remap(child)
            elif isinstance(value, list):
                for child in value:
                    remap(child)

        remap(raw)
        recovered = bool(data["relationship_recovery_actions"])
        for unit, entry in zip(
            raw["organization"], raw["relationship_investigations"], strict=True
        ):
            own = [
                identifier for identifier in unit["file_ids"] if identifier in ledger
            ]
            if not own:
                unit["responsibility"].update(
                    status="unresolved",
                    limitations=["Required source has not been read."],
                )
            entry["examined_file_ids"] = own
            if unit["name"] != "Entry" and not (recovered and self.resolve):
                entry["status"] = "unresolved"
                entry["assessment"].update(
                    status="unresolved",
                    limitations=[
                        "The service-to-store boundary has not been resolved."
                    ],
                )
        if recovered and self.resolve:
            raw["connections"].append(
                {
                    "source_unit": "Service",
                    "target_unit": "Store",
                    "kind": "calls",
                    "description": {
                        "statement": "Service.run invokes Store.load.",
                        "scope": "service.py and store.py",
                        "status": "supported",
                        "evidence_ids": [
                            ledger[self.records[path].file_id]["id"]
                            for path in ("service.py", "store.py")
                        ],
                    },
                }
            )
        return json.dumps({"architecture": raw})


def test_agent_forces_endpoint_recovery_and_then_resolves_connections(modules):
    _, fresh, raw, records = modules
    model = RecoveryModel(raw, records)
    events = []
    tools = fresh()
    result = asyncio.run(
        ProjectArchitectureAgent(
            model, on_event=lambda name, values: events.append(name)
        ).run(tools)
    )
    assert result.completion_status == "complete"
    assert len(model.prompts) == 3
    assert "architecture_relationship_recovery" in events
    assert any(
        record.file_id == records["store.py"].file_id
        for record in result.retrieved_evidence
    )
    assert all(
        item.status == "connected" and item.resolution_blocker is None
        for item in result.relationship_coverage
    )
    assert len(result.architecture.connections) == 2


def test_agent_cannot_close_by_repeating_unresolved_and_records_budget_stop(modules):
    _, fresh, raw, records = modules
    model = RecoveryModel(raw, records, resolve=False)
    result = asyncio.run(ProjectArchitectureAgent(model).run(fresh()))
    assert len(model.prompts) == 8
    assert result.completion_status == "partial"
    pending = [
        item for item in result.relationship_coverage if item.status == "unresolved"
    ]
    assert pending and all(
        item.resolution_blocker == "budget_exhausted" for item in pending
    )
    assert any(
        item.category == "relationship_assessment_incomplete"
        for item in result.execution_issues
    )
    assert len(result.architecture.connections) == 1


def test_failed_endpoint_is_explained_without_repeating_unavailable_reads(
    modules, monkeypatch
):
    _, fresh, raw, records = modules
    tools = fresh()
    get_source = tools._queries.get_source_excerpt

    def unavailable(path, *args, **kwargs):
        if path == "store.py":
            raise ValueError("Source was not retained for store.py")
        return get_source(path, *args, **kwargs)

    monkeypatch.setattr(tools._queries, "get_source_excerpt", unavailable)
    model = RecoveryModel(raw, records, resolve=False)
    result = asyncio.run(ProjectArchitectureAgent(model).run(tools))
    assert result.completion_status == "partial"
    assert any(
        item.resolution_blocker == "source_unavailable"
        for item in result.relationship_coverage
    ), result.model_dump()
    assert any(
        item.category == "relationship_sources_unavailable"
        for item in result.execution_issues
    )
    assert len(model.prompts) < 8
