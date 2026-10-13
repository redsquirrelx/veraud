"""Phase-one invariants, including real LangGraph state-channel behavior."""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from server.agents.project_analysis import (
    ArchitectureAnalysisInput,
    InvestigationBudget,
    ProjectAnalysisContext,
    ProjectAnalysisInput,
    ProjectAnalysisReport,
    ProjectAnalysisRunResult,
    ProjectAnalysisState,
)
from server.agents.project_analysis.schemas import (
    AnalysisClaim,
    BudgetUsage,
    ComponentRelationship,
    ExecutionIssue,
    FunctionalComponent,
    InvestigationCoverage,
    InvestigationObjective,
    InvestigationOutcome,
    InvestigationPlan,
    InvestigationResult,
    OpenQuestion,
    RetrievedEvidence,
)
from server.agents.project_analysis.state import merge_records_by_id
from server.services.repository_analysis import RepositoryAnalysisService


@pytest.fixture
def context(tmp_path):
    (tmp_path / "main.py").write_text("def main():\n    return 42\n", encoding="utf-8")
    snapshot = RepositoryAnalysisService().analyze_sync(tmp_path)
    return ProjectAnalysisContext(
        snapshot=snapshot,
        input=ProjectAnalysisInput(snapshot_hash=snapshot.repository.snapshot_hash),
    )


def objective(context, **overrides):
    fields = {
        "id": "investigation:startup",
        "project_id": context.snapshot.files[0].project_id,
        "objective": "Understand startup.",
        "seed_entity_ids": (context.snapshot.files[0].id,),
        "questions": ("What does main return?",),
        "report_sections": ("main_flows",),
        "selection_reason": "A main entrypoint was detected.",
        "priority_tier": "startup",
        "expected_deliverable": "A supported description of startup.",
        "completion_criteria": ("Inspect main or explain why it cannot be resolved.",),
    }
    return InvestigationObjective(**(fields | overrides))


def report(context, *, completed=False, **overrides):
    target = objective(context)
    coverage = InvestigationCoverage(
        selected_project_ids=(target.project_id,),
        planned_investigation_ids=(target.id,),
        completed_investigation_ids=(target.id,) if completed else (),
        pending_investigation_ids=() if completed else (target.id,),
    )
    return ProjectAnalysisReport(
        **(
            {
                "snapshot_hash": context.input.snapshot_hash,
                "investigation_plan": InvestigationPlan(objectives=(target,)),
                "investigation_outcomes": (
                    InvestigationOutcome(
                        id="finding:startup",
                        investigation_id=target.id,
                        status="completed",
                    ),
                )
                if completed
                else (),
                "investigation_coverage": coverage,
            }
            | overrides
        )
    )


def test_context_is_snapshot_bound_in_memory_and_does_not_mutate_repository(
    context, tmp_path
):
    original = list(tmp_path.iterdir())
    state = context.initial_state()
    assert state["snapshot_hash"] == context.snapshot.repository.snapshot_hash
    assert state["repository_overview"].symbol_count == 1
    assert state["completion_status"] is None
    assert state["budget_usage"] == BudgetUsage()
    assert state["findings"] == ()
    assert context.elapsed_seconds >= 0
    (tmp_path / "main.py").unlink()
    assert "return 42" in context.queries.get_source_excerpt("main.py").content
    assert len(original) == 1
    with pytest.raises(TypeError):
        context.reference_indexes["file"]["invented"] = context.snapshot.files[0]
    with pytest.raises(ValueError, match="hashes must match"):
        ProjectAnalysisContext(
            snapshot=context.snapshot,
            input=ProjectAnalysisInput(snapshot_hash="0" * 64),
        )


def test_contracts_are_immutable_strict_and_json_roundtrippable(context):
    draft = report(context)
    assert (
        ProjectAnalysisReport.model_validate(json.loads(draft.model_dump_json()))
        == draft
    )
    with pytest.raises(ValidationError):
        ProjectAnalysisInput(snapshot_hash="not-a-hash")
    with pytest.raises(ValidationError):
        ProjectAnalysisInput(
            snapshot_hash=context.input.snapshot_hash, root_path="unused"
        )
    with pytest.raises(ValidationError):
        draft.snapshot_hash = "0" * 64
    with pytest.raises(ValidationError, match="Duplicate"):
        InvestigationPlan(objectives=(objective(context), objective(context)))


