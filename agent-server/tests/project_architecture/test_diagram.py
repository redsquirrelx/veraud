"""Diagram references, semantic interpretation, rendering, and report selection."""

import asyncio
import json

import pytest

from server.agents.project_analysis.project_architecture import ProjectArchitectureAgent
from server.agents.project_analysis.project_architecture.context import (
    retain_valid_sections,
    validate_report,
)
from server.agents.project_analysis.project_architecture.diagram import (
    project_component_diagram,
    render_diagram,
    render_mermaid,
)
from server.agents.project_analysis.project_architecture.diagram_composition import (
    complete_views,
    missing_views,
)
from server.agents.project_analysis.project_architecture.schemas import (
    ArchitectureDiagram,
    ArchitectureReport,
    ArchitectureResult,
)
from server.agents.project_analysis.project_semantic_validation.context import (
    report_hash,
    review_targets,
)
from server.agents.project_analysis.project_semantic_validation.schemas import (
    SemanticFinding,
    SemanticValidationResult,
)
from server.pipelines import ProjectArchitecturePipeline
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
def fixture(tmp_path):
    workspace = tmp_path / "workspace"
    root = workspace / "checkout"
    root.mkdir(parents=True)
    for name, text in {
        "service.py": "from port import Port\nclass Service:\n    def run(self, port: Port):\n        return port.load()\n",
        "port.py": "class Port:\n    def load(self):\n        raise NotImplementedError\n",
        "adapter.py": "from port import Port\nclass Adapter(Port):\n    def load(self):\n        return 42\n",
    }.items():
        (root / name).write_text(text, encoding="utf-8")
    snapshot = RepositoryAnalysisService().analyze_sync(root)

    def fresh():
        return RepositoryToolset(
            RepositoryContext(
                snapshot=snapshot,
                input=RepositoryInput(
                    snapshot_hash=snapshot.repository.snapshot_hash,
                    budget=ExecutionBudget(max_input_tokens_per_call=12000),
                ),
            ),
            workspace_root=workspace,
        )

    tools = fresh()
    records = {
        name: tools.execute(
            "get_source_excerpt", {"path": name}, tool_call_id=name
        ).evidence[0]
        for name in ("service.py", "port.py", "adapter.py")
    }

    def claim(statement, names):
        return {
            "statement": statement,
            "scope": "Inspected service module",
            "status": "supported",
            "evidence_ids": [records[name].id for name in names],
        }

    report = ArchitectureReport.model_validate(
        {
            "organization": [
                {
                    "name": name,
                    "file_ids": [records[path].file_id],
                    "responsibility": claim(statement, [path]),
                }
                for name, path, statement in (
                    ("Use Case", "service.py", "Delegates loading through Port."),
                    ("Port", "port.py", "Defines the load contract."),
                    ("Adapter", "adapter.py", "Implements the load contract."),
                )
            ],
            "connections": [
                {
                    "source_unit": "Use Case",
                    "target_unit": "Port",
                    "description": claim(
                        "Service consumes Port.", ["service.py", "port.py"]
                    ),
                },
                {
                    "source_unit": "Adapter",
                    "target_unit": "Port",
                    "description": claim(
                        "Adapter inherits Port.", ["adapter.py", "port.py"]
                    ),
                },
            ],
            "relationship_investigations": [
                {
                    "unit_name": name,
                    "status": "connected",
                    "assessment": claim(statement, [path]),
                    "examined_file_ids": [records[path].file_id],
                }
                for name, path, statement in (
                    (
                        "Use Case",
                        "service.py",
                        "The service consumes the inspected Port contract.",
                    ),
                    (
                        "Port",
                        "port.py",
                        "The inspected contract is consumed by Service and implemented by Adapter.",
                    ),
                    (
                        "Adapter",
                        "adapter.py",
                        "The adapter implements the inspected Port contract.",
                    ),
                )
            ],
            "closest_architecture": {
                "pattern": "Ports and adapters",
                "assessment": {
                    "statement": "Local inversion is plausible.",
                    "scope": "Inspected module",
                    "status": "hypothesis",
                    "limitations": ["Composition has not been inspected."],
                },
            },
            "explanation": claim(
                "The service consumes a contract implemented by the adapter.",
                ["service.py", "port.py", "adapter.py"],
            ),
            "diagram": {
                "title": "Local component view",
                "scope": "Inspected module",
                "groups": [
                    {"id": "core", "title": "Core", "scope": "service.py and port.py"},
                    {"id": "infra", "title": "Infrastructure", "scope": "adapter.py"},
                ],
                "nodes": [
                    {
                        "id": "use_case",
                        "unit_ref": "/organization/0",
                        "group_id": "core",
                    },
                    {"id": "port", "unit_ref": "/organization/1", "group_id": "core"},
                    {
                        "id": "adapter",
                        "unit_ref": "/organization/2",
                        "group_id": "infra",
                    },
                ],
                "edges": [
                    {
                        "source": "use_case",
                        "target": "port",
                        "kind": "depends_on",
                        "claim_ref": "/connections/0/description",
                    },
                    {
                        "source": "adapter",
                        "target": "port",
                        "kind": "implements",
                        "claim_ref": "/connections/1/description",
                    },
                ],
                "limitations": ["Runtime composition is unverified."],
            },
        }
    )
    original = ArchitectureResult(
        snapshot_hash=snapshot.repository.snapshot_hash,
        completion_status="partial",
        architecture=report,
        retrieved_evidence=tools.retrieved_evidence,
        usage=BudgetUsage(),
        telemetry=ExecutionTelemetry(),
    )
    return tools, fresh, original, snapshot, workspace


