"""Synthetic regressions for bounded discovery and reference-only recovery."""

from types import SimpleNamespace

import pytest
from test_architecture_boundary_doc_driven_investigation import (
    Model,
    assess_all,
    run,
    verified_tools,
)
from test_architecture_boundary_doc_driven_planning import claim, context, prepare
from test_architecture_boundary_doc_driven_synthesis import candidate

from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven import (
    AuditRequest,
    BoundaryConfig,
)
from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.execution import (
    BoundaryExecution,
)
from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.investigation import (
    complete_citation_links,
    normalize_candidate_links,
    reference_errors,
)
from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.planning import (
    prepare_planning,
)
from server.agents.maintainability.v2.modularity.architecture_boundary_doc_driven.schemas import (
    BoundaryInvestigationResult,
    BoundaryToolQuery,
    ClaimAssessment,
)


def conclusion(ids):
    return BoundaryInvestigationResult(investigation_id="task", status="finding_candidate",
        summary="Observed dependency", justification="Inspect current source.",
        candidates=[candidate(document_claim_ids=ids)], claim_assessments=[
            ClaimAssessment(claim_id="restriction", status="contradicted", rationale="Direct construction."),
            ClaimAssessment(claim_id="exception", status="supported", rationale="Assembly is permitted elsewhere.")])


def test_favorable_reference_cleanup_preserves_verdicts_and_unknown_ids():
    original = conclusion(["restriction", "exception", "unknown"])
    normalized = normalize_candidate_links(original)
    assert normalized.candidates[0].document_claim_ids == ["restriction", "unknown"]
    assert original.candidates[0].document_claim_ids == ["restriction", "exception", "unknown"]
    assert normalized.claim_assessments == original.claim_assessments
    assert normalized.candidates[0].description == original.candidates[0].description
    assert normalized.limitations
    # A favorable-only candidate must not become code-first and escape validation.
    assert normalize_candidate_links(conclusion(["exception"])).candidates[0].document_claim_ids == ["exception"]


def test_citation_completion_never_supplies_assessment_source_or_unknown_ids():
    result = conclusion(["restriction"])
    result = result.model_copy(update={"candidates": [result.candidates[0].model_copy(update={
        "components": ["a.py"], "evidence_ids": ["source-a"]})],
        "claim_assessments": [result.claim_assessments[0].model_copy(update={
            "scope_paths": [], "code_evidence_ids": ["source-a"]}),
            result.claim_assessments[1].model_copy(update={"scope_paths": ["b.py"]})]})
    catalog = {"source_evidence_by_component": {"a.py": ["source-a"], "b.py": ["source-b"]},
        "examined_relationships": [], "evidence": [{"id": "source-a"}, {"id": "source-b"}]}
    normalized = complete_citation_links(result, catalog)
    assert normalized.claim_assessments[0].scope_paths == ["a.py"]
    assert normalized.claim_assessments[0].code_evidence_ids == ["source-a"]
    assert normalized.claim_assessments[1].code_evidence_ids == []
    assert normalized.claim_assessments[1].status == "supported"
    assert normalized.limitations and not result.limitations


def test_endpoint_repair_identifies_available_missing_citation():
    result = conclusion(["restriction"])
    item = result.candidates[0].model_copy(update={"evidence_ids": ["source-a"], "relationship_ids": ["edge"]})
    result = result.model_copy(update={"candidates": [item]})
    catalog = {"evidence": [{"id": "source-a", "kind": "source", "path": "a.py"}],
        "examined_relationships": [{"id": "edge", "source_path": "a.py", "target_path": "b.py"}],
        "source_evidence_by_component": {"a.py": ["source-a"], "b.py": ["source-b"]}}
    errors = reference_errors(SimpleNamespace(conclusion=result), "dependency_endpoints_source_not_inspected", catalog)
    error = next(row for row in errors if row["subject_id"] == item.id)
    assert error["missing_endpoint_path"] == "b.py"
    assert error["available_source_evidence_ids"] == ["source-b"]
    assert not error["source_required"]