def test_unresolved_claims_and_completed_investigations_are_compatible(context):
    claim = AnalysisClaim(
        id="claim:wiring",
        statement="Implementation selection is unresolved.",
        status="unresolved",
        limitations=("Dynamic dispatch was not resolved.",),
    )
    question = OpenQuestion(
        id="question:wiring",
        question="Which implementation is selected?",
        reason="Dynamic dispatch.",
        investigation_id=objective(context).id,
    )
    draft = report(context, completed=True, claims=(claim,), open_questions=(question,))
    result = ProjectAnalysisRunResult(
        completion_status="complete",
        report=draft,
        investigation_coverage=draft.investigation_coverage,
        unresolved_questions=(question,),
    )
    context.validate_result(result)
    context.validate_architecture_input(ArchitectureAnalysisInput.from_result(result))
    with pytest.raises(ValidationError, match="require evidence"):
        AnalysisClaim(id="claim:bad", statement="It uses MongoDB.", status="supported")
    with pytest.raises(ValidationError, match="explicit limitations"):
        AnalysisClaim(
            id="claim:bad", statement="It might use MongoDB.", status="hypothesis"
        )


def test_partial_and_failed_results_have_explicit_reasons(context):
    draft = report(context)
    partial = ProjectAnalysisRunResult(
        completion_status="partial",
        report=draft,
        investigation_coverage=draft.investigation_coverage,
    )
    context.validate_result(partial)
    issue = ExecutionIssue(
        id="issue:provider",
        stage="planning",
        category="provider_error",
        message="Provider unavailable.",
    )
    failed = ProjectAnalysisRunResult(
        completion_status="failed",
        investigation_coverage=InvestigationCoverage(),
        execution_issues=(issue,),
    )
    context.validate_result(failed)
    with pytest.raises(ValueError, match="Failed analysis"):
        ArchitectureAnalysisInput.from_result(failed)
    with pytest.raises(ValidationError):
        ProjectAnalysisRunResult(
            completion_status="failed", investigation_coverage=InvestigationCoverage()
        )
    with pytest.raises(ValidationError):
        ProjectAnalysisRunResult(
            completion_status="complete",
            report=draft,
            investigation_coverage=draft.investigation_coverage,
        )
    with pytest.raises(ValidationError):
        ProjectAnalysisRunResult(
            completion_status="failed",
            report=draft,
            investigation_coverage=draft.investigation_coverage,
            execution_issues=(issue,),
        )


def test_coverage_partitions_and_outcome_ledger_must_be_consistent(context):
    with pytest.raises(ValidationError, match="disjoint"):
        InvestigationCoverage(
            planned_investigation_ids=("target",),
            completed_investigation_ids=("target",),
            pending_investigation_ids=("target",),
        )
    with pytest.raises(ValidationError, match="exactly one"):
        InvestigationCoverage(planned_investigation_ids=("target",))
    with pytest.raises(ValidationError, match="outcomes"):
        report(context, completed=True, investigation_outcomes=())
    with pytest.raises(ValidationError, match="accepted investigation plan"):
        report(context, investigation_plan=InvestigationPlan())


def test_handoff_checks_identity_coverage_and_external_snapshot(context):
    draft = report(context)
    result = ProjectAnalysisRunResult(
        completion_status="partial",
        report=draft,
        investigation_coverage=draft.investigation_coverage,
    )
    handoff = ArchitectureAnalysisInput.from_result(result)
    context.validate_architecture_input(handoff)
    with pytest.raises(ValidationError, match="hashes must match"):
        ArchitectureAnalysisInput(
            **(handoff.model_dump() | {"snapshot_hash": "0" * 64})
        )
    with pytest.raises(ValidationError, match="coverage must match"):
        ArchitectureAnalysisInput(
            **(
                handoff.model_dump()
                | {"investigation_coverage": InvestigationCoverage()}
            )
        )
    other_report = report(context, snapshot_hash="0" * 64)
    other_handoff = ArchitectureAnalysisInput(
        snapshot_hash="0" * 64,
        project_analysis_report=other_report,
        investigation_coverage=other_report.investigation_coverage,
    )
    with pytest.raises(ValueError, match="hashes must match"):
        context.validate_architecture_input(other_handoff)


