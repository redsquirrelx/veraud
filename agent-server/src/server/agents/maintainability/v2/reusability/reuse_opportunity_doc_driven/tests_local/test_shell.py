import asyncio
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from pydantic_core import PydanticCustomError

from config.agents import InvestigationConfig
from server.agents.architecture_context.schemas import (
    ArchitectureContextResult,
    KnowledgeClaim,
    KnowledgeEvidence,
)
from server.agents.maintainability.v2.reusability.coordinator.registry import (
    registered_investigators,
)
from server.agents.maintainability.v2.reusability.reuse_opportunity_doc_driven import (
    ReuseOpportunityDocDrivenAgent,
)
from server.agents.maintainability.v2.reusability.reuse_opportunity_doc_driven.execution import (
    ReuseOpportunityExecution,
)
from server.agents.maintainability.v2.reusability.reuse_opportunity_doc_driven.schemas import (
    ReuseCorrelationResponse,
    ReuseInvestigationProposal,
    ReuseOpportunityDocDrivenRequest,
    ReusePlanningResponse,
)
from server.runtimes.investigation.agent import InvestigationExecution
from server.runtimes.investigation.structured import (
    correction_feedback,
    safe_diagnostic,
)
from server.runtimes.repository.context import RepositoryContext
from server.runtimes.repository.schemas import ExecutionBudget, RepositoryInput
from server.runtimes.repository.tools import RepositoryToolset
from server.services.repository_analysis import RepositoryAnalysisService


class ScriptedModel:
    def __init__(self, response):
        self.responses = iter(response if isinstance(response, list) else [response])
        self.history = []

    def bind_tools(self, _tools):
        return self

    async def ainvoke(self, messages, **_kwargs):
        self.history.append(messages)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return AIMessage(content=json.dumps(response(messages) if callable(response) else response))


@pytest.mark.parametrize("native", [False, True])
def test_raw_response_is_printed_before_validation_without_polluting_stdout(monkeypatch, capsys, native):
    raw = AIMessage(content="invalid JSON visible before validation")
    response = {"raw": raw, "parsed": None, "parsing_error": ValueError()} if native else raw

    async def provider_request(*args, **kwargs):
        return response

    monkeypatch.setattr(InvestigationExecution, "provider_request", provider_request)
    execution = object.__new__(ReuseOpportunityExecution)
    returned = asyncio.run(execution.provider_request(None, [], "", "plan_investigation", None, 0))

    captured = capsys.readouterr()
    assert returned is response
    assert captured.out == ""
    assert "[DEBUG_LLM_RAW plan_investigation] invalid JSON visible before validation" in captured.err


def toolset(root):
    snapshot = RepositoryAnalysisService().analyze_sync(root)
    budget = ExecutionBudget(max_model_calls=12, max_tool_calls=10,
        max_total_tokens=100_000, max_tokens_per_objective=100_000,
        max_input_tokens_per_call=50_000)
    return RepositoryToolset(RepositoryContext(snapshot, RepositoryInput(
        snapshot_hash=snapshot.repository.snapshot_hash, budget=budget)), workspace_root=root.parent)


def test_plan_schema_requires_documentary_claims_and_two_sided_resolution_criteria():
    investigation = ReuseInvestigationProposal(
        capability="Audit event listing",
        question="Does the documented shared audit capability have one compatible provider?",
        document_claim_ids=["claim-0"],
        objectives=["Locate providers and consumers"],
        reuse_criteria=["Matching semantics and contract"],
        independent_implementation_criteria=["Different domain semantics"],
        rationale="The supplied claim names a shared audit capability.",
        documented_reuse_expectation="Audit listing is a shared capability.",
        implementation_uncertainty="Whether consumers duplicate equivalent listing behavior.",
    )
    response = ReusePlanningResponse(investigations=[investigation])
    assert response.investigations[0].document_claim_ids == ["claim-0"]


def planning_execution():
    execution = object.__new__(ReuseOpportunityExecution)
    execution.tools = SimpleNamespace(accessible_snapshot=SimpleNamespace(
        repository=SimpleNamespace(snapshot_hash="a" * 64),
        files=[SimpleNamespace(path="lib/services/audit.py"), SimpleNamespace(path="src/modules/audit.py")],
    ))
    execution._current_claim_ids = {"claim-0"}
    execution._planning_context = {"phase": "formulate"}
    return execution


def close_from_context(messages, status="no_reuse_opportunity"):
    context = json.loads(messages[1].content)
    investigate = context["investigation"]
    sources = [item for item in context["evidence"] if item["kind"] == "source"]
    paths = sorted({item["path"] for item in sources})
    return {
        "action": "close",
        "queries": [],
        "conclusion": {
            "investigation_id": investigate["id"],
            "status": status,
            "summary": "The inspected source does not establish a reuse opportunity.",
            "justification": "The source evidence was sufficient to resolve the investigation.",
            "components": paths,
            "symbol_ids": sorted({symbol for item in sources for symbol in item["symbol_ids"]}),
            "relationship_ids": [],
            "evidence_ids": [item["id"] for item in context["evidence"]],
            "candidates": [],
            "limitations": [],
            "claim_assessments": [],
            "comparisons": [comparison_from_context(context, "justified_independence")]
                if len(context.get("symbols", [])) >= 2 else [],
        },
    }