def multiview_report(original):
    raw = original.architecture.model_dump(mode="json")
    raw["deviations"] = [
        {
            "observed_decision": {
                "statement": "Adapter returns a constant instead of reading external state.",
                "scope": "adapter.py",
                "status": "supported",
                "evidence_ids": list(
                    original.architecture.organization[2].responsibility.evidence_ids
                ),
            },
            "pattern_expectation": "The persistence adapter delegates to an external store.",
            "explanation": "This adapter is a local stub; this is a variation, not proof of a defect.",
        }
    ]
    diagram = raw["diagram"]
    diagram["nodes"][0]["role"] = "service"
    diagram["nodes"][1]["role"] = "interface"
    diagram["nodes"][2]["role"] = "adapter"
    diagram["edges"][0]["label"] = "load contract"
    diagram["deviations"] = [
        {
            "deviation_ref": "/deviations/0",
            "node_ids": ["adapter"],
            "explanation": "The adapter's load implementation returns a constant.",
        }
    ]
    extra = {key: value for key, value in diagram.items() if key != "views"}
    diagram["views"] = [
        {
            **extra,
            "title": "Dependency inversion",
            "view_kind": "dependencies",
            "direction": "TB",
        }
    ]
    return ArchitectureReport.model_validate(raw)


def test_multiple_views_and_deviations_are_traceable_and_reviewable(fixture):
    tools, _, original, _, _ = fixture
    report = multiview_report(original)
    result = original.model_copy(update={"architecture": report})
    validate_report(tools, report)
    targets = {item.id: item for item in review_targets(tools, result)}
    assert "/diagram/nodes/1/role" in targets
    assert "/diagram/deviations/0" in targets
    pointer = "/diagram/views/0/deviations/0"
    assert pointer in targets
    finding = SemanticFinding(
        target_id=pointer,
        checked_statement=targets[pointer].claim.statement,
        verdict="insufficient_evidence",
        reason="Placement requires inspection.",
        counterevidence_check="The adapter might be a test stub rather than the active persistence adapter.",
        missing_evidence=(
            {"question": "Where is this adapter selected?", "paths": ["adapter.py"]},
        ),
    )
    rendered = render_diagram(result, findings=(finding,))
    assert len(rendered.views) == 1
    assert rendered.views[0].report_hash == rendered.report_hash
    assert rendered.views[0].deviations[0].semantic_verdict == "insufficient_evidence"
    assert pointer in rendered.views[0].deviations[0].review_target_ids
    assert "view_primary" not in rendered.mermaid and "view_0" not in rendered.mermaid
    assert rendered.mermaid.startswith("flowchart LR")
    assert rendered.views[0].mermaid.startswith("flowchart TB")
    assert 'd0["D1"]' in rendered.mermaid
    assert rendered.deviation_notes[0].observation.startswith(
        "Adapter returns a constant"
    )
    assert "load contract" in rendered.mermaid and rendered.legend
    assert "architect:" not in rendered.mermaid and "semantic:" not in rendered.mermaid
    assert 'legend["' not in rendered.mermaid


@pytest.mark.parametrize(
    "reference,node_ids",
    [("/deviations/99", ["adapter"]), ("/deviations/0", ["ghost"])],
)
def test_deviation_annotations_reject_unavailable_references(
    fixture, reference, node_ids
):
    _, _, original, _, _ = fixture
    raw = multiview_report(original).model_dump(mode="json")
    raw["diagram"]["views"][0]["deviations"][0].update(
        deviation_ref=reference, node_ids=node_ids
    )
    with pytest.raises(ValueError, match="existing"):
        ArchitectureReport.model_validate(raw)


