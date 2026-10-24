"""Scope laundering, targeted inspection and continuation regressions (no providers)."""

import asyncio
import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from test_architecture_boundary import (
    PLAN,
    ScriptedModel,
    audit,
    call,
    evaluation,
    request,
    review,
    toolset,
)

from server.agents.maintainability.modularity.architecture_boundary import (
    ArchitectureBoundaryAgent,
    AuditRequest,
    BoundaryConfig,
)
from server.agents.maintainability.modularity.architecture_boundary.claims import (
    assertion_issues,
)
from server.agents.maintainability.modularity.architecture_boundary.discovery import (
    BoundaryDiscovery,
)
from server.agents.maintainability.modularity.architecture_boundary.execution import (
    BoundaryExecution,
)
from server.agents.schemes.investigator import BoundaryEvaluation
from server.runtimes.investigation.messages import compact_tool_history

pytest_plugins = ["test_architecture_boundary"]


@pytest.fixture
def services(tmp_path):
    root = tmp_path / "checkout"
    (root / "ai-service").mkdir(parents=True)
    (root / "app").mkdir()
    (root / "ai-service" / "pyproject.toml").write_text('[project]\nname = "inference"\nversion = "1.0"\n')
    (root / "ai-service" / "app.py").write_text('from fastapi import FastAPI\napp = FastAPI()\n')
    (root / "app" / "page.tsx").write_text('export default function Page() { return null; }\n')
    return root


@pytest.mark.parametrize("broad", [True, False])
def test_packaging_evidence_cannot_certify_decoupling_even_when_reviewer_accepts(services, broad):
    question = "Is the Python service cleanly decoupled from the Next.js app?" if broad else "Is a Python package declared?"
    plan = {"objectives": ["Inspect boundaries"], "components": ["ai-service", "app"], "hypotheses": [
        {"id": "h1", "question": question, "criterion_id": "responsibility-boundaries", "evidence_needed": []}]}

    def assess(messages):
        context = json.loads(messages[1].content)
        refs = [item for item in context["evidence"] if item["kind"] == "source"]
        ids = [item["id"] for item in refs]
        description = ("Clear architectural boundaries cleanly decouple the Next.js app and ai-service."
            if broad else "ai-service/pyproject.toml declares a Python package with its own name and version.")
        candidate = {"id": "f1", "title": "Clean Separation of Presentation and AI Backend Boundaries" if broad else "Python package declaration",
            "description": description, "criterion_id": "responsibility-boundaries", "kind": "design_observation",
            "components": ["app", "ai-service"] if broad else ["ai-service/pyproject.toml"],
            "evidence_ids": ids, "justification": description, "modularity_impact": "Independent deployment is possible." if broad else "Packaging is declared; integration was not verified.",
            "severity": "info", "confidence": 0.8, "recommendation": "Retain the observed package declaration."}
        return {"sufficient": True, "hypotheses": [{**plan["hypotheses"][0], "status": "confirmed", "evidence_ids": ids,
            "rationale": description}], "candidates": [candidate], "missing_information": [],
            "claim_checks": [{"subject_type": kind, "subject_id": identifier, "claim_kind": "declaration",
                "scope_paths": [item["path"] for item in refs], "support": [{"evidence_id": item["id"],
                    "role": "declaration", "observation": "Package name and version declared."} for item in refs],
                "coverage_complete": True} for kind, identifier in [("hypothesis", "h1"), ("candidate", "f1")]]}

    model = ScriptedModel([plan, call(arguments={"path": "ai-service/pyproject.toml", "start_line": 1, "end_line": 3}),
        AIMessage(content="Ready"), assess, review()])
    result = asyncio.run(ArchitectureBoundaryAgent(model, BoundaryConfig(max_iterations=1, max_schema_retries=0,
        max_total_tokens=300000)).run(toolset(services), AuditRequest()))
    if broad:
        assert result.findings[0].validation_status == "insufficient_evidence"
        assert "boundary_claim_understates_conclusion:deployment" in result.findings[0].validation_issues
        assert result.hypotheses[0].status == "inconclusive"
        assert result.critical_review.findings[0].scope_supported is False
    else:
        assert result.findings[0].validation_status == "accepted"
        assert result.hypotheses[0].status == "confirmed"


