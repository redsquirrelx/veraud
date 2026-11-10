"""Documentary seeds remain grounded navigation, not findings or code evidence."""

import asyncio
import importlib.util
import json
from pathlib import Path
from typing import get_args

import pytest
from langchain_core.messages import AIMessage

from server.agents.architecture_context.schemas import (
    ArchitectureContextResult,
    FinalizationDiagnostic,
    KnowledgeClaim,
    KnowledgeIssue,
    RetrievalCategory,
)
from server.agents.maintainability.v2.modularity.architecture_boundary.planning import (
    prepare_planning as original_planning,
)
from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven import (
    ArchitectureBoundaryAgent,
    AuditRequest,
    BoundaryConfig,
)
from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.documentation import (
    claim_identity,
    link_structural_opportunities,
    prepare_documentation,
)
from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.planning import (
    planning_diagnostics,
    prepare_planning,
)
from server.runtimes.repository.context import RepositoryContext
from server.runtimes.repository.schemas import ExecutionBudget, RepositoryInput
from server.runtimes.repository.tools import RepositoryToolset
from server.services.document_indexing import DocumentRecord, IndexReference
from server.services.document_indexing.service import identifier
from server.services.repository_analysis import RepositoryAnalysisService


@pytest.fixture
def tools(tmp_path):
    root = tmp_path / "repo"
    contents = {
        "app/__init__.py": "",
        "app/api.py": "from .store import Store\nclass Api:\n    pass\n",
        "app/store.py": "from .api import Api\nclass Store:\n    pass\n",
    }
    for path, text in contents.items():
        file = root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8")
    snapshot = RepositoryAnalysisService().analyze_sync(root)
    snapshot = snapshot.model_copy(update={"repository": snapshot.repository.model_copy(update={"commit": "abc"})})
    return RepositoryToolset(RepositoryContext(snapshot, RepositoryInput(
        snapshot_hash=snapshot.repository.snapshot_hash,
        budget=ExecutionBudget(max_input_tokens_per_call=50_000),
    )), workspace_root=tmp_path)


def claim(statement="app.api must not depend on app.store implementations.", **updates):
    return KnowledgeClaim.model_validate({
        "category": "constraints", "subject": "app.api", "statement": statement,
        "related_subjects": ["app.store"], "certainty": "explicit", "section_ids": ["s1"],
        "reasoning": "An adopted dependency boundary.", "constraint": "prohibited",
        "evidence": [{"section_id": "s1", "start_line": 1, "end_line": 1, "quote": "Documented obligation.\n"}],
        **updates,
    })


def context(tools, claims, **updates):
    snapshot = tools.accessible_snapshot
    index = IndexReference(index_id="index", repository_id=identifier(str(Path(snapshot.repository.root_path).resolve())),
        commit=snapshot.repository.commit)
    return ArchitectureContextResult.model_validate({
        "document_index": index, "knowledge": claims, "knowledge_issues": [],
        "covered_categories": [], "pending_categories": list(get_args(RetrievalCategory)),
        "evaluated_categories": list(get_args(RetrievalCategory)), "coverage_assessment_status": "completed",
        "consulted_documents": [DocumentRecord(**index.model_dump(), path="docs/rules.md", content_hash="hash", line_count=10)],
        "section_paths": {"s1": "docs/rules.md", "s2": "docs/rules.md"}, "validation_errors": [],
        "execution_status": "partial", "finalization_reason": "incomplete_coverage", **updates,
    })


def prepare(tools, source=None, limit=100):
    return prepare_planning(tools.accessible_snapshot, AuditRequest(documented_architecture=source),
        limit=limit, check=lambda: None)


def docs(menu):
    return [task for task in menu if task.structural_signal.kind == "documented_boundary"]


class PlanningModel:
    def __init__(self):
        self.contexts = []

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages, **kwargs):
        payload = json.loads(messages[1].content)
        self.contexts.append(payload)
        assert "opportunities" in payload  # Investigation must never run in this harness.
        return AIMessage(content=json.dumps({"opportunity_ids": [item["id"] for item in
            payload["opportunities"][:payload["budget"]["max_investigations"]]]}),
            usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})