@pytest.mark.parametrize(
    "mutation,message",
    [
        (
            lambda raw: raw["diagram"]["nodes"][0].update(unit_ref="/organization/99"),
            "existing organization",
        ),
        (
            lambda raw: raw["diagram"]["edges"][0].update(source="unknown"),
            "existing nodes",
        ),
        (
            lambda raw: raw["diagram"]["edges"][0].update(
                source="port", target="use_case"
            ),
            "direction",
        ),
        (
            lambda raw: raw["diagram"]["edges"][0].update(claim_ref="/explanation"),
            "connection description",
        ),
        (
            lambda raw: raw["diagram"]["nodes"][0].update(group_id="missing"),
            "existing group",
        ),
        (lambda raw: raw["diagram"]["nodes"][0].update(id="port"), "unique|Duplicate"),
    ],
)
def test_invalid_structure_and_direction_rejected(fixture, mutation, message):
    raw = fixture[2].architecture.model_dump(mode="json")
    mutation(raw)
    with pytest.raises(ValueError, match=message):
        ArchitectureReport.model_validate(raw)


def test_diagram_inherits_evidence_and_new_types_are_reviewed(fixture):
    tools, fresh, original, _, _ = fixture
    validate_report(tools, original.architecture)
    targets = {item.id: item for item in review_targets(fresh(), original)}
    assert (
        targets["/diagram/edges/1"].claim.statement
        == "Diagram relation implements: Adapter -> Port."
    )
    assert (
        targets["/diagram/edges/1"].claim.evidence_ids
        == original.architecture.connections[1].description.evidence_ids
    )
    assert targets["/diagram/groups/0"].kind == "diagram_group"
    assert targets["/diagram/scope"].claim.scope == original.architecture.diagram.scope
    artifact = render_diagram(original)
    assert artifact.report_hash == report_hash(original)
    assert (
        artifact.nodes[0].evidence_ids
        == original.architecture.organization[0].responsibility.evidence_ids
    )
    assert all(node.semantic_verdict == "not_reviewed" for node in artifact.nodes)
    assert "n0 -->" in artifact.mermaid and "n2 -->" in artifact.mermaid
    assert "implements" in artifact.mermaid


def findings_for(fresh, original):
    return tuple(
        SemanticFinding(
            target_id=target.id,
            checked_statement=target.claim.statement,
            verdict="supported",
            reason="Inspected relevant implementation.",
            counterevidence_check="Checked concrete dependency direction.",
            evidence_ids=target.claim.evidence_ids
            or original.architecture.organization[0].responsibility.evidence_ids,
        )
        for target in review_targets(fresh(), original)
    )


def test_semantic_labels_require_linked_claim_and_interpretation_reviews(fixture):
    _, fresh, original, _, _ = fixture
    findings = findings_for(fresh, original)
    assert all(
        edge.semantic_verdict == "supported"
        for edge in render_diagram(original, findings=findings).edges
    )
    reduced = tuple(
        finding for finding in findings if finding.target_id != "/diagram/edges/0"
    )
    assert (
        render_diagram(original, findings=reduced).edges[0].semantic_verdict
        == "not_reviewed"
    )
    rejected = tuple(
        finding.model_copy(update={"verdict": "contradicted"})
        if finding.target_id == "/diagram/edges/0"
        else finding
        for finding in findings
    )
    assert (
        render_diagram(original, findings=rejected).edges[0].semantic_verdict
        == "contradicted"
    )
    assert "linkStyle 0 stroke:#b91c1c" in render_mermaid(
        original.architecture, findings=rejected
    )


def test_hypothesis_uses_dashed_edges_without_upgrading_certainty(fixture):
    raw = fixture[2].architecture.model_dump(mode="json")
    raw["connections"][0]["description"].update(
        status="hypothesis", limitations=["Runtime invocation unverified."]
    )
    report = ArchitectureReport.model_validate(raw)
    assert "n0 -.->" in render_mermaid(report)
    assert "architect: hypothesis" not in render_mermaid(report)


