"""Host-side synthesis and finalize: consolidated, provisional, honest findings."""

from server.agents.maintainability.v2.reusability.coordinator.registry import (
    registered_investigators,
)
from server.agents.maintainability.v2.reusability.reuse_parametrization_doc_driven import (
    ReuseParametrizationConfig,
    ReuseParametrizationDocDrivenAgent,
    ReuseParametrizationDocDrivenRequest,
    ReuseParametrizationDocDrivenResult,
)
from server.agents.maintainability.v2.reusability.reuse_parametrization_doc_driven.schemas import (
    ParametrizationCandidate,
    ParametrizationInvestigationCandidate,
    ParametrizationInvestigationResult,
    ParametrizationPlan,
)
from server.agents.maintainability.v2.reusability.reuse_parametrization_doc_driven.synthesis import (
    consolidate_candidates,
)
from server.contracts.audit import Hypothesis
from server.runtimes.repository.context import RepositoryContext
from server.runtimes.repository.schemas import ExecutionBudget, RepositoryInput
from server.runtimes.repository.tools import RepositoryToolset
from server.services.repository_analysis import RepositoryAnalysisService


class TestModel:
    def bind_tools(self, _tools):
        return self

    async def ainvoke(self, *_args, **_kwargs):
        raise AssertionError("no model call expected in this test")