def test_plan_checks_seed_project_and_budget(context):
    context.validate_plan(InvestigationPlan(objectives=(objective(context),)))
    with pytest.raises(ValueError, match="Unknown snapshot entity"):
        context.validate_plan(
            InvestigationPlan(
                objectives=(objective(context, seed_entity_ids=("missing",)),)
            )
        )
    with pytest.raises(ValueError, match="Unknown project_id"):
        context.validate_plan(
            InvestigationPlan(objectives=(objective(context, project_id="missing"),))
        )
    limited = ProjectAnalysisContext(
        snapshot=context.snapshot,
        input=ProjectAnalysisInput(
            snapshot_hash=context.input.snapshot_hash,
            budget=InvestigationBudget(max_investigations=1),
        ),
    )
    with pytest.raises(ValueError, match="budget"):
        limited.validate_plan(
            InvestigationPlan(
                objectives=(objective(context), objective(context, id="second"))
            )
        )
    with pytest.raises(ValidationError, match="reserve"):
        InvestigationBudget(max_model_calls=3, reserved_report_model_calls=3)


def test_report_checks_typed_snapshot_and_local_references(context):
    file_id = context.snapshot.files[0].id
    snapshot_evidence = context.snapshot.evidence[0].id
    claim = AnalysisClaim(
        id="claim:return",
        statement="main returns 42.",
        status="supported",
        entity_ids=(file_id,),
        evidence_ids=(snapshot_evidence,),
    )
    component = FunctionalComponent(
        id="component:main",
        name="Main",
        project_id=context.snapshot.projects[0].id,
        responsibility=claim,
        file_ids=(file_id,),
    )
    draft = report(context, functional_components=(component,))
    context.validate_report(draft)
    wrong_kind = component.model_dump() | {"symbol_ids": (file_id,)}
    with pytest.raises(ValueError, match="Unknown symbol_ids"):
        context.validate_report(
            report(context, functional_components=(FunctionalComponent(**wrong_kind),))
        )
    relationship = ComponentRelationship(
        id="relationship:bad",
        source_component_id=component.id,
        target_component_id="missing",
        kind="calls",
        description=claim,
    )
    with pytest.raises(ValueError, match="target_component_id"):
        context.validate_report(
            report(
                context,
                functional_components=(component,),
                component_relationships=(relationship,),
            )
        )
    bad_claim = AnalysisClaim(**(claim.model_dump() | {"evidence_ids": ("missing",)}))
    with pytest.raises(ValueError, match="Unknown evidence_ids"):
        context.validate_report(report(context, claims=(bad_claim,)))


def test_retrieval_references_require_snapshot_content_and_valid_ranges(context):
    source = context.snapshot.files[0]
    retrieval = RetrievedEvidence(
        id="retrieval:main",
        snapshot_hash=context.input.snapshot_hash,
        file_id=source.id,
        content_hash=source.content_hash,
        tool_call_id="tool:1",
        kind="source",
        start_line=1,
        end_line=2,
    )
    claim = AnalysisClaim(
        id="claim:return",
        statement="main returns 42.",
        status="supported",
        evidence_ids=(retrieval.id,),
    )
    context.validate_report(
        report(context, retrieved_evidence=(retrieval,), claims=(claim,))
    )
    for override, message in [
        ({"content_hash": "0" * 64}, "content hash"),
        ({"end_line": 3}, "line range"),
        ({"snapshot_hash": "0" * 64}, "hashes must match"),
    ]:
        invalid = RetrievedEvidence(**(retrieval.model_dump() | override))
        with pytest.raises(ValueError, match=message):
            context.validate_report(report(context, retrieved_evidence=(invalid,)))
    with pytest.raises(ValidationError, match="line range"):
        RetrievedEvidence(
            **(retrieval.model_dump() | {"start_line": None, "end_line": None})
        )