def proposal_response(targets, claim_ids=None):
    return ReusePlanningResponse(investigations=[ReuseInvestigationProposal(
        capability="Shared audit listing",
        question="Do providers and consumers implement compatible audit-listing semantics?",
        document_claim_ids=claim_ids or ["claim-0"],
        initial_targets=targets,
        objectives=["Locate providers, consumers and alternative implementations."],
        reuse_criteria=["Matching semantics and compatible contracts."],
        independent_implementation_criteria=["Documented domain separation."],
        rationale="A supplied claim describes a shared capability.",
        documented_reuse_expectation="Audit listing is a shared capability.",
        implementation_uncertainty="Whether consumers duplicate equivalent listing behavior.",
    )])


@pytest.mark.parametrize(("targets", "expected"), [
    (["lib/services/", "src/modules/"], ["lib/services", "src/modules"]),
    (["lib/services/audit.py"], ["lib/services/audit.py"]),
    (["lib\\services\\", "./lib/services/"], ["lib/services"]),
    ([], []),
])
def test_targets_are_optional_indexed_file_or_directory_hints(targets, expected):
    execution = planning_execution()
    investigations = execution._validate_plan(proposal_response(targets), {"claim-0"})
    assert investigations[0].initial_targets == expected


@pytest.mark.parametrize("target", ["lib/service/", "src/unknown", "../lib/services", "/lib/services", "C:\\repo", "."])
def test_nonexistent_or_unsafe_hints_have_actionable_safe_feedback(target):
    execution = planning_execution()
    with pytest.raises(PydanticCustomError) as caught:
        execution._validate_plan(proposal_response([target]), {"claim-0"})
    diagnostic = safe_diagnostic(caught.value, ReusePlanningResponse)
    assert "planning_unknown_target" in diagnostic
    feedback = correction_feedback(caught.value, ReusePlanningResponse)
    assert "directories containing indexed files" in feedback
    assert "use []" in feedback
    assert "response unavailable" not in diagnostic


def test_claim_references_must_belong_to_current_portion():
    execution = planning_execution()
    with pytest.raises(PydanticCustomError) as caught:
        execution._validate_plan(proposal_response([], ["claim-99"]), {"claim-0"})
    assert "planning_unknown_document_claim" in safe_diagnostic(caught.value, ReusePlanningResponse)
    correction = execution.structured_correction_context("plan_investigation", {})
    assert correction["allowed_document_claim_ids"] == ["claim-0"]


def test_shell_is_registered_with_no_completion_reasons():
    spec = registered_investigators()["reuse_opportunity_doc_driven"]

    assert spec.agent_class is ReuseOpportunityDocDrivenAgent
    assert spec.completed_reasons == ()