@pytest.mark.parametrize(
    "semantic,color",
    [
        ("supported", "#15803d"),
        ("overstated", "#c2410c"),
        ("contradicted", "#b91c1c"),
        ("insufficient_evidence", "#64748b"),
    ],
)
def test_node_fill_and_border_represent_independent_judgments(fixture, semantic, color):
    _, fresh, original, _, _ = fixture
    findings = tuple(
        item.model_copy(update={"verdict": semantic})
        if item.target_id == "/organization/0/responsibility"
        else item
        for item in findings_for(fresh, original)
    )
    chart = render_mermaid(original.architecture, findings=findings)
    assert f"style n0 fill:#dbeafe,stroke:{color}" in chart
    assert "architect:" not in chart and "semantic:" not in chart
    if semantic == "insufficient_evidence":
        assert "stroke-dasharray: 5 5" in chart


def test_labels_cannot_inject_mermaid_nodes_html_or_directives(fixture):
    raw = fixture[2].architecture.model_dump(mode="json")
    malicious = 'UI"]\nmalicious["<script> %%{init: {}}'
    raw["organization"][0]["name"] = malicious
    raw["connections"][0]["source_unit"] = malicious
    raw["diagram"]["title"] = malicious
    text = render_mermaid(ArchitectureReport.model_validate(raw))
    assert "<script>" not in text and "%%{init" not in text
    assert "\nmalicious[" not in text
    assert "#34;" in text and "#60;" in text
    assert text == render_mermaid(ArchitectureReport.model_validate(raw))


def test_invalid_diagram_is_omitted_without_losing_valid_report(fixture):
    tools, _, original, _, _ = fixture
    raw = original.architecture.model_dump(mode="json")
    raw["diagram"]["edges"][0]["target"] = "missing"
    salvaged = retain_valid_sections(tools, raw)
    assert salvaged.organization == original.architecture.organization
    assert salvaged.diagram is None
    assert any("Diagram omitted" in item for item in salvaged.uncertainties)


def test_nested_dependency_and_runtime_references_are_resolved(fixture):
    raw = fixture[2].architecture.model_dump(mode="json")
    raw["closest_architecture"]["observed_dependencies"] = [raw["connections"][1]]
    raw["closest_architecture"]["observed_paths"] = [[raw["connections"][0]]]
    raw["diagram"]["edges"][0]["claim_ref"] = (
        "/closest_architecture/observed_paths/0/0/description"
    )
    raw["diagram"]["edges"][1]["claim_ref"] = (
        "/closest_architecture/observed_dependencies/0/description"
    )
    report = ArchitectureReport.model_validate(raw)
    assert "n0 -->" in render_mermaid(report) and "n2 -->" in render_mermaid(report)
    raw["diagram"]["edges"][0]["claim_ref"] = (
        "/closest_architecture/observed_paths/0/9/description"
    )
    with pytest.raises(ValueError, match="existing connection"):
        ArchitectureReport.model_validate(raw)