def test_accumulated_records_are_idempotent_and_conflicts_fail():
    question = OpenQuestion(
        id="question:1", question="Which adapter?", reason="Unresolved wiring."
    )
    first = (question,)
    assert merge_records_by_id(first, first) == first
    changed = OpenQuestion(
        id=question.id, question="Which database?", reason=question.reason
    )
    with pytest.raises(ValueError, match="Conflicting accumulated"):
        merge_records_by_id(first, (changed,))
    assert first == (question,)


def test_cross_project_seeds_and_snapshot_identifier_collisions_are_rejected(tmp_path):
    (tmp_path / "package.json").write_text('{"name":"root"}', encoding="utf-8")
    child = tmp_path / "child"
    child.mkdir()
    (child / "package.json").write_text('{"name":"child"}', encoding="utf-8")
    snapshot = RepositoryAnalysisService().analyze_sync(tmp_path)
    context = ProjectAnalysisContext(
        snapshot=snapshot,
        input=ProjectAnalysisInput(snapshot_hash=snapshot.repository.snapshot_hash),
    )
    root_project = next(project for project in snapshot.projects if project.path == ".")
    child_file = next(
        source for source in snapshot.files if source.path.startswith("child/")
    )
    with pytest.raises(ValueError, match="selected project"):
        context.validate_plan(
            InvestigationPlan(
                objectives=(
                    objective(
                        context,
                        project_id=root_project.id,
                        seed_entity_ids=(child_file.id,),
                    ),
                )
            )
        )
    conflicting_claim = AnalysisClaim(
        id=child_file.id,
        statement="Unknown purpose.",
        status="unresolved",
        limitations=("Not investigated.",),
    )
    with pytest.raises(ValueError, match="collides with snapshot"):
        context.validate_report(report(context, claims=(conflicting_claim,)))


def test_followup_provenance_requires_an_accepted_finding(context):
    followup = objective(
        context, id="investigation:followup", origin_finding_ids=("finding:startup",)
    )
    plan = InvestigationPlan(objectives=(objective(context), followup))
    with pytest.raises(ValueError, match="origin_finding_ids"):
        context.validate_plan(plan)
    context.validate_plan(plan, known_finding_ids=("finding:startup",))
    coverage = InvestigationCoverage(
        planned_investigation_ids=(objective(context).id, followup.id),
        completed_investigation_ids=(objective(context).id,),
        pending_investigation_ids=(followup.id,),
    )
    draft = report(
        context,
        completed=True,
        investigation_plan=plan,
        investigation_coverage=coverage,
    )
    context.validate_report(draft)


def test_actual_langgraph_reducers_preserve_records_replace_counters_and_scope_messages(
    context,
):
    finding = InvestigationResult(
        id="finding:1", investigation_id="investigation:startup", status="completed"
    )
    graph = StateGraph(ProjectAnalysisState, context_schema=ProjectAnalysisContext)

    def first(state, runtime):
        assert runtime.context is context
        return {
            "findings": (finding,),
            "budget_usage": BudgetUsage(model_calls=1),
            "investigation_messages": [
                HumanMessage(id="target:1", content="First target")
            ],
        }

    def second(state):
        assert state["budget_usage"].model_calls == 1
        return {
            "findings": (finding,),
            "budget_usage": BudgetUsage(model_calls=2),
            "investigation_messages": [
                RemoveMessage(id="target:1"),
                AIMessage(id="target:2", content="Next target"),
            ],
        }

    graph.add_node("first", first)
    graph.add_node("second", second)
    graph.add_edge(START, "first")
    graph.add_edge("first", "second")
    graph.add_edge("second", END)
    initial = context.initial_state()
    final = graph.compile().invoke(initial, context=context)
    assert final["findings"] == (finding,)
    assert final["budget_usage"].model_calls == 2
    assert [message.id for message in final["investigation_messages"]] == ["target:2"]
    assert initial["findings"] == ()
    assert initial["investigation_messages"] == []