@pytest.mark.parametrize("invalid_first", [False, True])
def test_runner_agent_executes_planning_node_only(tmp_path, invalid_first):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "service.py").write_text("def list_audit_logs():\n    return []\n", encoding="utf-8")
    document = ArchitectureContextResult(
        document_index=None,
        knowledge=[KnowledgeClaim(
            category="responsibilities",
            subject="Audit log capability",
            statement="Audit log listing is provided as a shared capability.",
            related_subjects=["audit consumers"],
            certainty="explicit",
            section_ids=["section-1"],
            reasoning="Direct statement of shared responsibility.",
            constraint="required",
            evidence=[KnowledgeEvidence(section_id="section-1", start_line=1, end_line=1,
                quote="Audit log listing is provided as a shared capability.")],
        )],
        knowledge_issues=[],
        covered_categories=[],
        pending_categories=[],
        evaluated_categories=[],
        coverage_assessment_status="not_run",
        consulted_documents=[],
        section_paths={"section-1": "docs/architecture.md"},
        validation_errors=[],
        execution_status="partial",
        finalization_reason="partial_context",
    )
    scripted = ScriptedModel({
        "investigations": [{
            "capability": "Shared audit-log listing",
            "question": "Does the documented shared audit-log capability have compatible providers and consumers?",
            "document_claim_ids": ["claim-0"],
            "initial_targets": ["service.py"],
            "objectives": ["Locate actual providers and consumers."],
            "reuse_criteria": ["Providers implement compatible contracts and semantics."],
            "independent_implementation_criteria": ["Consumers require materially different domain behavior."],
            "priority": "high",
            "rationale": "The supplied claim explicitly calls the capability shared.",
            "documented_reuse_expectation": "Audit listing is provided as a shared capability.",
            "implementation_uncertainty": "Whether consumers reuse compatible providers.",
        }],
        "limitations": [],
        "insufficient_architectural_evidence": False,
    })
    valid_response = next(scripted.responses)
    discovery = {"capabilities": [{
        "capability": "Shared audit-log listing", "documented_reuse_expectation": "Shared audit listing.",
        "document_claim_ids": ["claim-0"], "uncertainty": "Whether consumers reuse the provider.",
    }]}
    correlation = {"groups": [{"capability": "Shared audit-log listing",
        "capability_ids": ["capability-0"], "rationale": "Single capability with original evidence to inspect."}]}
    if invalid_first:
        invalid_response = json.loads(json.dumps(valid_response))
        invalid_response["investigations"][0]["initial_targets"] = ["invented/directory/"]
        scripted.responses = iter([discovery, correlation, invalid_response, valid_response, close_from_context])
    else:
        scripted.responses = iter([discovery, correlation, valid_response, close_from_context])
    output = asyncio.run(ReuseOpportunityDocDrivenAgent(
        scripted, InvestigationConfig(),
    ).run(toolset(root), ReuseOpportunityDocDrivenRequest(documented_architecture=document)))

    assert output.status == "investigation_partial"
    assert output.termination_reason == "investigations_partial"
    assert output.model_calls == (5 if invalid_first else 4)
    assert output.tool_calls >= 1
    assert len(output.investigation_results) == 1
    assert output.investigation_results[0].status == "inconclusive"
    assert "functional_comparison_missing" in output.investigation_results[0].limitations
    assert output.investigation_results[0].components == ["service.py"]
    assert output.evidence
    assert len(output.plan.investigations) == 1
    assert output.plan.investigations[0].id
    assert output.plan.document_claims["claim-0"]["evidence"][0]["quote"].startswith("Audit log")
    assert output.findings == []
    assert output.evidence
    assert output.planning_diagnostics["input_claim_count"] == 1
    assert output.planning_diagnostics["batches_processed"] == 1
    assert output.planning_diagnostics["context_size_breakdown"]["original_claim_characters"] > 0
    if invalid_first:
        correction = " ".join(str(message.content) for messages in scripted.history for message in messages)
        assert "planning_unknown_target" in correction
        assert "directories containing indexed files" in correction
        assert "allowed_document_claim_ids" in correction


def test_multi_portion_plan_uses_all_claims_and_reports_diagnostics(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "service.py").write_text("def service():\n    return None\n", encoding="utf-8")
    claims = [KnowledgeClaim(
        category="responsibilities",
        subject=f"Capability {index}",
        statement=f"Capability {index} is documented as a shared provider. " + "context " * 250,
        certainty="explicit",
        section_ids=[f"section-{index}"],
        reasoning="Original claim rationale.",
        constraint="required",
        evidence=[KnowledgeEvidence(section_id=f"section-{index}", start_line=1, end_line=1,
            quote="Original quote retained by host.")],
    ) for index in range(60)]
    architecture = ArchitectureContextResult(
        document_index=None,
        knowledge=claims,
        knowledge_issues=[],
        covered_categories=[],
        pending_categories=[],
        evaluated_categories=[],
        coverage_assessment_status="not_run",
        consulted_documents=[],
        section_paths={},
        validation_errors=[],
        execution_status="partial",
        finalization_reason="partial_context",
    )
    empty_response = {"capabilities": [], "limitations": []}
    model = ScriptedModel([empty_response] * 20)

    result = asyncio.run(ReuseOpportunityDocDrivenAgent(model, InvestigationConfig()).run(
        toolset(root), ReuseOpportunityDocDrivenRequest(documented_architecture=architecture)))

    assert result.status == "planning_only"
    assert result.model_calls >= 2
    assert result.planning_diagnostics["batches_processed"] == result.model_calls
    assert result.planning_diagnostics["claims_sent_to_model"] == 60
    assert result.planning_diagnostics["omitted_claim_ids"] == []
    for messages in model.history:
        context = json.loads(messages[1].content)
        assert context["phase"] == "identify"
        assert all("evidence" not in claim for claim in context["claims"])


def architecture_context(claims):
    return ArchitectureContextResult(document_index=None, knowledge=claims, knowledge_issues=[],
        covered_categories=[], pending_categories=[], evaluated_categories=[], coverage_assessment_status="not_run",
        consulted_documents=[], section_paths={"section-a": "docs/architecture.md"},
        validation_errors=[], execution_status="partial", finalization_reason="partial_context")


def symbol_map(root):
    snapshot = RepositoryAnalysisService().analyze_sync(root)
    return {symbol.name: symbol.id for symbol in snapshot.symbols}


def documentary_claim(subject, statement, section="section-a", constraint="required"):
    return KnowledgeClaim(category="responsibilities", subject=subject, statement=statement,
        certainty="explicit", section_ids=[section], reasoning="Original architectural rationale, not a model summary.",
        constraint=constraint, evidence=[KnowledgeEvidence(section_id=section, start_line=1, end_line=1,
            quote="Exact original quotation: " + statement)])


