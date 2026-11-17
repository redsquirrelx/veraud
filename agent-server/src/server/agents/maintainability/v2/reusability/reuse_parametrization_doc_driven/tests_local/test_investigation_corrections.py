"""Regression tests for the investigation-loop corrections (auditable behavior)."""

import asyncio
from types import SimpleNamespace

import pytest
from pydantic_core import PydanticCustomError

from server.agents.maintainability.v2.reusability.reuse_parametrization_doc_driven import (
    ReuseParametrizationConfig,
    ReuseParametrizationDocDrivenAgent,
    ReuseParametrizationDocDrivenRequest,
    ReuseParametrizationDocDrivenResult,
)
from server.agents.maintainability.v2.reusability.reuse_parametrization_doc_driven.schemas import (
    ParametrizationCandidate,
    ParametrizationClaimAssessment,
    ParametrizationEvidenceAssessment,
    ParametrizationInvestigationCandidate,
    ParametrizationInvestigationResult,
    ParametrizationInvestigationTurn,
    ParametrizationPlan,
    ParametrizationToolQuery,
)
from server.contracts.audit import Hypothesis
from server.runtimes.repository.context import RepositoryContext
from server.runtimes.repository.schemas import ExecutionBudget, RepositoryInput
from server.runtimes.repository.tools import RepositoryToolset
from server.services.repository_analysis import RepositoryAnalysisService


class UnexpectedModel:
    def bind_tools(self, _tools):
        return self

    async def ainvoke(self, *_args, **_kwargs):
        raise AssertionError("no model call expected in this test")


def toolset(root):
    root.mkdir(exist_ok=True)
    (root / "handler.py").write_text(
        "class RouteHandlerConfig:\n"
        "    pass\n\n"
        "def create_api_handler(schema, require_auth=None, permission=None, success_status=200):\n"
        "    return schema, require_auth, permission, success_status\n",
        encoding="utf-8",
    )
    (root / "alternatives.py").write_text(
        "class ZodSchema:\n"
        "    pass\n",
        encoding="utf-8",
    )
    snapshot = RepositoryAnalysisService().analyze_sync(root)
    budget = ExecutionBudget(
        max_model_calls=4,
        max_tool_calls=4,
        max_total_tokens=40_000,
        max_tokens_per_objective=40_000,
        max_input_tokens_per_call=20_000,
    )
    return RepositoryToolset(RepositoryContext(snapshot, RepositoryInput(
        snapshot_hash=snapshot.repository.snapshot_hash,
        budget=budget,
    )), workspace_root=root.parent)


def plan_execution(tmp_path, *, tools=None):
    request = ReuseParametrizationDocDrivenRequest()
    kwargs = {} if tools is None else {"tools": tools}
    execution = ReuseParametrizationDocDrivenAgent.execution_type(
        UnexpectedModel(), ReuseParametrizationConfig(max_model_calls=4, **kwargs), toolset(tmp_path), request)
    candidate = ParametrizationCandidate(
        id="candidate-1",
        priority="medium",
        scope=["handler.py", "alternatives.py"],
        primary_component="handler.py",
        variation_mechanism="schema validation",
        alternatives=["validation function", "Zod schema"],
        variation_basis="explicit",
        initial_locations=["handler.py", "alternatives.py"],
        observed_indicators=["Handler accepts a schema parameter."],
        question="Can handler.py use schema validation to choose the alternative?",
        evidence_needed=["Inspect handler.py for schema selection.", "Inspect one selection site."],
        document_claim_ids=[],
    )
    plan = ParametrizationPlan(
        objectives=[request.objective], components=["handler.py", "alternatives.py"],
        hypotheses=[Hypothesis(id=candidate.id, question=candidate.question,
            criterion_id="parametrized-reuse", priority="medium",
            evidence_needed=candidate.evidence_needed)],
        candidates=[candidate], limitations=[], document_claims={})
    return request, execution, execution.initial_state() | {"plan": plan}


def task_stub(*, evidence_needed, document_claim_ids=(), primary_component="handler.py"):
    return SimpleNamespace(
        id="candidate-1",
        evidence_needed=list(evidence_needed),
        document_claim_ids=list(document_claim_ids),
        primary_component=primary_component,
        initial_locations=["handler.py"],
        scope=["handler.py"],
    )