def run_plan(tools, source, *, model=None, **overrides):
    model = model or PlanningModel()
    config = BoundaryConfig(provider_request_interval_seconds=0, max_output_tokens=1000, **overrides)
    execution = ArchitectureBoundaryAgent.execution_type(model, config, tools, AuditRequest(documented_architecture=source))

    async def run():
        with execution.timing.stage("investigation"):
            return (await execution.plan_investigation(execution.initial_state()))["result"]
    return asyncio.run(run()), model


def test_without_documentation_preserves_structural_menu(tools):
    menu, inventory, _ = prepare(tools)
    original, _, _ = original_planning(tools.accessible_snapshot, AuditRequest(), limit=100, check=lambda: None)
    assert [task.model_dump(exclude={"document_claim_ids"}) for task in menu] == [task.model_dump() for task in original]
    assert not docs(menu)
    assert inventory["documentary_diagnostics"]["context_status"] == "not_provided"


def test_normative_claim_has_separate_identity_and_original_provenance(tools):
    original = claim()
    source = context(tools, [original])
    menu, inventory, _ = prepare(tools, source)
    task = docs(menu)[0]
    claim_id = task.document_claim_ids[0]
    record = inventory["_document_claims"][claim_id]
    assert claim_id.startswith("document_claim_")
    assert record.claim == original and record.document_index == source.document_index
    assert record.section_paths == {"s1": "docs/rules.md"}
    assert task.scope == ["app/api.py", "app/store.py"]
    # Planned refs are indexed navigation, never fabricated dependencies.
    assert {ref.id for ref in task.structural_signal.relationships} <= {
        item.id for item in tools.accessible_snapshot.relationships}
    assert not task.structural_signal.symbol_ids
    assert any(task.structural_signal.kind == "cycle" for task in menu)


def test_groups_same_boundary_without_losing_multiple_evidence_references(tools):
    first = claim()
    second = claim("app.api must depend on the public ports of app.store.", constraint="required")
    # Explicit interface access and dependency rules are different mechanisms,
    # so use a dependency-specific companion without an encapsulation predicate.
    second = second.model_copy(update={"statement": "app.store must implement dependency interfaces consumed by app.api."})
    third = claim("app.api may depend on app.store interfaces.", constraint="allowed",
        section_ids=["s1", "s2"], evidence=[
            {"section_id": "s1", "start_line": 1, "end_line": 1, "quote": "First.\n"},
            {"section_id": "s2", "start_line": 2, "end_line": 2, "quote": "Second.\n"},
        ])
    source = context(tools, [first, second, third])
    menu, inventory, _ = prepare(tools, source)
    assert len(docs(menu)) == 1
    assert len(docs(menu)[0].document_claim_ids) == 3
    assert all(record.claim in [first, second, third] for record in inventory["_document_claims"].values())
    assert len(inventory["_document_claims"][claim_identity(third, source)].claim.evidence) == 2


def test_same_files_different_obligations_are_not_deduplicated(tools):
    source = context(tools, [claim(), claim("app.api must not access private state owned by app.store.")])
    menu, inventory, _ = prepare(tools, source)
    assert len(docs(menu)) == 2
    assert len({task.id for task in menu}) == len(menu)
    assert len({tuple(task.scope) for task in docs(menu)}) == 1
    assert inventory["opportunity_diagnostics"]["generated_by_type"]["cycle"] >= 1


def test_document_paths_never_map_to_code_and_unresolved_owners_stay_pending(tools):
    source = context(tools, [claim("MissingService must not depend on app.missing.", subject="MissingService", related_subjects=[])])
    menu, inventory, _ = prepare(tools, source)
    assert not docs(menu)
    record = next(iter(inventory["_document_claims"].values()))
    assert record.status == "unmapped" and not record.opportunity_ids
    assert "docs/rules.md" not in record.scope_paths
    assert planning_diagnostics(inventory, menu, [], [])["documentation"]["unmapped"] == 1