def test_semantic_global_grouping_recovers_exception_from_other_portion(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "provider.py").write_text("def provider():\n    pass\n", encoding="utf-8")
    doc = architecture_context([
        documentary_claim("Audit capability", "Audit listing is a shared capability in provider.py."),
        documentary_claim("Audit capability", "Archived audit records intentionally use independent semantics.",
            section="section-b", constraint="exception"),
        documentary_claim("Common event reader", "Event reading provides the same common audit capability."),
    ])

    def separate_portions(self, records):
        from server.agents.maintainability.v2.reusability.reuse_opportunity_doc_driven.planning import (
            discovery_projection,
        )
        return [[discovery_projection(record)] for record in records.values()], []

    monkeypatch.setattr(ReuseOpportunityExecution, "_discovery_batches", separate_portions)

    def capability(name, claim_id):
        return {"capabilities": [{"capability": name, "documented_reuse_expectation": "Shared audit listing.",
            "document_claim_ids": [claim_id], "uncertainty": "Whether active audit consumers reuse a compatible provider."}]}

    def correlate(messages):
        context = json.loads(messages[1].content)
        assert context["phase"] == "correlate"
        assert len(context["capabilities"]) == 2
        assert {item["capability"] for item in context["capabilities"]} == {"Audit listing", "Common event reader"}
        return {"groups": [{"capability": "Active audit listing", "capability_ids": ["capability-0", "capability-1"],
            "additional_document_claim_ids": ["claim-1"], "rationale": "Same active capability; read the archived-record exception."}]}

    def formulate(messages):
        context = json.loads(messages[1].content)
        assert context["phase"] == "formulate"
        assert len(context["claims"]) == 3
        exception = next(item for item in context["claims"] if item["id"] == "claim-1")
        assert exception["constraint"] == "exception"
        assert exception["evidence"][0]["quote"].startswith("Exact original quotation")
        assert exception["reasoning"].startswith("Original architectural rationale")
        assert "provider.py" in context["repository_navigation"]["indexed_target_candidates"]
        response = proposal_response(["provider.py"], ["claim-0", "claim-2"])
        return response.model_dump(mode="json")

    model = ScriptedModel([capability("Audit listing", "claim-0"), {"capabilities": []},
        capability("Common event reader", "claim-2"), correlate, formulate, close_from_context])
    result = asyncio.run(ReuseOpportunityDocDrivenAgent(model, InvestigationConfig()).run(toolset(root),
        ReuseOpportunityDocDrivenRequest(documented_architecture=doc)))
    assert result.status == "investigation_partial"
    assert len(result.plan.investigations) == 1
    assert result.model_calls == 6
    assert result.tool_calls >= 1
    assert result.planning_diagnostics["global_correlation_completed"] is True
    assert result.plan.document_claims["claim-1"]["constraint"] == "exception"


def test_correlation_must_account_for_every_seed_without_merging_by_name():
    execution = planning_execution()
    execution._capability_ids = {"capability-0", "capability-1"}
    partial = ReuseCorrelationResponse(groups=[{
        "capability": "Shared capability", "capability_ids": ["capability-0"], "rationale": "One provider."
    }])
    with pytest.raises(PydanticCustomError, match="Every supplied capability"):
        execution.prepare_structured_result("plan_investigation", partial, {})
    complete = partial.model_copy(update={"excluded_capabilities": {"capability-1": "Different domain; no reuse intent."}})
    assert execution.prepare_structured_result("plan_investigation", complete, {}) is complete


def test_global_group_does_not_union_investigation_field_limits():
    # Two discovery sets can jointly cite more than the final per-investigation
    # limit; the LLM must select supporting citations instead of host list union.
    correlation = ReuseCorrelationResponse(groups=[{
        "capability": "Shared audit", "capability_ids": [f"capability-{i}" for i in range(30)],
        "rationale": "One capability across documentary portions.",
    }])
    execution = planning_execution()
    execution._capability_ids = {f"capability-{i}" for i in range(30)}
    assert execution.prepare_structured_result("plan_investigation", correlation, {}) is correlation
    final = execution._validate_plan(proposal_response([], ["claim-0"]), {"claim-0"})
    assert len(final[0].document_claim_ids) == 1


def test_blocked_request_counts_no_claims_as_sent(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "service.py").write_text("def service():\n    pass\n", encoding="utf-8")
    doc = architecture_context([documentary_claim("Shared reader", "Shared capability. " + "x" * 20_000)])
    model = ScriptedModel([])
    result = asyncio.run(ReuseOpportunityDocDrivenAgent(model, InvestigationConfig(max_context_characters=4000)).run(
        toolset(root), ReuseOpportunityDocDrivenRequest(documented_architecture=doc)))
    assert result.status == "planning_blocked"
    assert result.model_calls == 0
    assert result.planning_diagnostics["claims_sent_to_model"] == 0
    assert result.planning_diagnostics["oversized_claim_ids"] == ["claim-0"]
    assert result.planning_diagnostics["omitted_claim_ids"] == ["claim-0"]