def test_cli_prints_diagram_and_keeps_json_machine_readable(
    fixture, monkeypatch, capsys
):
    from server import repository_runner
    from server.run_project_architecture import main

    original = fixture[2]
    data = original.model_dump(mode="json") | {
        "execution_mode": "architecture",
        "architecture_diagram": render_diagram(original).model_dump(mode="json"),
    }

    async def run(arguments):
        return data, True

    monkeypatch.setattr(repository_runner, "run", run)
    assert main(["unused", "--diagram"]) == 0
    text = capsys.readouterr().out
    assert "Architecture diagram (original report)" in text
    assert "```mermaid\nflowchart LR" in text
    assert main(["unused", "--diagram", "--json"]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["architecture_diagram"][
        "structure"
    ] == original.architecture.diagram.model_dump(mode="json")
    assert (
        parsed["architecture_diagram"]["nodes"][0]["semantic_verdict"] == "not_reviewed"
    )


def test_architect_retains_diagram_without_an_extra_model_call(fixture):
    tools, _, original, _, _ = fixture

    class Model:
        calls = 0

        async def generate(self, prompt):
            self.calls += 1
            return json.dumps(
                {"architecture": original.architecture.model_dump(mode="json")}
            )

    model = Model()
    result = asyncio.run(ProjectArchitectureAgent(model).run(tools))
    assert result.architecture.diagram == original.architecture.diagram
    assert model.calls == 1


def test_main_investigation_has_no_diagram_contract_or_automatic_selection(fixture):
    tools, fresh, original, _, _ = fixture
    raw = original.architecture.model_dump(mode="json", exclude={"diagram"})

    class Model:
        def __init__(self):
            self.prompts = []

        async def generate(self, prompt):
            self.prompts.append(str(prompt))
            contract = json.loads(
                str(prompt).split("\nOUTPUT_SCHEMA\n", 1)[1].split("\nTOOLS\n", 1)[0]
            )
            assert "diagram" not in contract["types"]["ArchitectureReport"]["fields"]
            assert "DiagramNode" not in contract["types"]
            return json.dumps({"architecture": raw})

    model = Model()
    result = asyncio.run(ProjectArchitectureAgent(model).run(tools))
    assert len(model.prompts) == 1
    assert result.architecture.diagram is None
    targets = review_targets(fresh(), result)
    assert not any(target.id.startswith("/diagram/") for target in targets)


def test_changed_projection_is_not_exempt_from_semantic_scope_review(fixture):
    _, fresh, original, _, _ = fixture
    report = original.architecture.model_copy(
        update={"diagram": project_component_diagram(original.architecture)}
    )
    raw = report.model_dump(mode="json")
    raw["diagram"]["scope"] = "Entire repository, without omissions."
    changed = original.model_copy(
        update={"architecture": ArchitectureReport.model_validate(raw)}
    )
    assert any(
        target.id == "/diagram/scope" for target in review_targets(fresh(), changed)
    )


def test_compact_composition_preserves_model_selection_and_native_output_limit(fixture):
    from server.runtimes.repository.model_runtime import ModelGateway

    _, fresh, original, _, _ = fixture
    original = original.model_copy(
        update={
            "architecture": original.architecture.model_copy(update={"diagram": None})
        }
    )
    selected = {
        "title": "Selected core responsibilities",
        "scope": "service.py and port.py",
        "groups": [
            {
                "id": "core",
                "title": "Application contract boundary",
                "scope": "service.py and port.py",
            }
        ],
        "nodes": [
            {"id": "service", "unit_ref": "/organization/0", "group_id": "core"},
            {"id": "contract", "unit_ref": "/organization/1", "group_id": "core"},
        ],
        "edges": [
            {
                "source": "service",
                "target": "contract",
                "kind": "depends_on",
                "claim_ref": "/connections/0/description",
            }
        ],
        "limitations": ["Adapter omitted to focus on the application boundary."],
    }

    class Model:
        def __init__(self):
            self.calls = []

        async def generate(self, prompt):
            raise AssertionError("Use the native small output limit.")

        async def generate_with_output_limit(self, prompt, *, max_output_tokens):
            data = json.loads(prompt.split("\nDIAGRAM_DATA\n", 1)[1])
            assert len(data["units"]) == 3
            assert "TOOLS" not in prompt and "tool_results" not in prompt
            assert len(prompt) < 48000
            self.calls.append(max_output_tokens)
            return json.dumps(selected)

    model = Model()
    agent = ProjectArchitectureAgent(model, generate=ModelGateway(model))
    tools = fresh()
    composition = asyncio.run(agent.compose_diagram(tools, original))
    assert composition.completion_status == "complete"
    assert composition.composition_origin == "host_fallback"
    assert (
        composition.diagram.nodes == ArchitectureDiagram.model_validate(selected).nodes
    )
    assert not missing_views(original.architecture, composition.diagram)
    assert (
        len(composition.diagram.nodes) == 2
    )  # The host did not add the omitted adapter.
    assert model.calls == [3000, 3000]  # One directed correction before fallback.
    assert composition.usage.model_calls == 2 and composition.usage.tool_calls == 0
    assert not tools.retrieved_evidence
    assert original.architecture.diagram is None


@pytest.mark.parametrize("failure", ["direction", "provider"])
def test_composition_failure_preserves_report_and_guarantees_fallback_views(
    fixture, failure
):
    _, fresh, original, _, _ = fixture
    before = original.model_dump_json()

    class Model:
        calls = 0

        async def generate(self, prompt):
            self.calls += 1
            if failure == "provider":
                raise RuntimeError("Unavailable")
            raw = original.architecture.diagram.model_dump(mode="json")
            raw["edges"][0].update(source="port", target="use_case")
            return json.dumps(raw)

    model = Model()
    result = asyncio.run(
        ProjectArchitectureAgent(model).compose_diagram(fresh(), original)
    )
    assert result.completion_status == "complete" and result.diagram is not None
    assert result.composition_origin == "host_fallback"
    assert not missing_views(original.architecture, result.diagram)
    assert result.execution_issues and model.calls == 2
    assert original.model_dump_json() == before


def test_composition_external_cancellation_propagates(fixture):
    _, fresh, original, _, _ = fixture

    async def scenario():
        entered = asyncio.Event()

        class Model:
            async def generate(self, prompt):
                entered.set()
                await asyncio.sleep(3600)

        task = asyncio.create_task(
            ProjectArchitectureAgent(Model()).compose_diagram(fresh(), original)
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_missing_views_are_corrected_once_by_model(fixture):
    _, fresh, original, _, _ = fixture

    class Model:
        calls = 0

        async def generate(self, prompt):
            self.calls += 1
            if self.calls == 1:
                return original.architecture.diagram.model_dump_json()
            assert "CORRECTION" in prompt
            data = json.loads(str(prompt).split("\nDIAGRAM_DATA\n", 1)[1])
            assert data["required_views"] == ["structure", "dependencies"]
            return complete_views(
                original.architecture, original.architecture.diagram
            ).model_dump_json()

    model = Model()
    composition = asyncio.run(
        ProjectArchitectureAgent(model).compose_diagram(fresh(), original)
    )
    assert composition.composition_origin == "model_repaired"
    assert model.calls == 2 and not composition.execution_issues
    assert {
        view.view_kind for view in [composition.diagram, *composition.diagram.views]
    } == {"structure", "dependencies"}


def test_fallback_adds_flow_only_for_explicit_supported_calls(fixture):
    tools, _, original, _, _ = fixture
    plain = complete_views(original.architecture)
    assert len(plain.views) == 1
    assert any("runtime flow" in limitation for limitation in plain.limitations)
    raw = original.architecture.model_dump(mode="json")
    raw["connections"][0]["kind"] = "calls"
    raw["connections"][1]["kind"] = "implements"
    report = ArchitectureReport.model_validate(raw)
    completed = complete_views(report)
    assert not missing_views(report, completed)
    assert {view.view_kind for view in [completed, *completed.views]} == {
        "structure",
        "dependencies",
        "flow",
    }
    flow = next(view for view in completed.views if view.view_kind == "flow")
    assert all(edge.kind == "calls" for edge in flow.edges)
    validate_report(tools, report.model_copy(update={"diagram": completed}))


def test_empty_connection_report_has_explicit_dependency_and_flow_limits(fixture):
    report = fixture[2].architecture.model_copy(
        update={"connections": (), "diagram": None}
    )
    diagram = complete_views(report)
    assert not diagram.views[0].edges
    assert any(
        "No connections" in limitation for limitation in diagram.views[0].limitations
    )
    assert any("runtime flow" in limitation for limitation in diagram.limitations)


def test_pipeline_composes_original_and_revised_views_before_their_reviews(fixture):
    from server.runtimes.repository.model_runtime import ModelGateway

    _, fresh, original, snapshot, workspace = fixture
    original = original.model_copy(
        update={
            "architecture": original.architecture.model_copy(update={"diagram": None})
        }
    )
    order = []

    class Model:
        calls = 0

        async def generate_with_output_limit(self, prompt, *, max_output_tokens):
            self.calls += 1
            order.append("compose")
            raw = fixture[2].architecture.diagram.model_dump(mode="json")
            raw["title"] = (
                "Original selected view" if self.calls == 1 else "Revised selected view"
            )
            return complete_views(
                original.architecture, ArchitectureDiagram.model_validate(raw)
            ).model_dump_json()

    model = Model()
    gateway = ModelGateway(model)

    class Architect(ProjectArchitectureAgent):
        async def run(self, tools, orientation=None, **kwargs):
            order.append("investigate")
            return original

    class Validator:
        calls = 0

        async def run(self, tools, result, **kwargs):
            self.calls += 1
            order.append("validate")
            assert result.architecture.diagram.title == (
                "Original selected view" if self.calls == 1 else "Revised selected view"
            )
            targets = review_targets(fresh(), result)
            if self.calls == 1:
                target = next(
                    target for target in targets if target.id == "/diagram/scope"
                )
                findings = (
                    SemanticFinding(
                        target_id=target.id,
                        checked_statement=target.claim.statement,
                        verdict="insufficient_evidence",
                        reason="Inspect composition.",
                        counterevidence_check="Runtime wiring unknown.",
                        missing_evidence=(
                            {
                                "question": "Inspect composition.",
                                "paths": ("service.py",),
                            },
                        ),
                    ),
                )
            else:
                findings = findings_for(fresh, result)
            done = {finding.target_id for finding in findings}
            return SemanticValidationResult(
                snapshot_hash=result.snapshot_hash,
                report_hash=report_hash(result),
                original_result=result,
                completion_status="complete" if self.calls == 2 else "partial",
                verdict="accepted" if self.calls == 2 else "needs_evidence",
                selected_target_ids=tuple(target.id for target in targets),
                pending_target_ids=tuple(
                    target.id for target in targets if target.id not in done
                ),
                findings=findings,
                usage=BudgetUsage(),
                telemetry=ExecutionTelemetry(),
            )

    result = asyncio.run(
        ProjectArchitecturePipeline(
            Architect(model, generate=gateway), validator=Validator()
        ).run(
            snapshot,
            budget=ExecutionBudget(),
            workspace_root=workspace,
            include_orientation=False,
        )
    )
    assert order == [
        "investigate",
        "compose",
        "validate",
        "investigate",
        "compose",
        "validate",
    ]
    assert result.diagram_composition.usage.model_calls == 1
    assert result.semantic_validation.diagram_revision.usage.model_calls == 1
    assert (
        result.semantic_validation.diagram_revision.telemetry.model_calls[
            0
        ].objective_id
        == "diagram_revision"
    )
    assert result.model_calls == 2
    assert result.diagram.report_origin == "revised"
    assert "Revised selected view" in result.diagram.mermaid
    assert result.architecture.architecture.diagram.title == "Original selected view"
    assert original.architecture.diagram is None


def test_pipeline_selects_revised_diagram_with_matching_review_only(fixture):
    _, fresh, original, snapshot, workspace = fixture
    raw = original.architecture.model_dump(mode="json")
    raw["diagram"]["title"] = "Revised component view"
    revised = original.model_copy(
        update={"architecture": ArchitectureReport.model_validate(raw)}
    )

    class Architect:
        async def run(self, tools, orientation=None, **kwargs):
            return revised if kwargs.get("feedback") else original

    class Validator:
        async def run(self, tools, result, **kwargs):
            findings = findings_for(fresh, result)
            if result is original:
                findings = (
                    SemanticFinding(
                        target_id="/diagram/scope",
                        checked_statement=next(
                            item
                            for item in review_targets(fresh(), original)
                            if item.id == "/diagram/scope"
                        ).claim.statement,
                        verdict="insufficient_evidence",
                        reason="Composition not inspected.",
                        counterevidence_check="Wiring remains unknown.",
                        missing_evidence=(
                            {
                                "question": "Inspect composition.",
                                "paths": ("service.py",),
                            },
                        ),
                    ),
                )
            ids = tuple(target.id for target in review_targets(fresh(), result))
            done = {finding.target_id for finding in findings}
            return SemanticValidationResult(
                snapshot_hash=result.snapshot_hash,
                report_hash=report_hash(result),
                original_result=result,
                completion_status="complete" if result is revised else "partial",
                verdict="accepted" if result is revised else "needs_evidence",
                selected_target_ids=ids,
                pending_target_ids=tuple(
                    identifier for identifier in ids if identifier not in done
                ),
                findings=findings,
                usage=BudgetUsage(),
                telemetry=ExecutionTelemetry(),
            )

    pipeline = ProjectArchitecturePipeline(Architect(), validator=Validator())
    result = asyncio.run(
        pipeline.run(
            snapshot,
            budget=ExecutionBudget(),
            workspace_root=workspace,
            include_orientation=False,
        )
    )
    assert result.diagram.report_origin == "revised"
    assert result.diagram.report_hash == report_hash(revised)
    assert "Revised component view" in result.diagram.mermaid
    assert all(edge.semantic_verdict == "supported" for edge in result.diagram.edges)
    assert result.architecture.architecture.diagram.title == "Local component view"


def test_runner_checkpoints_before_503_and_resumes_without_investigation(
    fixture, tmp_path, monkeypatch
):
    from server import repository_runner
    from server.agents.project_analysis.project_semantic_validation import (
        ProjectSemanticValidationAgent,
    )

    _, fresh, original, _, workspace = fixture
    checkpoint = tmp_path / "saved-report.json"
    selected = original.architecture.diagram.model_dump(mode="json")
    original = original.model_copy(
        update={
            "architecture": original.architecture.model_copy(update={"diagram": None})
        }
    )
    investigation_calls, reviews = [], []

    async def investigate(self, tools, orientation=None, **kwargs):
        investigation_calls.append(True)
        return original

    async def validate(self, tools, report, **kwargs):
        reviews.append(report.architecture.diagram)
        targets = review_targets(fresh(), report)
        return SemanticValidationResult(
            snapshot_hash=report.snapshot_hash,
            report_hash=report_hash(report),
            original_result=report,
            completion_status="complete",
            verdict="accepted",
            selected_target_ids=tuple(target.id for target in targets),
            pending_target_ids=(),
            findings=findings_for(fresh, report),
            usage=BudgetUsage(),
            telemetry=ExecutionTelemetry(),
        )

    class Unavailable(Exception):
        status_code = 503

    class Model:
        failing = True
        calls = 0

        async def generate(self, prompt):
            assert repository_runner.load_architecture_report(checkpoint) == original
            self.calls += 1
            if self.failing:
                raise Unavailable("Service temporarily overloaded")
            return complete_views(
                original.architecture, ArchitectureDiagram.model_validate(selected)
            ).model_dump_json()

    model = Model()
    monkeypatch.setattr(repository_runner, "create_model", lambda arguments: model)
    monkeypatch.setattr(ProjectArchitectureAgent, "run", investigate)
    monkeypatch.setattr(ProjectSemanticValidationAgent, "run", validate)
    parser = repository_runner.build_parser("architecture")
    base = [
        str(workspace / "checkout"),
        "--workspace-root",
        str(workspace),
        "--quiet",
        "--checkpoint",
        str(checkpoint),
        "--skip-orientation",
        "--diagram",
        "--diagram-retry-backoff",
        "0",
        "--validate-semantics",
        "--no-semantic-return",
    ]
    data, usable = asyncio.run(repository_runner.run(parser.parse_args(base)))
    assert usable and data["pipeline_status"] == "partial"
    assert model.calls == 3 and len(investigation_calls) == 1
    assert len(reviews) == 1 and reviews[0] is not None
    assert data["diagram_composition"]["composition_origin"] == "host_fallback"
    assert data["pipeline_usage"]["provider_attempts"] == 3
    assert (
        "Service temporarily overloaded"
        in data["diagram_composition"]["execution_issues"][0]["message"]
    )
    assert repository_runner.load_architecture_report(checkpoint) == original
    model.failing = False
    resumed, usable = asyncio.run(
        repository_runner.run(
            parser.parse_args(base + ["--resume-report", str(checkpoint)])
        )
    )
    assert usable and resumed["architecture_diagram"]
    assert len(investigation_calls) == 1 and model.calls == 4
    assert resumed["pipeline_usage"]["provider_attempts"] == 1
    assert resumed["pipeline_stages"][1]["status"] == "skipped"
    assert reviews[-1] is not None

    # A changed checkout cannot silently reuse evidence from the saved snapshot.
    (workspace / "checkout" / "service.py").write_text("class Changed: pass\n")
    with pytest.raises(ValueError, match="snapshot"):
        asyncio.run(
            repository_runner.run(
                parser.parse_args(base + ["--resume-report", str(checkpoint)])
            )
        )
    assert model.calls == 4


def test_runner_routes_configured_diagram_model_only_to_composition(
    fixture, tmp_path, monkeypatch
):
    from server import repository_runner

    _, _, original, _, workspace = fixture
    view = original.architecture.diagram.model_dump(mode="json")
    original = original.model_copy(
        update={
            "architecture": original.architecture.model_copy(update={"diagram": None})
        }
    )
    saved = tmp_path / "report.json"
    saved.write_text(original.model_dump_json(), encoding="utf-8")
    configurations = []

    class Model:
        async def generate(self, prompt):
            assert configurations[-1] == (
                "diagram-provider",
                "diagram-model",
                "diagram-key",
            )
            assert "\nDIAGRAM_DATA\n" in prompt
            return json.dumps(view)

    def create(arguments):
        configurations.append((arguments.provider, arguments.model, arguments.api_key))
        return Model()

    monkeypatch.setattr(repository_runner, "create_model", create)
    arguments = repository_runner.build_parser("architecture").parse_args(
        [
            str(workspace / "checkout"),
            "--workspace-root",
            str(workspace),
            "--quiet",
            "--resume-report",
            str(saved),
            "--checkpoint",
            str(saved),
            "--diagram-model",
            "diagram-model",
            "--diagram-provider",
            "diagram-provider",
            "--diagram-api-key",
            "diagram-key",
        ]
    )
    data, usable = asyncio.run(repository_runner.run(arguments))
    assert usable and data["architecture_diagram"]
    assert configurations == [
        (None, None, None),
        ("diagram-provider", "diagram-model", "diagram-key"),
    ]
    assert data["run_metadata"]["diagram_model"]["name"] == "protocol_smoke"