@pytest.mark.parametrize("kind", ["unknown", "ambiguity", "discrepancy"])
def test_related_uncertainty_is_not_a_normative_task(tools, kind):
    source = context(tools, [claim()], knowledge_issues=[KnowledgeIssue(category="constraints", kind=kind,
        question="Which boundary is adopted?", section_ids=["s1"])])
    menu, inventory, limits = prepare(tools, source)
    assert not docs(menu)
    assert next(iter(inventory["_document_claims"].values())).status == "uncertain"
    assert any("not an exhaustive" in item for item in limits)


@pytest.mark.parametrize("field", ["repository_id", "commit"])
def test_incompatible_context_does_not_disable_structural_planning(tools, field):
    source = context(tools, [claim()])
    source = source.model_copy(update={"document_index": source.document_index.model_copy(update={field: "foreign"})})
    menu, inventory, _ = prepare(tools, source)
    assert menu and not docs(menu)
    assert inventory["documentary_diagnostics"]["context_status"] == "incompatible"
    assert next(iter(inventory["_document_claims"].values())).status == "incompatible"


def test_claim_and_opportunity_ids_are_stable_under_input_reordering(tools):
    first, second = claim(), claim("app.store must implement dependency interfaces consumed by app.api.", constraint="required")
    source = context(tools, [first, second, first])
    menu, inventory, _ = prepare(tools, source)
    reversed_source = source.model_copy(update={"knowledge": [second, first]})
    other, other_inventory, _ = prepare(tools, reversed_source)
    assert docs(menu) == docs(other)
    assert inventory["_document_claims"] == other_inventory["_document_claims"]
    assert inventory["documentary_diagnostics"]["received"] == 3


def test_identity_does_not_depend_on_evidence_or_subject_reference_order(tools):
    original = claim(section_ids=["s1", "s2"], related_subjects=["app.store", "app.api"], evidence=[
        {"section_id": "s1", "start_line": 1, "end_line": 1, "quote": "First.\n"},
        {"section_id": "s2", "start_line": 2, "end_line": 2, "quote": "Second.\n"},
    ])
    source = context(tools, [original])
    reordered = original.model_copy(update={"evidence": list(reversed(original.evidence)),
        "section_ids": list(reversed(original.section_ids)), "related_subjects": list(reversed(original.related_subjects))})
    assert claim_identity(original, source) == claim_identity(reordered, source)


def test_one_broad_claim_can_seed_independently_owned_scopes(tools):
    snapshot = tools.accessible_snapshot.model_copy(update={"relationships": ()})
    files = {file.id: file for file in snapshot.files if file.path in {"app/api.py", "app/store.py"}}
    projects = {key: file.path for key, file in files.items()}
    source = context(tools, [claim("app must use dependency interfaces.", subject="app", related_subjects=[])])
    tasks, records, _, _ = prepare_documentation(snapshot, AuditRequest(documented_architecture=source),
        files, set(files), projects, check=lambda: None)
    assert len(tasks) == 2
    assert tasks[0].document_claim_ids == tasks[1].document_claim_ids
    assert len(next(iter(records.values())).opportunity_ids) == 2


def test_distinct_symbol_boundaries_sharing_files_are_not_merged(tools):
    source = context(tools, [
        claim("Api must not access private state in app.store.", subject="Api"),
        claim("Store must not access private state in app.api.", subject="Store"),
    ])
    # Both mention the same modules, but distinct uniquely indexed API owners.
    source = source.model_copy(update={"knowledge": [item.model_copy(update={
        "related_subjects": ["app.store", "app.api"]}) for item in source.knowledge]})
    menu, _, _ = prepare(tools, source)
    assert len(docs(menu)) == 2
    assert all(task.structural_signal.symbol_ids for task in docs(menu))