def test_interrupted_discovery_preserves_omissions_and_unresolved_capabilities(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "service.py").write_text("def service():\n    pass\n", encoding="utf-8")
    doc = architecture_context([documentary_claim(f"Capability {i}", "Shared provider.") for i in range(3)])

    def batches(self, records):
        from server.agents.maintainability.v2.reusability.reuse_opportunity_doc_driven.planning import (
            discovery_projection,
        )
        return [[discovery_projection(records["claim-0"])],
            [discovery_projection(records["claim-1"])]], ["claim-2"]

    monkeypatch.setattr(ReuseOpportunityExecution, "_discovery_batches", batches)
    model = ScriptedModel([{"capabilities": [{"capability": "Shared reader",
        "document_claim_ids": ["claim-0"], "documented_reuse_expectation": "Shared reading.",
        "uncertainty": "Whether consumers reuse the same provider."}]}, ValueError("Provider failure")])
    result = asyncio.run(ReuseOpportunityDocDrivenAgent(model, InvestigationConfig()).run(
        toolset(root), ReuseOpportunityDocDrivenRequest(documented_architecture=doc)))
    diagnostics = result.planning_diagnostics
    assert result.status == "planning_partial"
    assert diagnostics["identified_claim_ids"] == ["claim-0"]
    assert diagnostics["omitted_claim_ids"] == ["claim-1", "claim-2"]
    assert diagnostics["unresolved_capability_ids"] == ["capability-0"]
    assert diagnostics["claims_sent_to_model"] == 2
    assert diagnostics["batches_processed"] == 1
    assert not diagnostics["global_correlation_completed"]
    assert result.findings == []


def test_equal_labels_can_remain_separate_semantic_groups():
    execution = planning_execution()
    execution._capability_ids = {"capability-0", "capability-1"}
    response = ReuseCorrelationResponse(groups=[{
        "capability": "Shared reader", "capability_ids": [key], "rationale": rationale,
    } for key, rationale in [
        ("capability-0", "Live records provider with one contract."),
        ("capability-1", "Archived records are a separate domain with incompatible semantics."),
    ]])
    assert execution.prepare_structured_result("plan_investigation", response, {}) is response
    assert len(response.groups) == 2


def test_prompt_requires_shared_functional_capability_and_reuse_intention():
    from pathlib import Path

    from server.agents.maintainability.v2.reusability.reuse_opportunity_doc_driven import (
        execution,
    )

    prompt = (Path(execution.__file__).parent / "prompts" / "plan_investigation.md").read_text(encoding="utf-8")

    assert "substantially the same functional capability and the same documented reuse" in prompt
    assert "architectural flow, layer, domain" in prompt
    assert "If this" in prompt and "keep the capabilities separate" in prompt


def test_broad_same_layer_capabilities_remain_separate_through_formulation(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "audit.py").write_text("def audit_listing():\n    pass\n", encoding="utf-8")
    (root / "payment.py").write_text("def payment_report():\n    pass\n", encoding="utf-8")
    doc = architecture_context([
        documentary_claim("Audit capability", "Audit listing is a shared service capability in the same Route to Service flow."),
        documentary_claim("Payment capability", "Payment report generation is a shared service capability in the same Route to Service flow."),
    ])
    discovery = {"capabilities": [
        {"capability": "Audit listing", "documented_reuse_expectation": "Shared audit listing.",
         "document_claim_ids": ["claim-0"], "uncertainty": "Whether active consumers reuse audit listing."},
        {"capability": "Payment report generation", "documented_reuse_expectation": "Shared payment reporting.",
         "document_claim_ids": ["claim-1"], "uncertainty": "Whether reporting consumers reuse the generator."},
    ]}
    correlation = {"groups": [
        {"capability": "Audit listing", "capability_ids": ["capability-0"],
         "rationale": "Shared Route to Service flow only; this is the audit-listing functional capability."},
        {"capability": "Payment report generation", "capability_ids": ["capability-1"],
         "rationale": "Shared Route to Service flow only; this is the payment-report functional capability."},
    ]}
    formulate_audit = proposal_response(["audit.py"], ["claim-0"]).model_dump(mode="json")
    formulate_audit["investigations"][0].update(capability="Audit listing", question="Do actual audit providers and consumers implement compatible audit-listing semantics?", documented_reuse_expectation="Audit listing is a shared capability.")
    formulate_payment = proposal_response(["payment.py"], ["claim-1"]).model_dump(mode="json")
    formulate_payment["investigations"][0].update(capability="Payment report generation", question="Do actual payment-report providers and consumers implement compatible reporting semantics?", documented_reuse_expectation="Payment report generation is a shared capability.")
    model = ScriptedModel([discovery, correlation, formulate_audit, formulate_payment,
        close_from_context, close_from_context])

    result = asyncio.run(ReuseOpportunityDocDrivenAgent(model, InvestigationConfig()).run(
        toolset(root), ReuseOpportunityDocDrivenRequest(documented_architecture=doc)))

    assert [item.capability for item in result.plan.investigations] == [
        "Audit listing", "Payment report generation",
    ]
    assert result.model_calls == 6
    assert result.tool_calls >= 2
    assert len(result.investigation_results) == 2
    assert result.status == "investigation_partial"
    assert all(len(item.document_claim_ids) == 1 for item in result.plan.investigations)


