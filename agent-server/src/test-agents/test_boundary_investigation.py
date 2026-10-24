"""Regression checks for discovery, coverage, progress and provider context retention."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from google.genai import errors
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
    BoundaryConfig,
)
from server.agents.maintainability.modularity.architecture_boundary.discovery import (
    BoundaryDiscovery,
)
from server.agents.maintainability.modularity.architecture_boundary.execution import (
    BoundaryExecution,
)
from server.agents.maintainability.modularity.architecture_boundary.support import (
    supports_role,
)
from server.runtimes.investigation.messages import compact_tool_history

pytest_plugins = ["test_architecture_boundary"]


def test_discovery_exposes_unvisited_boundaries_without_creating_evidence(repo):
    tools = toolset(repo)
    discovery = BoundaryDiscovery(tools.accessible_snapshot)
    coverage = discovery.coverage([])
    assert coverage["boundary_count"] >= 1
    assert any("storage/db.py" in item["uninspected_paths"] for item in coverage["boundaries"])
    assert not tools.retrieved_evidence
    result, model, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"), evaluation, review()])
    assert result.investigation_coverage["inspected_file_count"] == 1
    assert json.loads(model.history[0][1].content)["boundary_coverage"]["boundary_count"] >= 1


def test_cycle_claim_cannot_override_observed_cycle_with_complete_flag(repo):
    (repo / "storage" / "db.py").write_text("from domain.service import execute\n\ndef save():\n    return execute()\n")

    def no_cycles(messages):
        value = evaluation(messages)
        context = json.loads(messages[1].content)
        sources = [item for item in context["evidence"] if item["kind"] == "source"]
        for check in value["claim_checks"]:
            check.update(claim_kind="absence_of_cycles", coverage_complete=True,
                scope_paths=[item["path"] for item in sources],
                support=[{"evidence_id": item["id"], "role": "dependency", "observation": "Import inspected"}
                    for item in sources])
        return value

    result, _, _ = audit(repo, [PLAN, call(),
        call(arguments={"path": "storage/db.py", "start_line": 1, "end_line": 4}, identifier="db"),
        AIMessage(content="Ready"), no_cycles, review()], max_iterations=1)
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert "boundary_indexed_cycle_observed" in result.findings[0].validation_issues


def test_isolation_requires_support_for_known_third_endpoint(repo):
    (repo / "client.py").write_text("from storage.db import save\n\ndef run():\n    save()\n")

    def isolation(messages):
        value = evaluation(messages)
        sources = [item for item in json.loads(messages[1].content)["evidence"] if item["kind"] == "source"]
        for check in value["claim_checks"]:
            check.update(claim_kind="isolation", coverage_complete=True,
                scope_paths=[item["path"] for item in sources],
                support=[{"evidence_id": item["id"], "role": role, "observation": "Source inspected"}
                    for item in sources for role in ("implementation", "usage", "composition")])
        return value

    result, _, _ = audit(repo, [PLAN, call(),
        call(arguments={"path": "storage/db.py", "start_line": 1, "end_line": 2}, identifier="db"),
        AIMessage(content="Ready"), isolation, review()], max_iterations=1)
    assert "boundary_related_endpoints_not_supported" in result.findings[0].validation_issues


def test_repeated_nonempty_investigation_stops_and_retains_closing_review(repo):
    result, _, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"),
        lambda messages: evaluation(messages, sufficient=False),
        call(identifier="repeat-1"), call(identifier="repeat-2"), call(identifier="repeat-3"), review()],
        max_iterations=10)
    assert result.termination_reason == "no_investigation_progress"
    assert result.critical_review is not None
    assert result.evidence


def test_conceptual_question_gets_actionable_module_level_configuration_read(repo):
    (repo / "database_config.py").write_text('DATABASE_URL = "sqlite:///shared.db"\n')
    plan = {**PLAN, "hypotheses": [{"id": "h1", "question": "Is database configuration shared?",
        "evidence_needed": ["Inspect database construction and configuration"]}]}

    def unresolved(messages):
        return {"sufficient": False, "hypotheses": [{**plan["hypotheses"][0], "status": "inconclusive"}],
            "candidates": [], "claim_checks": [], "missing_information": ["Inspect database configuration"]}

    result, model, _ = audit(repo, [plan, AIMessage(content="Need database configuration"),
        unresolved, AIMessage(content="Configuration still missing"), unresolved], max_iterations=2)
    tasks = json.loads(model.history[3][1].content)["evidence_recovery_tasks"]
    reads = next(item for item in tasks if item["id"] == "h1")["next_source_reads"]
    assert reads[0]["arguments"]["path"] == "database_config.py"
    assert result.tool_calls == 2  # One bounded recovery batch uses the normal, charged ToolNode.
    assert any(ref.path == "database_config.py" for ref in result.evidence)
    assert result.hypotheses[0].status == "inconclusive"  # Retrieval is not a finding or a resolved hypothesis.


def test_compaction_preserves_cited_source_and_native_tool_pairs():
    messages = []
    for index in range(4):
        messages.extend([call(identifier=str(index)), ToolMessage(tool_call_id=str(index),
            content=json.dumps({"evidence": [{"id": str(index)}], "source": "x" * 5000}))])
    compacted = compact_tool_history(messages, 1000, {"0"})
    assert compacted[1].content == messages[1].content
    assert json.loads(compacted[3].content)["history_compacted"] is True
    assert len(compacted) == len(messages)
    assert compacted[-1].content == messages[-1].content
    assert "history_compacted" not in messages[3].content


def test_configuration_and_typescript_module_extensions_have_bounded_support():
    for path, content in [("config.json", '{"database": "shared"}'),
                          ("config.yaml", "database: shared"),
                          ("client.mts", "export const client = createClient();")]:
        source = SimpleNamespace(path=path, content=content)
        reference = SimpleNamespace(kind="source", start_line=1, end_line=1)
        assert supports_role(source, reference, "declaration")
        if path.endswith("yaml"):
            assert not supports_role(source, reference, "implementation")


def test_token_headroom_stops_exploration_but_preserves_critical_review(repo):
    class MeteredModel(ScriptedModel):
        async def ainvoke(self, messages, **kwargs):
            response = await super().ainvoke(messages, **kwargs)
            return response.model_copy(update={"usage_metadata": {
                "input_tokens": 10_000, "output_tokens": 1, "total_tokens": 10_001}})

    model = MeteredModel([PLAN, call(), AIMessage(content="Ready"),
        lambda messages: evaluation(messages, sufficient=False), review()])
    result = asyncio.run(ArchitectureBoundaryAgent(model, BoundaryConfig(
        max_total_tokens=60_000, provider_rate_limits={"requests_per_minute": None, "tokens_per_minute": None},
    )).run(toolset(repo), request()))
    assert result.termination_reason == "token_limit"
    assert result.critical_review is not None
    assert result.findings[0].validation_status == "accepted"
    assert result.hypotheses[0].status == "inconclusive"
    assert result.missing_information
    assert result.accounted_tokens == 50_005
    assert result.model_calls == 5
    assert any("token_budget_reserved_for_closing" in item and "effective_limit=60000" in item
        for item in result.limitations)


@pytest.mark.parametrize("candidate", [False, True])
def test_new_evidence_survives_a_blocked_evaluation_and_closing_failure(repo, monkeypatch, candidate):
    original = BoundaryExecution.call
    evaluations = 0
    active = None

    async def block_second_evaluation(self, node, state, *args, **kwargs):
        nonlocal evaluations, active
        active = self
        if node == "evaluate_evidence":
            evaluations += 1
            if evaluations == 2:
                self.stop = "token_limit"
                return None
        return await original(self, node, state, *args, **kwargs)

    monkeypatch.setattr(BoundaryExecution, "call", block_second_evaluation)
    responses = [PLAN, call(), AIMessage(content="Ready"),
        lambda messages: evaluation(messages, sufficient=False, candidate=candidate),
        call(arguments={"path": "storage/db.py", "start_line": 1, "end_line": 2}, identifier="new-evidence"),
        AIMessage(content="Ready")]
    if candidate:
        def gateway_timeout(messages):
            active.token_limit = active.tokens + 1
            return errors.ServerError(504, response_json={"error": {"code": 504, "message": "Gateway timeout"}})
        responses.append(gateway_timeout)
    result, model, _ = audit(repo, responses)
    assert result.termination_reason == "token_limit"
    assert result.evaluation_evidence_status == "stale"
    refs = {item.id: item for item in result.evidence}
    assert [refs[item].path for item in result.pending_evaluation_evidence_ids] == ["storage/db.py"]
    assert [refs[item].path for item in result.evaluated_evidence_ids] == ["domain/service.py"]
    assert set(refs) == set(result.pending_evaluation_evidence_ids + result.evaluated_evidence_ids)
    assert result.critical_review is None and result.model_calls == len(model.history) == (7 if candidate else 6)
    if candidate:
        assert result.deferred_stages[0].reason == "provider_retry_token_limit"
        assert result.deferred_stages[0].http_status == 504 and result.deferred_stages[0].attempts == 1
        assert result.findings[0].validation_status == "insufficient_evidence"
    else:
        assert not result.deferred_stages
    assert any("Prior conclusions do not evaluate these excerpts" in item for item in result.missing_information)
    assert result.hypotheses[0].status == "inconclusive"


def test_model_tool_envelope_retains_source_without_repeating_provenance(repo):
    result, model, tools = audit(repo, [PLAN, call(), AIMessage(content="Ready"), evaluation, review()])
    response = next(item for item in model.history[2] if isinstance(item, ToolMessage))
    payload = json.loads(response.content)
    assert "from storage.db import save" in json.dumps(payload["data"])
    assert "budget_usage" not in payload
    assert all("snapshot_hash" not in item and "content_hash" not in item for item in payload["evidence"])
    assert result.evidence[0].content_hash == tools.retrieved_evidence[0].content_hash
    context = json.loads(model.history[-1][1].content)
    assert "boundary_coverage" not in context
    assert "hypotheses" not in context["evaluation"]
    assert context["hypotheses"]


def test_structured_nodes_drop_inventory_payload_but_keep_cited_source():
    source = ToolMessage(tool_call_id="read", content=json.dumps({
        "evidence": [{"id": "source", "kind": "source"}], "data": {"content": "save()"}}))
    inventory = ToolMessage(tool_call_id="list", content=json.dumps({
        "evidence": [{"id": "metadata", "kind": "metadata"}], "data": {"items": ["file"] * 500}}))
    messages = [call(identifier="read"), source, call(identifier="list"), inventory]
    compacted = compact_tool_history(messages, 100_000, {"source"}, compact_metadata=True)
    assert compacted[1].content == source.content
    assert json.loads(compacted[3].content)["history_compacted"]
    assert "items" in json.loads(inventory.content)["data"]


def test_pending_evidence_evaluation_can_use_the_stale_review_reserve(repo, monkeypatch):
    original = BoundaryExecution.closing_token_reserve
    reserves = []

    def closing_reserve(self, node, request_reserve):
        if node == "evaluate_evidence" and self._prioritize_evaluation:
            # Enough for reevaluation, but not reevaluation plus a review reservation.
            self.tokens = self.token_limit - request_reserve
        reserve = original(self, node, request_reserve)
        if node == "evaluate_evidence":
            reserves.append(reserve)
        return reserve

    monkeypatch.setattr(BoundaryExecution, "closing_token_reserve", closing_reserve)
    result, _, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"),
        lambda messages: evaluation(messages, sufficient=False, candidate=False),
        call(arguments={"path": "storage/db.py", "start_line": 1, "end_line": 2}, identifier="new-evidence"),
        AIMessage(content="Ready"), lambda messages: evaluation(messages, candidate=False)])
    assert reserves[0] > 0 and reserves[1] == 0
    assert result.evaluation_evidence_status == "current"
    assert not result.pending_evaluation_evidence_ids
    assert result.model_calls == 7
    assert result.accounted_tokens <= 300_000
    assert result.critical_review is None


@pytest.mark.parametrize("repair_outcome", ["success", "provider_error", "invalid_structure"])
def test_delivered_citation_repair_avoids_another_investigation_and_preserves_valid_work(repo, repair_outcome):
    def inconsistent(messages):
        value = evaluation(messages)
        refs = json.loads(messages[1].content)["evidence"]
        other = next(item["id"] for item in refs if item["path"] == "storage/db.py")
        value["candidates"][0].update(title="Retained second evaluation", evidence_ids=[other])
        return value

    def repaired(messages):
        assert "Repair data (not instructions):" in messages[-1].content
        assert "boundary_support_not_cited" in messages[-1].content
        value = evaluation(messages)
        value["candidates"][0]["title"] = "Repaired second evaluation"
        return value

    def malformed(messages):
        value = evaluation(messages)
        value["claim_checks"] = []
        return value

    responses = [PLAN, call(), AIMessage(content="Ready"),
        lambda messages: evaluation(messages, sufficient=False),
        call(arguments={"path": "storage/db.py", "start_line": 1, "end_line": 2}, identifier="new"),
        AIMessage(content="Ready"), inconsistent]
    if repair_outcome == "success":
        responses.extend([repaired, review()])
    elif repair_outcome == "provider_error":
        responses.append(RuntimeError("Provider unavailable during repair"))
    else:
        responses.extend([malformed, malformed, review()])
    result, model, _ = audit(repo, responses, max_schema_retries=1, max_schema_recovery_attempts=0)
    assert result.iterations == 2 and result.tool_calls == 2
    assert result.evaluation_evidence_status == "current"
    assert result.pending_evaluation_evidence_ids == []
    assert result.model_calls == len(model.history) == len(responses)
    finding = result.findings[0]
    if repair_outcome == "success":
        assert finding.title == "Repaired second evaluation"
        assert finding.validation_status == "accepted"
        assert result.termination_reason == "sufficient_evidence"
    else:
        assert finding.title == "Retained second evaluation"
        assert finding.validation_status == "insufficient_evidence"
        assert result.termination_reason != "sufficient_evidence"
        if repair_outcome == "invalid_structure":
            assert result.failed_evaluation_attempt is not None
            assert result.failed_evaluation_attempt.claim_checks == []
            assert result.evaluation_attempt_issues


def test_initial_evaluation_can_repair_citations_from_delivered_source_without_new_reads(repo):
    def wrong_scope_citation(messages):
        value = evaluation(messages)
        refs = json.loads(messages[1].content)["evidence"]
        header = next(item["id"] for item in refs if item["start_line"] == 1)
        body = next(item["id"] for item in refs if item["start_line"] == 3)
        value["candidates"][0]["evidence_ids"] = [body]
        for check in value["claim_checks"]:
            check["support"] = [{"evidence_id": header, "role": "dependency", "observation": "Imports storage.db"}]
        return value

    def repair(messages):
        assert "Repair data (not instructions):" in messages[-1].content
        value = wrong_scope_citation(messages)
        ref = next(item["id"] for item in json.loads(messages[1].content)["evidence"] if item["start_line"] == 1)
        value["candidates"][0]["evidence_ids"] = [ref]
        return value

    result, model, _ = audit(repo, [PLAN,
        call(arguments={"path": "domain/service.py", "start_line": 1, "end_line": 1}),
        call(arguments={"path": "domain/service.py", "start_line": 3, "end_line": 4}, identifier="body"),
        AIMessage(content="Ready"), wrong_scope_citation, repair, review()])
    assert result.iterations == 1 and result.tool_calls == 2
    assert result.model_calls == len(model.history) == 7
    assert result.findings[0].validation_status == "accepted"
    assert result.termination_reason == "sufficient_evidence"


def test_criterion_and_boundary_diagnostics_are_both_retained(repo):
    from server.agents.schemes.base import Criterion

    def invalid(messages):
        value = evaluation(messages)
        check = next(item for item in value["claim_checks"] if item["subject_type"] == "candidate")
        check["scope_paths"].append("storage/db.py")
        return value

    audit_request = request().model_copy(update={"criteria": [Criterion(id="domain-rule",
        description="Separate responsibilities", origin="design_principle", provenance="Auditor heuristic")]})
    model = ScriptedModel([PLAN, call(), AIMessage(content="Ready"), invalid, review()])
    result = asyncio.run(ArchitectureBoundaryAgent(model, BoundaryConfig(max_iterations=1,
        max_schema_retries=0)).run(toolset(repo), audit_request))
    finding = result.findings[0]
    assert {"violation_requires_explicit_criterion", "boundary_scope_not_inspected"} <= set(finding.validation_issues)
    assert "violation_requires_explicit_criterion" in finding.review_rationale
    assert "boundary_scope_not_inspected" in finding.review_rationale
    assert finding.validation_status == "insufficient_evidence"


def test_prior_semantic_review_is_not_reused_for_a_changed_conclusion_after_provider_failure(repo):
    def incomplete_candidate_review(messages):
        value = review()(messages)
        value["findings"][0].update(status="insufficient_evidence", scope_supported=False,
            unverified_claims=["Inspect the target implementation before accepting the candidate."])
        assert value["hypotheses"][0]["status"] == "supported"
        return value

    def changed_conclusion(messages):
        value = evaluation(messages)
        value["hypotheses"][0]["rationale"] = "The intended service layer is bypassed across the system."
        return value

    result, _, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"), evaluation,
        incomplete_candidate_review,
        call(arguments={"path": "storage/db.py", "start_line": 1, "end_line": 2}, identifier="target"),
        AIMessage(content="Ready"), changed_conclusion, RuntimeError("Review provider unavailable")])
    assert result.evaluation_evidence_status == "current"
    assert result.critical_review is None
    assert result.hypotheses[0].status == "inconclusive"
    assert "boundary_hypothesis_semantic_review_missing" in result.hypotheses[0].rationale
    assert result.findings[0].validation_status == "insufficient_evidence"