def test_explicit_cross_project_interaction_keeps_both_owners(tools):
    snapshot = tools.accessible_snapshot
    files = {file.id: file for file in snapshot.files if file.path in {"app/api.py", "app/store.py"}}
    projects = {key: file.path for key, file in files.items()}
    tasks, _, _, _ = prepare_documentation(snapshot, AuditRequest(documented_architecture=context(tools, [claim()])),
        files, set(files), projects, check=lambda: None)
    assert len(tasks) == 1
    assert tasks[0].scope_kind == "inter_application"
    assert len(tasks[0].project_ids) == 2


def test_validation_errors_only_block_affected_documentary_claims(tools):
    source = context(tools, [claim()], validation_errors=[FinalizationDiagnostic(
        target="claim", section_ids=["s1"], reason="Rejected quotation")])
    menu, inventory, _ = prepare(tools, source)
    assert not docs(menu)
    assert next(iter(inventory["_document_claims"].values())).status == "uncertain"
    unaffected = source.model_copy(update={"validation_errors": [FinalizationDiagnostic(
        target="claim", section_ids=["other"], reason="Rejected unrelated quotation")]})
    assert docs(prepare(tools, unaffected)[0])


@pytest.mark.parametrize("item", [
    claim("app.api handles orders.", constraint="unspecified"),
    claim("app.api must return integer cents.", reasoning="Money representation requirement."),
    claim("app.api should not depend on app.store.", certainty="derived"),
    claim("Proposed: app.api must not depend on app.store."),
])
def test_non_boundary_or_uncertain_assertions_are_diagnosed(tools, item):
    menu, inventory, _ = prepare(tools, context(tools, [item]))
    assert not docs(menu)
    assert next(iter(inventory["_document_claims"].values())).status in {"uncertain", "not_applicable"}


def test_combined_model_menu_preserves_original_claims_and_planning_coverage(tools):
    source = context(tools, [claim()])
    result, model = run_plan(tools, source, max_planned_investigations=1)
    assert len(model.contexts) == 1
    payload = model.contexts[0]
    assert any(item["kind"] == "cycle" for item in payload["opportunities"])
    assert any(item["kind"] == "documented_boundary" for item in payload["opportunities"])
    assert payload["document_claims"]
    assert len(result.plan.investigations) <= 1 and not result.findings
    coverage = result.investigation_coverage["documentation"]
    assert coverage["received"] == coverage["applicable"] == coverage["grouped"] == 1
    assert coverage["investigated"] == 0
    assert result.plan.document_claims


@pytest.mark.parametrize("abstain", [False, True])
def test_documentary_selection_is_grounded_and_never_forced(tools, abstain):
    class Selector(PlanningModel):
        async def ainvoke(self, messages, **kwargs):
            payload = json.loads(messages[1].content)
            self.contexts.append(payload)
            ids = [] if abstain else [item["id"] for item in payload["opportunities"] if item["kind"] == "documented_boundary"]
            return AIMessage(content=json.dumps({"opportunity_ids": ids}))

    source = context(tools, [claim()])
    result, _ = run_plan(tools, source, model=Selector())
    selected = result.plan.investigations
    assert len(selected) == (0 if abstain else 1)
    assert result.investigation_coverage["documentation"]["selected"] == (0 if abstain else 1)
    if selected:
        assert selected[0].document_claim_ids == [claim_identity(source.knowledge[0], source)]
        assert result.plan.document_claims[selected[0].document_claim_ids[0]].claim == source.knowledge[0]


def test_menu_and_context_limits_leave_claims_recoverable(tools):
    source = context(tools, [claim("app.api must not access private state owned by app.store.")])
    menu, inventory, _ = prepare(tools, source, limit=1)
    status = planning_diagnostics(inventory, menu, [], [])["documentation"]
    assert status["grouped"] == 1
    assert status["omitted_by_menu_or_context"] + status["not_selected"] == 1
    # Even a full literal quote larger than the model allowance is retained in
    # the output registry; whole opportunities, not quotations, leave the prompt.
    enormous = claim(evidence=[{"section_id": "s1", "start_line": 1, "end_line": 1, "quote": "source " * 20_000}])
    result, model = run_plan(tools, context(tools, [enormous]), max_context_characters=12_000)
    assert next(iter(result.plan.document_claims.values())).claim == enormous
    assert result.investigation_coverage["documentation"]["omitted_by_menu_or_context"] == 1
    assert model.contexts  # The oversized quote must not evict usable structural planning.
    assert all(not item.get("document_claims") for item in model.contexts)