def test_indexed_target_candidates_include_explicit_dirs_and_exclude_unverified_paths():
    from server.agents.maintainability.v2.reusability.reuse_opportunity_doc_driven.planning import (
        documentary_records,
        indexed_target_candidates,
    )

    claims = [
        documentary_claim("Documented provider", "Provider lives in ai-service/providers/ and handles requests."),
        documentary_claim("Documented unknown", "Documentation mentions invented/not-indexed/ without indexing it."),
    ]
    records = documentary_records(architecture_context(claims))
    candidates = indexed_target_candidates(records.values(), ["ai-service/providers/gateway.py"])

    assert "ai-service/providers" in candidates
    assert "ai-service/providers/gateway.py" not in candidates
    assert "invented/not-indexed" not in candidates


def test_prompt_excludes_architecture_conformance_as_reuse_opportunity():
    from pathlib import Path

    from server.agents.maintainability.v2.reusability.reuse_opportunity_doc_driven import (
        execution,
    )

    prompt = (Path(execution.__file__).parent / "prompts" / "plan_investigation.md").read_text(encoding="utf-8")

    normalized_prompt = " ".join(prompt.split())
    assert "dependency-inversion mechanism" in normalized_prompt or "inversion of dependency" in normalized_prompt
    assert "provider swapping" in normalized_prompt
    assert "Ask only whether actual providers, consumers and alternative implementations" in normalized_prompt


def test_pure_decoupling_seed_is_explicitly_excluded_before_formulation(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "provider.py").write_text("def provider():\n    pass\n", encoding="utf-8")
    doc = architecture_context([documentary_claim(
        "LLM provider abstraction",
        "The LlmProvider interface permits provider swapping without modifying orchestrators.",
    )])
    discovery = {"capabilities": [{
        "capability": "LlmProvider interface", "documented_reuse_expectation": "Provider swapping without dependency changes.",
        "document_claim_ids": ["claim-0"],
        "uncertainty": "Whether the design is configurable or decoupled.",
    }]}
    exclusion = {
        "groups": [],
        "excluded_capabilities": {
            "capability-0": "Only dependency inversion and provider swapping; no concrete repeated functional behavior or reuse decision."
        },
        "limitations": ["No functional reuse capability survived architectural-intent review."],
    }
    model = ScriptedModel([discovery, exclusion])

    result = asyncio.run(ReuseOpportunityDocDrivenAgent(model, InvestigationConfig()).run(
        toolset(root), ReuseOpportunityDocDrivenRequest(documented_architecture=doc)))

    assert result.plan.investigations == []
    assert result.model_calls == 2
    assert result.planning_diagnostics["global_correlation_completed"] is True
    assert result.planning_diagnostics["excluded_capabilities"]["capability-0"].startswith("Only dependency inversion")
    assert result.planning_diagnostics["formulation_reviewed_claim_ids"] == []


def test_prompt_covers_functional_reuse_investigation_dimensions():
    from pathlib import Path

    from server.agents.maintainability.v2.reusability.reuse_opportunity_doc_driven import (
        execution,
    )

    prompt = (Path(execution.__file__).parent / "prompts" / "plan_investigation.md").read_text(
        encoding="utf-8"
    )
    normalized_prompt = " ".join(prompt.split())

    for dimension in [
        "Functional duplication",
        "Underused reuse",
        "Incomplete centralization",
        "Semantic equivalence",
        "Architectural viability",
        "Justified separation",
        "must allow the reuse hypothesis to be supported or discarded",
        "not merely verify interface compliance",
    ]:
        assert dimension in normalized_prompt


def test_prompt_requires_decision_oriented_functional_reuse_questions():
    from pathlib import Path

    from server.agents.maintainability.v2.reusability.reuse_opportunity_doc_driven import (
        execution,
    )

    normalized_prompt = " ".join(
        (Path(execution.__file__).parent / "prompts" / "plan_investigation.md").read_text(
            encoding="utf-8"
        ).split()
    )

    assert "shared candidate or duplicated candidate alternatives" in normalized_prompt
    assert "actual consumers or providers, or explicitly unknowns" in normalized_prompt
    assert "reuse-vs-separation decision" in normalized_prompt
    assert "which reuse hypothesis" in normalized_prompt
    assert "If the cited evidence supports only an abstraction" in normalized_prompt