def test_source_file_id_alias_cannot_bypass_scope_or_conflict(tmp_path):
    tools = verified_tools(tmp_path, {"a.py": "def run(): pass\n", "b.py": "def other(): pass\n"})
    execution = BoundaryExecution(Model(lambda _: {}), BoundaryConfig(), tools, AuditRequest())
    file = next(file for file in tools.accessible_snapshot.files if file.path == "a.py")
    task = SimpleNamespace(scope=["a.py"])
    query = BoundaryToolQuery(tool="get_source_excerpt", arguments={"file_id": file.id,
        "start_line": 1, "end_line": 1}, reason="Read implementation.")
    args, _ = execution._normalize_query(query, task)
    assert args["path"] == "a.py" and "file_id" not in args
    default_end, _ = execution._normalize_query(query.model_copy(update={
        "arguments": {"file_id": file.id, "start_line": 1}}), task)
    assert default_end["end_line"] == file.line_count
    with pytest.raises(ValueError, match="conflicting_source_path"):
        execution._normalize_query(query.model_copy(update={"arguments": {"file_id": file.id, "path": "b.py"}}), task)
    with pytest.raises(ValueError, match="scope_expansion_reason_required"):
        execution._normalize_query(query, SimpleNamespace(scope=["b.py"]))


def test_component_pair_cap_keeps_independent_declared_interactions(tmp_path):
    contents = {"pkg/__init__.py": "", "pkg/left/__init__.py": "", "pkg/right/__init__.py": ""}
    for number in range(3):
        contents[f"pkg/left/use{number}.py"] = f"from pkg.right.target{number} import Target{number}\ndef run{number}(): return Target{number}()\n"
        contents[f"pkg/right/target{number}.py"] = f"class Target{number}: pass\n"
    tools = verified_tools(tmp_path, contents)
    counts = []
    for maximum in (1, 2):
        _, inventory, _ = prepare_planning(tools.accessible_snapshot, AuditRequest(), limit=100,
            check=lambda: None, config=BoundaryConfig(max_component_probes_per_group_pair=maximum))
        counts.append(inventory["opportunity_diagnostics"]["generated_by_type"].get("component_boundary", 0))
    assert counts == [1, 2]


def test_acyclicity_probe_keeps_return_path_instead_of_unrelated_edge_tasks(tmp_path):
    tools = verified_tools(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/a.py": "from pkg.b import b\ndef a(): return b()\n",
        "pkg/b.py": "from pkg.c import c\ndef b(): return c()\n",
        "pkg/c.py": "def c(): return 1\n",
    })
    source = context(tools, [claim("pkg must remain acyclic.", subject="pkg",
        related_subjects=[], constraint="required")])
    _, inventory, _ = prepare(tools, source)
    record = next(iter(inventory["_document_claims"].values()))
    assert any(set(portion.scope_paths) == {"pkg/a.py", "pkg/b.py", "pkg/c.py"}
               for portion in record.portions)
    assert not any(set(portion.scope_paths) == {"pkg/a.py", "pkg/b.py"} for portion in record.portions)


def test_prior_task_candidate_id_does_not_reject_a_new_local_candidate(tmp_path):
    tools = verified_tools(tmp_path, {
        "app/__init__.py": "",
        "app/api.py": "from .store import Store\ndef use(): return Store()\n",
        "app/store.py": "class Store: pass\n",
    })
    source = context(tools, [claim("app.api must not depend on app.store.", subject="app.api",
        related_subjects=["app.store"])])
    state, _, _ = run(tools, source,
        lambda payload: assess_all(payload, "contradicted", status="finding_candidate", candidate=True),
        transform=lambda state: state.update(candidates=[candidate(id="local-candidate")]))
    assert state["investigation_results"][0].status == "finding_candidate"


def test_explicit_graph_owner_list_resolves_unique_directory_suffixes(tmp_path):
    tools = verified_tools(tmp_path, {
        "src/pkg/inbound/a.py": "from pkg.outbound.b import b\ndef a(): return b()\n",
        "src/pkg/outbound/b.py": "from pkg.inbound.a import a\ndef b(): return a()\n",
    })
    rule = claim("Dependencies among inbound and outbound MUST be acyclic.",
        subject="Feature dependencies", related_subjects=[], constraint="required")
    _, inventory, _ = prepare(tools, context(tools, [rule]))
    record = next(iter(inventory["_document_claims"].values()))
    assert record.status == "applicable"
    assert set(record.scope_paths) == {"src/pkg/inbound/a.py", "src/pkg/outbound/b.py"}


def test_graph_owner_list_does_not_guess_between_duplicate_directory_names(tmp_path):
    tools = verified_tools(tmp_path, {
        "one/pkg/feature/a.py": "def a(): pass\n",
        "two/pkg/feature/b.py": "def b(): pass\n",
    })
    rule = claim("Dependencies among feature MUST be acyclic.",
        subject="Feature dependencies", related_subjects=[], constraint="required")
    _, inventory, _ = prepare(tools, context(tools, [rule]))
    record = next(iter(inventory["_document_claims"].values()))
    assert record.status == "unmapped"
    assert not record.scope_paths