def test_runner_graph_stops_after_planning(tools):
    path = Path(__file__).parents[1] / "src/test-agents/run_architecture_boundary_doc_driven.py"
    spec = importlib.util.spec_from_file_location("doc_driven_runner", path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    model = PlanningModel()
    config = BoundaryConfig(provider_request_interval_seconds=0, max_output_tokens=1000)
    result = asyncio.run(runner.PlanningOnlyBoundaryAgent(model, config).run(tools,
        AuditRequest(documented_architecture=context(tools, [claim()]))))
    assert result.termination_reason == "planning_completed"
    assert len(model.contexts) == 1
    assert result.plan.investigations and not result.investigation_results
    assert not result.findings and result.iterations == 0


def indexed_tools(tmp_path, contents):
    root = tmp_path / "indexed"
    for name, content in contents.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    snapshot = RepositoryAnalysisService().analyze_sync(root)
    snapshot = snapshot.model_copy(update={"repository": snapshot.repository.model_copy(update={"commit": "abc"})})
    return RepositoryToolset(RepositoryContext(snapshot, RepositoryInput(snapshot_hash=snapshot.repository.snapshot_hash,
        budget=ExecutionBudget(max_input_tokens_per_call=50_000))), workspace_root=tmp_path)


def test_cycle_reuses_applicable_rule_without_a_duplicate_documentary_probe(tools):
    rule = claim("app.api and app.store must not form dependency cycles.", subject="Feature packages")
    source = context(tools, [rule])
    menu, inventory, _ = prepare(tools, source)
    cycle = next(task for task in menu if task.structural_signal.kind == "cycle")
    key = claim_identity(rule, source)
    assert cycle.document_claim_ids == [key]
    assert not docs(menu)
    assert all(cycle.id in portion.opportunity_ids for portion in inventory["_document_claims"][key].portions)
    diagnostics = planning_diagnostics(inventory, menu, [cycle], [cycle])["documentation"]
    assert diagnostics["linked_to_structural"] == diagnostics["selected"] == 1
    assert diagnostics["investigated"] == 0 and not diagnostics["pending_claim_ids"]


def test_cycle_with_unrelated_direction_rule_does_not_acquire_claims(tools):
    source = context(tools, [claim()])
    menu, _, _ = prepare(tools, source)
    assert all(not task.document_claim_ids for task in menu if task.structural_signal.kind == "cycle")


def test_cycle_respects_explicit_documentary_exceptions(tools):
    rule = claim("app must remain acyclic except app.api.", subject="app", related_subjects=[])
    menu, inventory, _ = prepare(tools, context(tools, [rule]))
    assert all(not task.document_claim_ids for task in menu if task.structural_signal.kind == "cycle")
    assert "app/api.py" in next(iter(inventory["_document_claims"].values())).excluded_paths


def test_large_rule_is_partitioned_with_explicit_partial_selection(tmp_path):
    contents = {"pkg/__init__.py": "", "pkg/domain/__init__.py": "", "pkg/adapters/__init__.py": ""}
    for index in range(8):
        contents[f"pkg/domain/d{index}.py"] = f"from pkg.adapters.a{index} import A{index}\nclass D{index}: pass\n"
        contents[f"pkg/adapters/a{index}.py"] = f"class A{index}: pass\n"
    toolset = indexed_tools(tmp_path, contents)
    rule = claim("pkg.domain must not import concrete pkg.adapters implementations.",
        subject="pkg.domain", related_subjects=["pkg.adapters"])
    source = context(toolset, [rule])
    menu, inventory, _ = prepare(toolset, source)
    key = claim_identity(rule, source)
    record = inventory["_document_claims"][key]
    assert record.status == "applicable" and len(record.scope_paths) > 12
    assert len(record.portions) >= 8
    tasks = [task for task in menu if key in task.document_claim_ids]
    assert len(tasks) >= 8 and all(1 <= len(task.scope) <= 12 for task in tasks)
    assert any(task.structural_signal.kind == "component_boundary" for task in tasks)
    selected = tasks[:1]
    diagnostics = planning_diagnostics(inventory, menu, selected, selected)["documentation"]
    assert diagnostics["selected"] == 1 and diagnostics["partial"] == 1
    assert key in diagnostics["pending_claim_ids"]
    assert diagnostics["pending_portions"][key]
    assert diagnostics["investigated"] == 0


def test_unique_documented_path_suffix_is_corroborated_not_invented(tmp_path):
    toolset = indexed_tools(tmp_path, {"src/shoplab/bootstrap.py": "def build_services(): pass\n"})
    rule = claim("Bindings must be assembled in shoplab/bootstrap.py.",
        subject="Composition boundary", related_subjects=[], constraint="required")
    menu, inventory, _ = prepare(toolset, context(toolset, [rule]))
    record = next(iter(inventory["_document_claims"].values()))
    assert record.mapping_basis == "corroborated"
    assert record.scope_paths == ["src/shoplab/bootstrap.py"]
    assert docs(menu)[0].scope == record.scope_paths


def test_multiple_possible_source_roots_remain_ambiguous(tmp_path):
    toolset = indexed_tools(tmp_path, {"src/shoplab/bootstrap.py": "def build(): pass\n",
        "legacy/shoplab/bootstrap.py": "def build(): pass\n"})
    rule = claim("Bindings must be assembled in shoplab/bootstrap.py.",
        subject="Composition boundary", related_subjects=[], constraint="required")
    menu, inventory, _ = prepare(toolset, context(toolset, [rule]))
    record = next(iter(inventory["_document_claims"].values()))
    assert record.mapping_basis == "ambiguous" and record.status == "unmapped"
    assert not docs(menu)


@pytest.mark.parametrize(("statement", "expected"), [
    ("app.api allowed imports are app.store interfaces.", "applicable"),
    ("app.api has an import example involving app.store.", "not_applicable"),
    ("app.api displays an order total.", "not_applicable"),
])
def test_unspecified_modality_uses_actual_architectural_language(tools, statement, expected):
    rule = claim(statement, constraint="unspecified")
    _, inventory, _ = prepare(tools, context(tools, [rule]))
    assert next(iter(inventory["_document_claims"].values())).status == expected


def test_one_claim_can_enrich_independent_cycles_without_double_counting(tmp_path):
    contents = {"pkg/__init__.py": ""}
    for group in ("one", "two"):
        contents[f"pkg/{group}/__init__.py"] = ""
        contents[f"pkg/{group}/a.py"] = "from .b import b\ndef a(): pass\n"
        contents[f"pkg/{group}/b.py"] = "from .a import a\ndef b(): pass\n"
    toolset = indexed_tools(tmp_path, contents)
    rule = claim("pkg must remain acyclic.", subject="pkg", related_subjects=[], constraint="required")
    source = context(toolset, [rule])
    menu, inventory, _ = prepare(toolset, source)
    cycles = [task for task in menu if task.structural_signal.kind == "cycle"]
    assert len(cycles) == 2 and all(task.document_claim_ids == [claim_identity(rule, source)] for task in cycles)
    diag = planning_diagnostics(inventory, menu, cycles, cycles)["documentation"]
    assert diag["linked_to_structural"] == diag["selected"] == 1
    assert diag["structural_investigations_enriched"] == 2
    assert diag["investigated"] == 0


def test_non_applicable_claims_are_not_pending_obligations(tools):
    source = context(tools, [claim(), claim("Display an order total.", constraint="unspecified")])
    menu, inventory, _ = prepare(tools, source)
    diag = planning_diagnostics(inventory, menu, [], [])["documentation"]
    assert diag["received"] == 2 and diag["applicable"] == 1 and diag["not_applicable"] == 1
    assert len(diag["pending_claim_ids"]) == 1
    assert not set(diag["pending_claim_ids"]) & set(diag["not_applicable_claim_ids"])


def test_documented_layer_labels_require_real_documentary_ownership(tmp_path):
    toolset = indexed_tools(tmp_path, {"src/project/domain/a.py": "class Entity: pass\n"})
    ownership = claim("Domain layer is located at project/domain/.", subject="Domain layer", related_subjects=[],
        category="components", constraint="unspecified")
    rule = claim("Domain allowed imports are standard-library value primitives only.",
        subject="Domain layer", related_subjects=[], constraint="unspecified")
    menu, inventory, _ = prepare(toolset, context(toolset, [ownership, rule]))
    record = inventory["_document_claims"][claim_identity(rule, context(toolset, [ownership, rule]))]
    assert record.mapping_basis == "corroborated" and record.status == "applicable"
    assert docs(menu)


def test_directed_applicability_does_not_reverse_a_two_owner_title(tools):
    rule = claim("app.api must not import app.store.", subject="app.api app.store isolation")
    menu, inventory, _ = prepare(tools, context(tools, [rule]))
    cycle = next(task for task in menu if task.structural_signal.kind == "cycle")
    probes = [cycle.model_copy(update={"id": ref.id, "structural_signal": cycle.structural_signal.model_copy(update={
        "kind": "direction", "relationships": [ref]})}) for ref in cycle.structural_signal.relationships]
    linked, _ = link_structural_opportunities(probes, inventory["_document_claims"], lambda: None)
    assert any(task.document_claim_ids for task in linked if task.structural_signal.relationships[0].source_path == "app/api.py")
    assert all(not task.document_claim_ids for task in linked if task.structural_signal.relationships[0].source_path == "app/store.py")


def test_large_documentary_attachment_does_not_evict_its_structural_cycle(tools):
    rule = claim("app.api and app.store must not form cycles.", subject="Feature packages",
        evidence=[{"section_id": "s1", "start_line": 1, "end_line": 1, "quote": "source " * 20_000}])
    result, model = run_plan(tools, context(tools, [rule]), max_context_characters=12_000)
    assert model.contexts and result.plan.investigations
    assert result.plan.investigations[0].structural_signal.kind == "cycle"
    assert not result.plan.investigations[0].document_claim_ids
    assert result.investigation_coverage["documentation"]["selected"] == 0
    assert result.investigation_coverage["documentation"]["pending_portions"]


def test_multiple_cycle_obligations_keep_each_original_reference(tools):
    first = claim("app.api and app.store must not form cycles.", subject="Feature packages")
    second = claim("app.api and app.store must remain acyclic.", subject="Feature packages", constraint="required",
        section_ids=["s2"], evidence=[{"section_id": "s2", "start_line": 2, "end_line": 2, "quote": "Second rule.\n"}])
    source = context(tools, [first, second])
    menu, inventory, _ = prepare(tools, source)
    cycle = next(task for task in menu if task.structural_signal.kind == "cycle")
    assert set(cycle.document_claim_ids) == {claim_identity(first, source), claim_identity(second, source)}
    assert not docs(menu)
    assert {inventory["_document_claims"][key].claim.evidence[0].section_id for key in cycle.document_claim_ids} == {"s1", "s2"}


def test_documented_group_resolution_is_order_independent(tmp_path):
    toolset = indexed_tools(tmp_path, {"src/project/domain/a.py": "class Entity: pass\n"})
    ownership = claim("Domain layer is located at project/domain/.", subject="Domain layer", related_subjects=[],
        category="components", constraint="unspecified")
    rule = claim("Domain must remain acyclic.", subject="Domain", related_subjects=[], constraint="unspecified")
    first_menu, first_inventory, _ = prepare(toolset, context(toolset, [ownership, rule]))
    other_menu, other_inventory, _ = prepare(toolset, context(toolset, [rule, ownership]))
    assert first_menu == other_menu
    assert first_inventory["_document_claims"] == other_inventory["_document_claims"]