def reuse_opportunity_from_context(messages, symbols):
    context = json.loads(messages[1].content)
    investigate = context["investigation"]
    sources = [item for item in context["evidence"] if item["kind"] == "source"]
    paths = sorted({item["path"] for item in sources})
    evidence_ids = [item["id"] for item in context["evidence"]]
    return {
        "action": "close",
        "queries": [],
        "conclusion": {
            "investigation_id": investigate["id"],
            "status": "reuse_opportunity",
            "summary": "The source duplicates a documented shared audit-listing capability.",
            "justification": "The inspected independent implementation and local consumer support reuse.",
            "components": paths,
            "symbol_ids": sorted({symbol for item in sources for symbol in item["symbol_ids"]}),
            "relationship_ids": [],
            "evidence_ids": evidence_ids,
            "candidates": [{
                "id": "reuse-candidate-1",
                "title": "Audit listing is reimplemented locally",
                "description": "A local implementation duplicates the documented shared audit-listing behavior.",
                "criterion_id": "reuse-opportunity",
                "kind": "design_observation",
                "components": paths,
                "evidence_ids": evidence_ids,
                "justification": "The source contains the local capability and consumer evidence.",
                "modularity_impact": "Shared provider behavior is reproduced outside the shared implementation.",
                "severity": "medium",
                "confidence": 0.8,
                "recommendation": "Review the contract and consolidate behavior if domain constraints permit.",
                "symbol_ids": sorted(symbols.values()),
                "relationship_ids": [],
                "document_claim_ids": investigate["document_claim_ids"],
                "shared_component": paths[0],
                "independent_implementations": [paths[0] + "#duplicate_audit_listing"],
                "shared_behavior": "Return the shared audit-listing records for authorized consumers.",
                "independent_behavior": "Recompute and return the same audit-listing records locally.",
                "behavior_comparison": "Both operate on audit-listing records and return equivalent list behavior; the local implementation duplicates the shared provider behavior.",
                "shared_symbol_ids": [symbols["audit_listing"]],
                "independent_symbol_ids": [symbols["duplicate_audit_listing"]],
                "reuse_hypothesis": "functional_duplication",
            }],
            "limitations": [],
            "claim_assessments": [{
                "claim_id": claim_id,
                "status": "supported",
                "rationale": "The documented shared capability exists in the inspected source.",
                "code_evidence_ids": evidence_ids,
                "scope_paths": paths,
                "limitations": [],
            } for claim_id in investigate["document_claim_ids"]],
            "comparisons": [comparison_from_context(context, "equivalent_shareable")],
        },
    }


def comparison_from_context(context, outcome):
    values = context["symbols"]
    shared = next((item for item in values if item["name"] == "audit_listing"), values[0])
    other = next(item for item in values if item["id"] != shared["id"])
    def evidence_for(symbol):
        return [item["id"] for item in context["evidence"] if item["kind"] == "source" and item["path"] == symbol["path"]]
    return {"shared_symbol_id": shared["id"], "other_symbol_id": other["id"],
        "other_role": "independent_implementation", "outcome": outcome,
        "shared_evidence_ids": evidence_for(shared), "other_evidence_ids": evidence_for(other),
        "responsibility": "Controlled semantic comparison for the test, not a live judgment.",
        "inputs_outputs": "Both bodies inspected.", "effects": "No side effects in fixture.",
        "rules_and_errors": "No validation/errors in fixture.",
        "architectural_constraints": "Controlled fixture permits this scoped decision.",
        "rationale": "Source-backed scripted outcome."}


def test_investigate_loop_returns_an_evidence_backed_reuse_candidate(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "service.py").write_text(
        "def audit_listing():\n    pass\n\ndef duplicate_audit_listing():\n    pass\n",
        encoding="utf-8",
    )
    doc = architecture_context([documentary_claim(
        "Audit listing capability",
        "Audit listing is provided as a shared capability.",
    )])
    discovery = {"capabilities": [{
        "capability": "Shared audit listing",
        "documented_reuse_expectation": "Audit listing is a shared capability.",
        "document_claim_ids": ["claim-0"],
        "uncertainty": "Whether the local implementation duplicates the shared behavior.",
    }]}
    correlation = {
        "groups": [{"capability": "Shared audit listing", "capability_ids": ["capability-0"],
            "rationale": "Common functional behavior and one shared expectation."}]
    }
    formulate = proposal_response(["service.py"], ["claim-0"]).model_dump(mode="json")
    formulate["investigations"][0].update(
        question="Do actual audit-listing implementations share compatible behavior instead of being reimplemented locally?",
        documented_reuse_expectation="Audit listing is a shared capability.",
    )
    symbol_ids = symbol_map(root)
    implementation = lambda messages: reuse_opportunity_from_context(messages, symbol_ids)
    model = ScriptedModel([discovery, correlation, formulate, implementation])

    result = asyncio.run(ReuseOpportunityDocDrivenAgent(
        model, InvestigationConfig(),
    ).run(toolset(root), ReuseOpportunityDocDrivenRequest(documented_architecture=doc)))

    assert result.status == "investigation_complete"
    assert result.tool_calls >= 1
    assert len(result.investigation_results) == 1
    assert result.investigation_results[0].status == "reuse_opportunity"
    assert result.investigation_results[0].candidates[0].shared_component == "service.py"
    assert result.investigation_results[0].claim_assessments[0].status == "supported"
    assert result.hypotheses[0].status == "confirmed"
    assert result.candidates