def source_ref(path, record_id="e1", start_line=1, end_line=5):
    return SimpleNamespace(id=record_id, kind="source", path=path, start_line=start_line, end_line=end_line)


def test_coverage_recovery_does_not_depend_on_path_tool_membership(tmp_path):
    _request, execution, state = plan_execution(tmp_path)
    execution.stop = "model_or_schema_error"
    state = {**state, "initial_evidence_loaded": True, "query_cache": {}, "active_query_keys": [],
        "coverage_recovery_done": False}

    result = asyncio.run(execution.investigate(state))

    queries = result["pending_queries"]
    assert any(query.tool == "get_source_excerpt" and query.arguments["path"] == "handler.py"
        for query in queries)


def test_coverage_recovery_disabled_when_get_source_excerpt_is_disabled(tmp_path):
    _request, execution, state = plan_execution(
        tmp_path, tools=["list_files", "find_symbols", "list_relationships", "search_repository_text", "get_evidence"])
    execution.stop = "model_or_schema_error"
    plan = state["plan"]
    data = execution.tools.context.input
    result = ReuseParametrizationDocDrivenResult(
        repository_id=data.repository.name if hasattr(data, "repository") else "repo",
        commit=data.repository.commit if hasattr(data, "repository") else None,
        snapshot_hash=data.snapshot_hash,
        objective="objective",
        plan=plan,
        findings=[],
        hypotheses=plan.hypotheses,
        investigation_results=[],
        missing_information=[],
        limitations=[],
        termination_reason="investigating",
        model_calls=0,
        tool_calls=0,
        iterations=0,
        accounted_tokens=0,
        estimated_tokens=0,
        planning_diagnostics={},
    )
    state = {**state, "result": result, "initial_evidence_loaded": True, "query_cache": {},
        "active_query_keys": [], "coverage_recovery_done": False, "current_investigation": 0,
        "hypotheses": plan.hypotheses, "limitations": [], "limitations_loaded": True,
        "iterations": 0, "task_limitations": []}

    assert execution._coverage_recovery_queries(state, delivered=[]) == []
    received = asyncio.run(execution.investigate(state))
    assert received.get("pending_queries", []) == []


def test_resolved_requirement_needs_source_evidence(tmp_path):
    _request, execution, _state = plan_execution(tmp_path)
    task = task_stub(evidence_needed=["Inspect handler.py for schema selection."])
    result = ParametrizationInvestigationResult(
        investigation_id="candidate-1",
        status="no_finding",
        summary="s",
        justification="j",
        evidence_assessments=[
            ParametrizationEvidenceAssessment(requirement_index=0, status="resolved",
                rationale="The delivered source resolves this supplied capability obligation directly.",
                evidence_ids=[], scope_paths=[]),
        ],
    )

    errors = []
    execution._validate_evidence_requirements(result, task, references={}, errors=errors)

    assert any(item["code"] == "evidence_requirement_source_required" for item in errors)


def test_resolved_requirement_with_source_and_scope_passes(tmp_path):
    _request, execution, _state = plan_execution(tmp_path)
    task = task_stub(evidence_needed=["Inspect handler.py for schema selection."])
    reference = source_ref("handler.py", "e1")
    result = ParametrizationInvestigationResult(
        investigation_id="candidate-1",
        status="no_finding",
        summary="s",
        justification="j",
        evidence_assessments=[
            ParametrizationEvidenceAssessment(requirement_index=0, status="resolved",
                rationale="The delivered source resolves this supplied capability obligation directly.",
                evidence_ids=["e1"], scope_paths=["handler.py"]),
        ],
    )

    errors = []
    execution._validate_evidence_requirements(result, task, references={"e1": reference}, errors=errors)

    assert errors == []