def test_complete_flag_does_not_replace_named_components_and_verifications(services):
    tools = toolset(services)
    tools.execute("get_source_excerpt", {"path": "ai-service/app.py", "start_line": 1, "end_line": 2}, tool_call_id="source")
    model = ScriptedModel([])
    execution = BoundaryExecution(model, BoundaryConfig(), tools, AuditRequest())
    ref = execution.references()[0]
    value = BoundaryEvaluation(sufficient=True, candidates=[], missing_information=[], hypotheses=[{
        "id": "h1", "question": "Are app/ and ai-service/ cleanly decoupled?", "status": "confirmed", "evidence_ids": [ref.id]}],
        claim_checks=[{"subject_type": "hypothesis", "subject_id": "h1", "claim_kind": "isolation",
            "scope_paths": [ref.path], "coverage_complete": True, "support": [{"evidence_id": ref.id,
                "role": role, "observation": "FastAPI construction"} for role in ("implementation", "usage", "composition")]}])
    issues = execution.support_issues(value.hypotheses[0], value.claim_checks[0])
    assert "boundary_verification_missing:shared_resources" in issues
    assert "boundary_scope_coverage_not_demonstrated" in issues


def test_search_hits_do_not_count_as_source_inspection_or_complete_a_boundary(repo):
    tools = toolset(repo)
    tools.execute("search_repository_text", {"query": "save"}, tool_call_id="search")
    execution = BoundaryExecution(ScriptedModel([]), BoundaryConfig(), tools, request())
    discovery = BoundaryDiscovery(tools.accessible_snapshot)
    coverage = discovery.coverage(execution.references(), tools.tool_measurements)
    assert coverage["search_hit_file_count"] > 0
    assert coverage["excerpt_file_count"] == coverage["fully_inspected_file_count"] == 0
    tools.execute("get_source_excerpt", {"path": "domain/service.py", "start_line": 1, "end_line": 4}, tool_call_id="read")
    coverage = discovery.coverage(execution.references(), tools.tool_measurements)
    assert coverage["excerpt_file_count"] == coverage["fully_inspected_file_count"] == 1
    assert coverage["dependency_endpoint_pair_count"] == 0


def test_pending_question_prioritizes_imported_target_and_phase_costs_are_accounted(repo):
    partial, _, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"),
        lambda messages: evaluation(messages, sufficient=False, candidate=False)], max_iterations=1)
    task = next(item for item in partial.investigation_tasks if item["subject_id"] == "h1")
    assert any(read["arguments"]["path"] == "storage/db.py" for read in task["next_source_reads"])
    assert partial.investigation_progress[0]["pending_task_count"] > 0
    assert sum(item["accounted_tokens"] for item in partial.consumption_by_phase.values()) == partial.accounted_tokens
    assert sum(item["model_calls"] for item in partial.consumption_by_phase.values()) == partial.model_calls


def test_continuation_reuses_plan_revalidates_source_and_keeps_previous_usage_separate(repo):
    partial, _, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"),
        lambda messages: evaluation(messages, sufficient=False, candidate=False)], max_iterations=1)
    model = ScriptedModel([evaluation, review()])
    follow_up = request().model_copy(update={"continuation": partial})
    result = asyncio.run(ArchitectureBoundaryAgent(model, BoundaryConfig(max_total_tokens=300000)).run(toolset(repo), follow_up))
    assert result.findings[0].validation_status == "accepted"
    assert result.model_calls == 2
    assert result.continuation_usage["model_calls"] == partial.model_calls
    assert result.tool_calls == 1
    assert result.evidence[0].id != partial.evidence[0].id
    assert "Now execute evaluate_evidence" in model.history[0][-1].content


def test_continuation_rejects_changed_snapshot_before_any_provider_call(repo):
    partial, _, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"),
        lambda messages: evaluation(messages, sufficient=False, candidate=False)], max_iterations=1)
    (repo / "storage" / "db.py").write_text("def save():\n    return 2\n")
    model = ScriptedModel([])
    with pytest.raises(ValueError, match="same repository, snapshot"):
        asyncio.run(ArchitectureBoundaryAgent(model).run(toolset(repo), request().model_copy(update={"continuation": partial})))
    assert model.history == []


def test_focused_search_history_preserves_cited_line_and_authoritative_messages():
    payload = {"data": {"items": [{"file_id": "caller", "line": 1, "text": "import storage"},
        {"file_id": "unrelated", "line": 2, "text": "irrelevant" * 100}]}, "evidence": [
        {"id": "cited", "file_id": "caller", "kind": "source", "start_line": 1, "end_line": 1},
        {"id": "unused", "file_id": "unrelated", "kind": "source", "start_line": 2, "end_line": 2}]}
    original = ToolMessage(content=json.dumps(payload), name="search_repository_text", tool_call_id="search")
    history = compact_tool_history([original], 100000, ["cited"], focus_search_results=True)
    focused = json.loads(history[0].content)
    assert focused["data"]["items"] == payload["data"]["items"][:1]
    assert focused["data"]["history_omitted_search_hits"] == 1
    assert json.loads(original.content) == payload
    assert history[0].tool_call_id == "search"
    assert len(history[0].content) < len(original.content)