def test_noninconclusive_candidate_without_inspected_paths_is_correctable(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "service.py").write_text(
        "def audit_listing():\n    pass\n\ndef duplicate_audit_listing():\n    pass\n",
        encoding="utf-8",
    )
    doc = architecture_context([documentary_claim(
        "Audit listing capability",
        "Audit listing is provided as a shared capability.",
    )])

    discovery = {"capabilities": [{
        "capability": "Shared audit listing",
        "documented_reuse_expectation": "Audit listing is a shared capability.",
        "document_claim_ids": ["claim-0"],
        "uncertainty": "Whether the local implementation duplicates the shared behavior.",
    }]}
    correlation = {
        "groups": [{"capability": "Shared audit listing", "capability_ids": ["capability-0"],
            "rationale": "Common functional behavior and one shared expectation."}]
    }
    formulate = proposal_response(["service.py"], ["claim-0"]).model_dump(mode="json")

    def invalid_candidate(messages):
        data = reuse_opportunity_from_context(messages, symbol_map(root))
        data["conclusion"]["components"].append("app/api")
        data["conclusion"]["candidates"][0]["components"].append("app/api")
        return data

    model = ScriptedModel([discovery, correlation, formulate, invalid_candidate, close_from_context])
    result = asyncio.run(ReuseOpportunityDocDrivenAgent(
        model, InvestigationConfig(),
    ).run(toolset(root), ReuseOpportunityDocDrivenRequest(documented_architecture=doc)))

    correction = " ".join(
        str(message.content) for messages in model.history for message in messages
    )
    assert "candidate_component_uninspected" in correction
    assert result.status == "investigation_complete"
    assert result.investigation_results[0].candidates == []


def test_inconclusive_conclusion_cannot_carry_reuse_candidates(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "service.py").write_text(
        "def audit_listing():\n    pass\n\ndef duplicate_audit_listing():\n    pass\n",
        encoding="utf-8",
    )
    doc = architecture_context([documentary_claim(
        "Audit listing capability",
        "Audit listing is provided as a shared capability.",
    )])
    discovery = {"capabilities": [{
        "capability": "Shared audit listing",
        "documented_reuse_expectation": "Audit listing is a shared capability.",
        "document_claim_ids": ["claim-0"],
        "uncertainty": "Whether the local implementation duplicates the shared behavior.",
    }]}

    def invalid_candidate(messages):
        data = reuse_opportunity_from_context(messages, symbol_map(root))
        data["conclusion"]["status"] = "inconclusive"
        return data

    correlation = {
        "groups": [{"capability": "Shared audit listing", "capability_ids": ["capability-0"],
            "rationale": "Common functional behavior and one shared expectation."}]
    }
    formulate = proposal_response(["service.py"], ["claim-0"]).model_dump(mode="json")
    model = ScriptedModel([discovery, correlation, formulate, invalid_candidate, close_from_context])
    result = asyncio.run(ReuseOpportunityDocDrivenAgent(
        model, InvestigationConfig(),
    ).run(toolset(root), ReuseOpportunityDocDrivenRequest(documented_architecture=doc)))

    correction = " ".join(
        str(message.content) for messages in model.history for message in messages
    )
    assert "candidate_status_mismatch" in correction
    assert result.investigation_results[0].candidates == []


def test_candidate_must_identify_an_existing_inspected_independent_symbol(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "service.py").write_text(
        "def audit_listing():\n    pass\n\ndef duplicate_audit_listing():\n    pass\n",
        encoding="utf-8",
    )
    doc = architecture_context([documentary_claim(
        "Audit listing capability",
        "Audit listing is provided as a shared capability.",
    )])
    discovery = {"capabilities": [{
        "capability": "Shared audit listing",
        "documented_reuse_expectation": "Audit listing is a shared capability.",
        "document_claim_ids": ["claim-0"],
        "uncertainty": "Whether the local implementation duplicates the shared behavior.",
    }]}
    correlation = {
        "groups": [{"capability": "Shared audit listing", "capability_ids": ["capability-0"],
            "rationale": "Common functional behavior and one shared expectation."}]
    }
    formulate = proposal_response(["service.py"], ["claim-0"]).model_dump(mode="json")

    def invented_symbol(messages):
        data = reuse_opportunity_from_context(messages, symbol_map(root))
        data["conclusion"]["candidates"][0]["independent_implementations"] = [
            "service.py#symbol_that_does_not_exist"
        ]
        return data

    model = ScriptedModel([discovery, correlation, formulate, invented_symbol, close_from_context])
    result = asyncio.run(ReuseOpportunityDocDrivenAgent(
        model, InvestigationConfig(),
    ).run(toolset(root), ReuseOpportunityDocDrivenRequest(documented_architecture=doc)))

    correction = " ".join(
        str(message.content) for messages in model.history for message in messages
    )
    assert "candidate_independent_implementation" in correction
    assert result.status == "investigation_complete"