def test_not_applicable_cannot_evade_code_dependent_requirement(tmp_path):
    _request, execution, _state = plan_execution(tmp_path)
    task = task_stub(evidence_needed=["Inspect handler.py for schema selection."])
    result = ParametrizationInvestigationResult(
        investigation_id="candidate-1",
        status="no_finding",
        summary="s",
        justification="j",
        evidence_assessments=[
            ParametrizationEvidenceAssessment(requirement_index=0, status="not_applicable",
                rationale="This obligation does not govern the inspected component at all, in any useful way.",
                evidence_ids=[], scope_paths=[], exclusion_basis="not_code_dependent"),
        ],
    )

    errors = []
    execution._validate_evidence_requirements(result, task, references={}, errors=errors)

    codes = [item["code"] for item in errors]
    assert "evidence_requirement_not_applicable_unjustified" in codes
    assert "evidence_requirement_source_required" not in codes


def test_not_applicable_requires_concrete_rationale_and_basis(tmp_path):
    _request, execution, _state = plan_execution(tmp_path)
    task = task_stub(evidence_needed=["Context notes only."])
    result = ParametrizationInvestigationResult(
        investigation_id="candidate-1",
        status="no_finding",
        summary="s",
        justification="j",
        evidence_assessments=[
            ParametrizationEvidenceAssessment(requirement_index=0, status="not_applicable",
                rationale="not relevant", evidence_ids=[], scope_paths=[], exclusion_basis=None),
        ],
    )

    errors = []
    execution._validate_evidence_requirements(result, task, references={}, errors=errors)

    codes = [item["code"] for item in errors]
    assert "evidence_requirement_exclusion_basis_required" in codes
    assert "evidence_requirement_explanation_required" in codes


def test_code_verified_exclusion_still_needs_source(tmp_path):
    _request, execution, _state = plan_execution(tmp_path)
    task = task_stub(evidence_needed=["Context notes only."])
    result = ParametrizationInvestigationResult(
        investigation_id="candidate-1",
        status="no_finding",
        summary="s",
        justification="j",
        evidence_assessments=[
            ParametrizationEvidenceAssessment(requirement_index=0, status="not_applicable",
                rationale="Excluded because inspected source shows the adapter ignores caller configuration entirely.",
                evidence_ids=[], scope_paths=[], exclusion_basis="code_verified"),
        ],
    )

    errors = []
    execution._validate_evidence_requirements(result, task, references={}, errors=errors)

    assert any(item["code"] == "evidence_requirement_source_required" for item in errors)


def claim_conclusion(**overrides):
    base = {"investigation_id": "candidate-1",
        "status": "finding_candidate",
        "summary": "Found a substitutability defect.",
        "justification": "Delivered source violates the documented guarantee.",
        "components": ["handler.py"],
        "evidence_ids": [],
        "selection_phase": "unknown",
        "selection_sites": [],
        "consumer_impact": "not_verified",
        "claim_assessments": []}
    base.update(overrides)
    base["candidates"] = [ParametrizationInvestigationCandidate(
        id="cand-1", title="Substitutability defect",
        description="The implementation violates the documented substitutability guarantee.",
        criterion_id="parametrized-reuse", kind="design_observation",
        components=["handler.py"], evidence_ids=["absent-evidence"],
        justification="Inspected source shows the implementation violates the documented guarantee.",
        modularity_impact="Consumers cannot substitute the implementation without modification.",
        severity="high", confidence=0.8, recommendation="Enforce the documented contract.",
        variation_mechanism="schema validation", selected_alternatives=["validation function"],
        document_claim_ids=["claim-0"])]
    return ParametrizationInvestigationResult(**base)


def test_finding_scope_satisfied_by_primary_component_alone(tmp_path):
    _request, execution, _state = plan_execution(tmp_path)
    task = task_stub(evidence_needed=[], document_claim_ids=["claim-0"])
    result = ParametrizationInvestigationResult(
        investigation_id="candidate-1",
        status="finding_candidate",
        summary="s",
        justification="j",
        components=["handler.py"],
        claim_assessments=[ParametrizationClaimAssessment(claim_id="claim-0", status="supported",
            rationale="Source shows the documented mechanism end to end.",
            code_evidence_ids=["e1"], scope_paths=["handler.py"])],
        candidates=[ParametrizationInvestigationCandidate(
            id="cand-1", title="Contract violation",
            description="The implementation violates the documented substitutability guarantee.",
            criterion_id="parametrized-reuse", kind="design_observation",
            components=["handler.py"], evidence_ids=["e1"],
            justification="Inspected source shows the implementation violates the documented guarantee and blocks consumers from substituting the alternative.",
            modularity_impact="Consumers cannot substitute the implementation without modification.",
            severity="high", confidence=0.8, recommendation="Enforce the documented contract.",
            variation_mechanism="schema validation", selected_alternatives=["validation function"],
            document_claim_ids=["claim-0"])],
    )
    references = {"e1": source_ref("handler.py", "e1")}

    errors = []
    execution._validate_finding_scope(result, task, references, errors)

    assert errors == []