class TestToolset:
    @staticmethod
    def build(root):
        root.mkdir(exist_ok=True)
        (root / "pricing.py").write_text(
            "class FlatFarePolicy:\n"
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


def investigation_result(candidate_id, *, components=("pricing.py",), evidence_ids=("e1", "e2"),
        investigation_id="candidate-1", document_claim_ids=()):
    return ParametrizationInvestigationResult(
        investigation_id=investigation_id,
        status="finding_candidate",
        summary="Found a substitutability defect.",
        justification="Inspected source violates the documented substitutability guarantee.",
        components=list(components),
        evidence_ids=list(evidence_ids),
        selection_phase="assembly",
        selection_sites=list(components[:1]),
        consumer_impact="required",
        candidates=[ParametrizationInvestigationCandidate(
            id=candidate_id,
            title="Substitutability defect",
            description="The implementation violates the documented substitutability guarantee.",
            criterion_id="parametrized-reuse",
            kind="design_observation",
            components=list(components),
            evidence_ids=list(evidence_ids),
            justification="Inspected source shows the implementation violates the documented guarantee.",
            modularity_impact="Consumers cannot substitute the implementation without modification.",
            severity="high",
            confidence=0.7,
            recommendation="Enforce the documented contract.",
            variation_mechanism="fare strategy",
            selected_alternatives=["FlatFarePolicy"],
            document_claim_ids=list(document_claim_ids))],
    )


def result_obj(plan, repository_id, commit, snapshot_hash):
    return ReuseParametrizationDocDrivenResult(
        repository_id=repository_id,
        commit=commit,
        snapshot_hash=snapshot_hash,
        objective="objective",
        plan=plan,
        findings=[],
        hypotheses=[],
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


def plan_for(root):
    task = ParametrizationCandidate(
        id="candidate-1",
        priority="high",
        scope=["pricing.py"],
        primary_component="pricing.py",
        variation_mechanism="fare strategy",
        alternatives=["FlatFarePolicy"],
        variation_basis="explicit",
        initial_locations=["pricing.py"],
        observed_indicators=["Indexed implementation."],
        question="Can callers of pricing.py select the strategy?",
        evidence_needed=["Inspect pricing.py for the strategy's substitution guarantee."],
        document_claim_ids=[],
    )
    return ParametrizationPlan(
        objectives=["objective"], components=["pricing.py"],
        hypotheses=[Hypothesis(id=task.id, question=task.question,
            criterion_id="parametrized-reuse", priority="medium", evidence_needed=[])],
        candidates=[task], limitations=[], document_claims={})


def test_consolidation_merges_identical_candidates_across_investigations():
    first = investigation_result("local-a", evidence_ids=("e1", "e2"), investigation_id="candidate-1",
        document_claim_ids=["claim-0"])
    second = investigation_result("local-b", evidence_ids=("e2", "e3"), investigation_id="candidate-1",
        document_claim_ids=["claim-0"])

    candidates, origins = consolidate_candidates([first, second])

    assert len(candidates) == 1
    assert candidates[0].evidence_ids == ["e1", "e2", "e3"]
    merged_origins = origins[candidates[0].id]
    assert {item["investigation_id"] for item in merged_origins} == {"candidate-1"}
    assert candidates[0].id not in {"local-a", "local-b"} or candidates[0].id == "local-a"


def test_consolidation_keeps_distinct_candidates_separate():
    first = investigation_result("only-a", components=("pricing.py",))
    distinct = investigation_result("only-b", components=("other.py",))

    candidates, _origins = consolidate_candidates([first, distinct])

    assert len(candidates) == 2
    assert {item.id for item in candidates} == {"only-a", "only-b"}


def test_synthesis_and_finalize_lift_provisional_findings(tmp_path):
    toolset = TestToolset.build(tmp_path)
    snapshot = toolset.accessible_snapshot
    request = ReuseParametrizationDocDrivenRequest()
    execution = ReuseParametrizationDocDrivenAgent.execution_type(
        TestModel(),
        ReuseParametrizationConfig(max_model_calls=4),
        toolset,
        request)
    plan = plan_for(tmp_path)
    repository_id = snapshot.repository.name
    result = result_obj(plan, repository_id, snapshot.repository.commit, snapshot.repository.snapshot_hash)
    investigation = investigation_result("local-a", evidence_ids=("e1",), investigation_id="candidate-1",
        document_claim_ids=["claim-0"])
    state = {"result": result, "investigation_results": [investigation], "limitations": [],
        "termination_reason": "investigations_completed", "plan": plan,
        "hypotheses": [], "iterations": 0}

    after_synthesis = execution.synthesis(state)
    finalized = execution.finalize({**state, **after_synthesis})

    findings = finalized["result"].findings
    assert len(findings) == 1
    finding = findings[0]
    assert finding.criterion.id == "parametrized-reuse"
    assert finding.validation_status == "insufficient_evidence"
    assert "No critical review performed" in finding.review_rationale
    assert finding.document_claim_ids == ["claim-0"]
    assert after_synthesis["candidates"][0].id == finding.id


def test_finalize_maps_source_ledger_to_finding_evidence(tmp_path):
    toolset = TestToolset.build(tmp_path)
    snapshot = toolset.accessible_snapshot
    request = ReuseParametrizationDocDrivenRequest()
    execution = ReuseParametrizationDocDrivenAgent.execution_type(
        TestModel(),
        ReuseParametrizationConfig(max_model_calls=4),
        toolset,
        request)
    plan = plan_for(tmp_path)
    result = result_obj(plan, snapshot.repository.name, snapshot.repository.commit,
        snapshot.repository.snapshot_hash)
    # Deliver real source evidence through the toolset so the host ledger resolves it.
    toolset.execute("get_source_excerpt", {"path": "pricing.py", "start_line": 1, "end_line": 2},
        tool_call_id="lift-test-1")
    ledger_ids = [record.id for record in execution.references()]
    evidence_id = next(iter(ledger_ids))
    investigation = investigation_result("local-a", evidence_ids=(evidence_id,), investigation_id="candidate-1")
    state = {"result": result, "investigation_results": [investigation], "limitations": [],
        "termination_reason": "investigations_completed", "plan": plan,
        "hypotheses": [], "iterations": 0}

    after_synthesis = execution.synthesis(state)
    finalized = execution.finalize({**state, **after_synthesis})

    findings = finalized["result"].findings
    assert len(findings) == 1
    assert {reference.id for reference in findings[0].evidence} == {evidence_id}


def test_registered_result_schema_accepts_lifted_findings():
    spec = registered_investigators()["reuse_parametrization_doc_driven"]
    assert spec.result_class is ReuseParametrizationDocDrivenResult