def test_counterexample_does_not_require_proving_complete_isolation():
    from server.agents.schemes.base import Hypothesis
    from server.agents.schemes.investigator import BoundaryClaimCheck

    subject = Hypothesis(id="h", question="Are the two services cleanly decoupled?", status="discarded",
        rationale="They are not decoupled: this inspected caller directly accesses the same database.")
    check = BoundaryClaimCheck(subject_type="hypothesis", subject_id="h", claim_kind="dependency",
        scope_paths=["caller.py"], support=[{"evidence_id": "source", "role": "dependency", "observation": "Direct import."}])
    assert assertion_issues(subject, check) == []


def test_phase_metrics_distinguish_provider_usage_from_estimates(repo):
    class MeteredModel(ScriptedModel):
        async def ainvoke(self, messages, **kwargs):
            response = await super().ainvoke(messages, **kwargs)
            return response.model_copy(update={"usage_metadata": {
                "input_tokens": 100, "output_tokens": 10, "total_tokens": 110}})

    model = MeteredModel([PLAN, call(), AIMessage(content="Ready"), evaluation, review()])
    result = asyncio.run(ArchitectureBoundaryAgent(model, BoundaryConfig(max_total_tokens=300000)).run(toolset(repo), request()))
    assert result.accounted_tokens == 550 and result.estimated_tokens == 0
    assert sum(item["reported_input_tokens"] for item in result.consumption_by_phase.values()) == 500
    assert sum(item["reported_output_tokens"] for item in result.consumption_by_phase.values()) == 50
    assert result.consumption_by_phase["investigate"]["model_calls"] == 2


def test_continuation_rejects_changed_criteria_even_without_previous_findings(repo):
    partial, _, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"),
        lambda messages: evaluation(messages, sufficient=False, candidate=False)], max_iterations=1)
    original = request()
    changed = original.model_copy(update={"continuation": partial, "criteria": [
        original.criteria[0].model_copy(update={"description": "A different architectural rule."})]})
    model = ScriptedModel([])
    with pytest.raises(ValueError, match="request fingerprint"):
        asyncio.run(ArchitectureBoundaryAgent(model).run(toolset(repo), changed))
    assert model.history == []


def test_closing_with_unread_dependency_executes_bounded_reads_before_re_evaluation(repo):
    result, model, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"),
        lambda messages: evaluation(messages, sufficient=False, candidate=False),
        AIMessage(content="Ready without the target"), evaluation, review()], max_iterations=2)
    assert result.iterations == 2
    assert result.findings[0].validation_status == "accepted"
    assert any(ref.path == "storage/db.py" for ref in result.evidence)
    assert result.tool_calls == 2
    assert result.model_calls == len(model.history) == 7
    assert any("save" in message.content for message in model.history[5] if isinstance(message, ToolMessage))


def test_guided_reads_continue_after_delivered_chunks_without_repeating_them(repo):
    tools = toolset(repo)
    tools.execute("get_source_excerpt", {"path": "domain/service.py", "start_line": 1, "end_line": 2}, tool_call_id="first")
    execution = BoundaryExecution(ScriptedModel([]), BoundaryConfig(), tools, request())
    execution._research_tasks = [{"subject_type": "hypothesis", "subject_id": "h1", "next_source_reads": [
        {"tool": "get_source_excerpt", "arguments": {"path": "domain/service.py", "start_line": 1, "end_line": 4}}]}]
    empty = BoundaryEvaluation(sufficient=False, hypotheses=[], candidates=[], missing_information=[])
    batch = execution.pending_source_batch(empty)
    assert batch[0]["arguments"] == {"path": "domain/service.py", "start_line": 3, "end_line": 4}
    tools.execute("get_source_excerpt", batch[0]["arguments"], tool_call_id="remaining")
    assert execution.pending_source_batch(empty) == []


def test_narrower_answer_cannot_replace_original_hypothesis_question(repo):
    def narrowed(messages):
        value = evaluation(messages, candidate=False)
        value["hypotheses"][0]["question"] = "Is an import declared in domain/service.py?"
        return value

    result, _, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"), narrowed],
        max_iterations=1, max_schema_retries=0)
    assert result.hypotheses[0].question == PLAN["hypotheses"][0]["question"]
    assert result.hypotheses[0].status == "inconclusive"
    assert "boundary_hypothesis_question_changed" in result.hypotheses[0].rationale