def test_finding_rejects_uninspected_consumer(tmp_path):
    _request, execution, _state = plan_execution(tmp_path)
    task = task_stub(evidence_needed=[])
    result = ParametrizationInvestigationResult(
        investigation_id="candidate-1",
        status="finding_candidate",
        summary="s",
        justification="j",
        components=["alternatives.py"],
        candidates=[ParametrizationInvestigationCandidate(
            id="cand-1", title="Contract violation",
            description="The implementation violates the documented substitutability guarantee.",
            criterion_id="parametrized-reuse", kind="design_observation",
            components=["alternatives.py"], evidence_ids=["e2"],
            justification="Inspected source shows the implementation violates the documented guarantee.",
            modularity_impact="Consumers cannot substitute the implementation without modification.",
            severity="high", confidence=0.8, recommendation="Enforce the documented contract.",
            variation_mechanism="schema validation", selected_alternatives=["validation function"],
            consumers=["alternatives.py"], document_claim_ids=[])],
    )
    references = {}  # Nothing inspected.

    errors = []
    execution._validate_finding_scope(result, task, references, errors)

    codes = [item["code"] for item in errors]
    assert "finding_requires_variation_scope" in codes
    assert "uninspected_variation_scope" in codes


def test_validate_turn_accumulates_all_detectable_errors(tmp_path):
    _request, execution, state = plan_execution(tmp_path)
    turn = ParametrizationInvestigationTurn(
        action="close",
        conclusion=claim_conclusion(),
    )

    with pytest.raises(PydanticCustomError):
        execution._validate_turn(turn, state)

    errors = execution._last_validation_errors
    codes = {item["code"] for item in errors}
    assert {
        "evidence_requirements_unresolved",
        "selection_phase_unresolved",
        "consumer_impact_unresolved",
        "candidate_document_claim_unassessed",
        "coverage_incomplete",
        "conclusion_requires_inspected_source_and_components",
        "candidate_evidence_not_in_conclusion",
        "finding_requires_variation_scope",
    } <= codes
    assert any(item.get("index") is not None for item in errors)
    assert all(item["field"] for item in errors)


def test_investigation_context_recovers_earlier_source_via_get_evidence(tmp_path):
    _request, execution, state = plan_execution(tmp_path)
    queries = [
        ParametrizationToolQuery(tool="get_source_excerpt",
            arguments={"path": "handler.py", "start_line": 1, "end_line": 5},
            reason="Inspect the primary capability."),
        ParametrizationToolQuery(tool="find_symbols",
            arguments={"file_path": "handler.py", "limit": 10},
            reason="Locate the declarations relevant to the capability."),
        ParametrizationToolQuery(tool="get_source_excerpt",
            arguments={"path": "alternatives.py", "start_line": 1, "end_line": 5},
            reason="Inspect one alternative."),
    ]

    result = asyncio.run(execution.execute_investigation_tools(
        {**state, "pending_queries": queries}))
    first_source_id = result["query_cache"][result["active_query_keys"][0]]["evidence"][0]["id"]

    merged = {**state, **result, "pending_queries": []}
    context = execution._investigation_context(merged)

    recoverable_ids = {item["id"] for item in context["recoverable_evidence"]}
    assert first_source_id in recoverable_ids
    assert any(item["arguments"]["path"] == "handler.py" for item in context["recoverable_evidence"])
    assert len(context["tool_results"]) == 2
    assert len(context["query_history"]) == 3

    tool, arguments = execution._resolve_evidence_query("get_evidence", {"evidence_id": first_source_id})
    assert tool == "get_source_excerpt"
    assert arguments["path"] == "handler.py"
