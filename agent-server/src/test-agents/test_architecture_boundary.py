r"""Ejecutar desde agent-server (PowerShell):

    uv run pytest src/test-agents/test_architecture_boundary.py -q

Alternativa: uv run python src/test-agents/test_architecture_boundary.py
Pruebas offline con StateGraph, ToolNode y herramientas reales sobre fixtures.
El LLM está simulado: no requieren .env, no llaman al proveedor ni generan costes.
"""

import asyncio
import hashlib
import json
import subprocess

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import BaseModel, ConfigDict, ValidationError

from server.agents.maintainability.modularity.architecture_boundary import (
    ArchitectureBoundaryAgent,
    AuditRequest,
    BoundaryConfig,
    Criterion,
)
from server.runtimes.repository.context import RepositoryContext
from server.runtimes.repository.schemas import ExecutionBudget, RepositoryInput
from server.runtimes.repository.tools import RepositoryToolset
from server.services.repository_analysis import RepositoryAnalysisService

PLAN = {"objectives": ["Inspect domain boundary"], "components": ["domain", "storage"],
        "hypotheses": [{"id": "h1", "question": "Does domain depend on storage?",
                        "criterion_id": "domain-rule", "evidence_needed": ["domain source"]}]}


class ScriptedModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.history = []
        self.bound_tools = []

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    async def ainvoke(self, messages, **kwargs):
        self.history.append(messages)
        value = next(self.responses)
        if callable(value):
            value = value(messages)
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, AIMessage) else AIMessage(content=json.dumps(value))


class NativeStructuredModel(ScriptedModel):
    """Mimic LangChain's include_raw contract, including parsing-error envelopes."""

    def __init__(self, responses):
        super().__init__(responses)
        self.schemas = []

    def with_structured_output(self, schema, *, method, include_raw):
        self.schemas.append((schema.__name__, method, include_raw))
        parent = self

        class Structured:
            async def ainvoke(self, messages, **kwargs):
                raw = await parent.ainvoke(messages, **kwargs)
                try:
                    parsed = schema.model_validate(json.loads(raw.content))
                except (ValueError, TypeError) as error:
                    return {"raw": raw, "parsed": None, "parsing_error": error}
                return {"raw": raw, "parsed": parsed, "parsing_error": None}

        return Structured()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "checkout"
    (root / "domain").mkdir(parents=True)
    (root / "storage").mkdir()
    (root / "domain" / "service.py").write_text("from storage.db import save\n\ndef execute():\n    save()\n")
    (root / "storage" / "db.py").write_text("def save():\n    return None\n")
    (root / "README.md").write_text("Domain must not depend on storage.\n")
    return root


def toolset(root, **overrides):
    snapshot = RepositoryAnalysisService().analyze_sync(root)
    budget = ExecutionBudget(**({"max_model_calls": 16, "max_input_tokens_per_call": 50_000,
                                "max_tokens_per_objective": 300_000, "max_total_tokens": 300_000} | overrides))
    return RepositoryToolset(RepositoryContext(snapshot, RepositoryInput(
        snapshot_hash=snapshot.repository.snapshot_hash, budget=budget,
    )), workspace_root=root.parent)


def request():
    return AuditRequest(criteria=[Criterion(id="domain-rule", description="Domain must not import storage.",
                                           origin="explicit", provenance="Caller-supplied project rule")])


def call(name="get_source_excerpt", arguments=None, identifier="call-1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": arguments or
        {"path": "domain/service.py", "start_line": 1, "end_line": 4}, "id": identifier}])


def evaluation(messages, sufficient=True, candidate=True):
    envelopes = [json.loads(m.content) for m in messages if isinstance(m, ToolMessage)]
    ids = [r["id"] for envelope in envelopes for r in envelope.get("evidence", [])]
    finding = {"id": "f1", "title": "Domain imports concrete storage", "description": "Direct storage dependency",
               "criterion_id": "domain-rule", "kind": "violation", "components": ["domain", "storage"],
               "evidence_ids": ids, "justification": "Import contradicts supplied rule.",
               "modularity_impact": "Storage changes affect domain.", "severity": "medium", "confidence": 0.9,
               "recommendation": "Inject a domain-owned abstraction."}
    context = json.loads(messages[1].content)
    scope = list(dict.fromkeys(item["path"] for item in context["evidence"] if item["id"] in ids and item["path"] == "domain/service.py"))
    support = [{"evidence_id": item["id"], "role": "dependency", "observation": "Direct import of storage.db"}
        for item in context["evidence"] if item["id"] in ids and item["path"] == "domain/service.py" and item["kind"] == "source"]
    checks = [{"subject_type": kind, "subject_id": identifier, "claim_kind": "dependency",
        "scope_paths": scope, "support": support} for kind, identifier in
        [("hypothesis", "h1"), *([("candidate", "f1")] if candidate else [])]] if support else []
    return {"sufficient": sufficient, "hypotheses": [dict(PLAN["hypotheses"][0], evidence_ids=ids,
             status="confirmed" if sufficient else "inconclusive")],
            "candidates": [finding] if candidate else [],
            "missing_information": [] if sufficient else ["Inspect storage endpoint"], "claim_checks": checks}


class BoundaryReviewResponse(dict):
    def __call__(self, messages):
        value = json.loads(json.dumps(self))
        context = json.loads(messages[1].content)
        evaluation = context["evaluation"]
        for finding in value["findings"]:
            checks = [item for item in evaluation.get("claim_checks", [])
                if item["subject_type"] == "candidate" and item["subject_id"] == finding["finding_id"]]
            finding.update(scope_supported=True, checked_evidence_ids=list(dict.fromkeys(
                support["evidence_id"] for check in checks for support in check["support"])))
        if "hypotheses" not in value:
            requirements = context.get("boundary_hypothesis_review_requirements", [{
                "hypothesis_id": subject["id"], "expected_checked_evidence_ids": subject["evidence_ids"],
            } for subject in evaluation.get("hypotheses", []) if subject["status"] in {"confirmed", "discarded"}])
            value["hypotheses"] = [{"hypothesis_id": item["hypothesis_id"], "status": "supported",
                "rationale": "The inspected source answers the stated bounded question.",
                "scope_supported": True, "checked_evidence_ids": item["expected_checked_evidence_ids"],
                "unverified_claims": []} for item in requirements]
        return value


def review(status="accepted"):
    return BoundaryReviewResponse({"findings": [{"finding_id": "f1", "status": status, "rationale": "Rule and inspected import agree.",
                           "severity": "medium", "confidence": 0.8}], "limitations": []})


def hypothesis_review():
    response = review()
    response["findings"] = []
    return response


def audit(repo, responses, **config):
    tools = toolset(repo)
    model = ScriptedModel(responses)
    agent = ArchitectureBoundaryAgent(model, BoundaryConfig(**({"max_total_tokens": 300_000} | config)))
    return asyncio.run(agent.run(tools, request())), model, tools


def fingerprints(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def test_graph_plan_native_react_review_and_read_only(repo):
    before = fingerprints(repo)
    result, model, tools = audit(repo, [PLAN, call(), call("find_symbols", {"name": "save"}, "call-2"),
                                      AIMessage(content="Ready to evaluate."), evaluation, review()])
    assert result.plan.hypotheses[0].id == "h1"
    assert len(model.bound_tools) == 7
    assert isinstance(model.history[2][-1], ToolMessage)  # tools -> investigate
    assert result.tool_calls == 2
    assert result.termination_reason == "sufficient_evidence"
    finding = result.findings[0]
    assert finding.validation_status == "accepted"
    assert finding.confidence == 0.8
    assert any(e.path == "domain/service.py" and e.start_line == 1 for e in finding.evidence)
    assert all(e.snapshot_hash == tools.context.input.snapshot_hash for e in finding.evidence)
    assert fingerprints(repo) == before
    assert result.model_dump(mode="json")["findings"]


@pytest.mark.parametrize("verdict", ["accepted", "rejected"])
def test_run_publishes_evidence_and_findings_after_review(repo, verdict):
    from server.blackboard.identity import AuditIdentity
    from server.blackboard.impls.memory import MemoryBlackboard

    board = MemoryBlackboard()
    identity = AuditIdentity(run_id="audit", invocation_id="investigator")
    model = ScriptedModel([PLAN, call(), AIMessage(content="Ready"), evaluation, review(verdict)])
    result = asyncio.run(ArchitectureBoundaryAgent(model, blackboard=board, audit_identity=identity).run(toolset(repo), request()))

    published = board.query_findings(identity.run_id, identity.invocation_id)
    assert len(published) == len(result.findings) == 1
    stored = published[0]
    assert stored.details["validation_status"] == verdict
    assert stored.local_id == result.findings[0].id
    assert all(board.get_evidence(stored.run_id, identifier) is not None for identifier in stored.evidence_ids)
    assert stored.details["investigation"]["termination_reason"] == result.termination_reason
    baseline, baseline_model, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"), evaluation, review(verdict)])
    assert len(model.history) == len(baseline_model.history) == result.model_calls == baseline.model_calls
    assert result.tool_calls == baseline.tool_calls
    assert result.termination_reason == baseline.termination_reason


def test_reinvestigation_uses_missing_information(repo):
    result, model, _ = audit(repo, [PLAN, call(), AIMessage(content="Evaluate"),
        lambda m: evaluation(m, sufficient=False, candidate=False),
        call("get_source_excerpt", {"path": "storage/db.py", "start_line": 1, "end_line": 2}, "call-2"),
        AIMessage(content="Ready"), evaluation, review()])
    assert result.iterations == 2
    assert "Inspect storage endpoint" in model.history[4][1].content
    assert result.findings[0].validation_status == "accepted"


@pytest.mark.parametrize("limit, expected", [("iterations", "iteration_limit"), ("tools", "tool_call_limit"),
                                            ("models", "model_call_limit")])
def test_limits_preserve_inconclusive_hypotheses(repo, limit, expected):
    config = {"max_iterations": 1} if limit == "iterations" else {"max_tool_calls": 1} if limit == "tools" else {"max_model_calls": 5}
    responses = [PLAN, call()]
    if limit != "tools":
        responses.append(AIMessage(content="Evaluate"))
    responses += [lambda m: evaluation(m, False, False), {"findings": [], "limitations": []}]
    result, _, _ = audit(repo, responses, **config)
    assert result.termination_reason == expected
    assert result.hypotheses[0].status == "inconclusive"
    assert result.missing_information


@pytest.mark.parametrize("status", ["rejected", "insufficient_evidence"])
def test_critical_review_can_reject_candidates(repo, status):
    result, _, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"), evaluation, review(status)])
    assert result.findings[0].validation_status == status


def test_fabricated_evidence_cannot_be_accepted(repo):
    def forged(messages):
        value = evaluation(messages)
        value["candidates"][0]["evidence_ids"] = ["invented"]
        return value
    result, _, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"), forged, review()])
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert result.findings[0].evidence == []


def test_inferred_criterion_cannot_support_violation(repo):
    model = ScriptedModel([PLAN, call(), AIMessage(content="Ready"), evaluation, review()])
    criteria = request().criteria[0].model_copy(update={"origin": "inferred"})
    result = asyncio.run(ArchitectureBoundaryAgent(model).run(toolset(repo), AuditRequest(criteria=[criteria])))
    assert result.findings[0].validation_status == "insufficient_evidence"


def test_zero_tool_allowance_and_provider_failure(repo):
    result, _, _ = audit(repo, [PLAN, lambda m: evaluation(m, False, False),
                               {"findings": [], "limitations": []}], max_tool_calls=0)
    assert result.tool_calls == 0
    assert result.termination_reason == "tool_call_limit"
    failed, _, _ = audit(repo, [RuntimeError("offline")])
    assert failed.termination_reason == "model_or_schema_error"
    assert not failed.findings
    assert failed.estimated_tokens > 0


def test_repository_tools_reject_traversal(repo):
    result, _, tools = audit(repo, [PLAN, call(arguments={"path": "../secret.py"}),
        AIMessage(content="Insufficient"), lambda m: evaluation(m, False, False),
        {"findings": [], "limitations": []}], max_iterations=1)
    assert tools.retrieved_evidence == ()
    assert not result.findings


def test_token_limit_returns_valid_partial_result(repo):
    result, _, _ = audit(repo, [], max_total_tokens=1000)
    assert result.termination_reason == "token_limit"
    assert result.model_calls == 0


def test_parallel_tool_batch_is_bounded(repo):
    batch = AIMessage(content="", tool_calls=[
        {"name": "list_files", "args": {}, "id": f"c{i}"} for i in range(5)])
    result, _, _ = audit(repo, [PLAN, batch, lambda m: evaluation(m, False, False),
                               {"findings": [], "limitations": []}], max_tool_calls=2)
    assert result.tool_calls == 2
    assert result.termination_reason == "tool_call_limit"


@pytest.mark.parametrize("dirty", [False, True])
def test_citations_belong_to_commit_not_only_checkout(repo, dirty):
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True)
    git("init")
    git("-c", "core.autocrlf=false", "add", ".")
    git("-c", "user.name=Offline Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture")
    if dirty:
        with (repo / "domain" / "service.py").open("a") as stream:
            stream.write("# uncommitted evidence\n")
    before = fingerprints(repo)
    result, _, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"), evaluation, review()])
    assert result.commit
    assert result.findings[0].validation_status == ("insufficient_evidence" if dirty else "accepted")
    assert result.findings[0].evidence[0].commit == (None if dirty else result.commit)
    if dirty:
        assert "commit_blob_mismatch" in result.findings[0].review_rationale
        assert result.termination_reason == "provenance_unverifiable"
        assert result.model_calls == 5 and result.iterations == 1
        assert result.hypotheses[0].status == "inconclusive"
    assert fingerprints(repo) == before


def test_crlf_checkout_is_audited_and_published_with_explicit_commit_equivalence(repo):
    from server.blackboard.identity import AuditIdentity
    from server.blackboard.impls.memory import MemoryBlackboard

    path = repo / "domain" / "service.py"
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True)
    git("init")
    git("-c", "core.autocrlf=false", "add", ".")
    git("-c", "user.name=Offline Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture")
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    retained_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    before = fingerprints(repo)
    board = MemoryBlackboard()
    identity = AuditIdentity(run_id="crlf-audit", invocation_id="boundary")
    model = NativeStructuredModel([PLAN, call(), AIMessage(content="Ready"), evaluation, review()])
    agent = ArchitectureBoundaryAgent(model, blackboard=board, audit_identity=identity)
    result = asyncio.run(agent.run(toolset(repo), request()))
    assert result.termination_reason == "sufficient_evidence" and result.model_calls == 5
    assert result.findings[0].validation_status == "accepted"
    reference = result.findings[0].evidence[0]
    assert reference.commit == result.commit
    assert reference.commit_verification == "line_endings_equivalent"
    assert reference.content_hash == retained_hash
    assert reference.git_blob_id == git("rev-parse", f"{result.commit}:domain/service.py").stdout.decode().strip()
    published = board.query_evidence("crlf-audit")
    assert published[0].commit_verification == "line_endings_equivalent"
    assert published[0].git_blob_id == reference.git_blob_id
    assert fingerprints(repo) == before


def test_context_exhaustion_and_malformed_review_fail_closed(repo):
    result, _, _ = audit(repo, [PLAN], max_context_characters=4000)
    assert result.termination_reason == "context_limit"
    assert not result.findings
    result, _, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"), evaluation,
                               {"findings": [], "limitations": []}])
    assert result.findings[0].validation_status == "insufficient_evidence"


def test_metadata_alone_cannot_prove_violation(repo):
    result, _, _ = audit(repo, [PLAN, call("list_files", {"limit": 2}), AIMessage(content="Ready"),
                               evaluation, review()])
    assert result.findings[0].validation_status == "insufficient_evidence"


def test_metadata_candidate_returns_to_source_inspection_before_success(repo):
    def cited_evaluation(messages):
        value = evaluation(messages)
        value["hypotheses"][0]["evidence_ids"] = value["candidates"][0]["evidence_ids"]
        if not value["claim_checks"]:
            context = json.loads(messages[1].content)
            ref = next(item for item in context["evidence"] if item["path"] == "domain/service.py")
            value["claim_checks"] = [{"subject_type": kind, "subject_id": identifier, "claim_kind": "dependency",
                "scope_paths": [ref["path"]], "support": [{"evidence_id": ref["id"], "role": "dependency",
                    "observation": "Investigate the declared dependency"}]} for kind, identifier in [("candidate", "f1"), ("hypothesis", "h1")]]
        return value

    result, model, _ = audit(repo, [PLAN,
        call("list_files", {"limit": 2}), AIMessage(content="Ready"), cited_evaluation,
        call(), AIMessage(content="Ready"), cited_evaluation, review()])
    assert result.termination_reason == "sufficient_evidence"
    assert result.iterations == 2 and result.hypotheses[0].status == "confirmed"
    assert result.findings[0].validation_status == "accepted"
    context = json.loads(model.history[4][1].content)
    assert not context["evaluation"]["sufficient"]
    assert any("source_not_inspected" in gap and "get_source_excerpt" in gap for gap in context["missing_information"])
    hypothesis_task = next(task for task in context["evidence_recovery_tasks"] if task["subject_type"] == "hypothesis")
    assert hypothesis_task["id"] == "h1"
    assert hypothesis_task["action"] == "inspect_source_or_correct_citations"
    assert hypothesis_task["paths_to_inspect"]
    assert hypothesis_task["evidence_needed"] == PLAN["hypotheses"][0]["evidence_needed"]
    assert all("snapshot provenance" not in gap for gap in context["missing_information"] if gap.startswith("Hypothesis"))


def test_wrong_hypothesis_citations_reuse_existing_source_without_another_read(repo):
    def hypothesis_only(messages, kind):
        context = json.loads(messages[1].content)
        ids = [record["id"] for record in context["evidence"]
            if record["kind"] == kind and record["path"] == "domain/service.py"]
        assert ids
        return {"sufficient": True, "hypotheses": [dict(PLAN["hypotheses"][0],
            status="confirmed", evidence_ids=ids, rationale="Inspected the scoped import.")],
            "candidates": [], "missing_information": [], "claim_checks": [{
                "subject_type": "hypothesis", "subject_id": "h1", "claim_kind": "dependency",
                "scope_paths": ["domain/service.py"], "support": [{"evidence_id": ids[0],
                    "role": "dependency", "observation": "Direct import of storage.db"}],
            }] if kind == "source" else []}

    result, model, _ = audit(repo, [PLAN, call("list_files", {"limit": 2}), call(),
        AIMessage(content="Ready"), lambda messages: hypothesis_only(messages, "metadata"),
        AIMessage(content="Ready"), lambda messages: hypothesis_only(messages, "source"),
        hypothesis_review()])
    assert result.termination_reason == "sufficient_evidence"
    assert result.hypotheses[0].status == "confirmed"
    assert result.iterations == 2 and result.tool_calls == 2
    # A resolved hypothesis citing only metadata cannot support a claim check, and
    # demanding one anyway was unsatisfiable; it must return to investigation instead.
    assert not any("boundary_check_structure_invalid" in issue for issue in result.limitations)
    context = json.loads(model.history[5][1].content)
    assert any("boundary_no_delivered_source_evidence" in gap for gap in context["missing_information"])
    task = next(item for item in context["evidence_recovery_tasks"] if item["id"] == "h1")
    assert task["action"] == "inspect_source_or_correct_citations"
    assert task["paths_to_inspect"] == []  # the cited path was already read as source
    assert task["available_source_evidence_ids"]  # reuse it instead of reading again
    assert result.tool_calls == 2


def test_invalid_source_cannot_confirm_hypotheses_or_claim_sufficiency_at_finalization(repo):
    tools = toolset(repo)
    execution = ArchitectureBoundaryAgent.execution_type(ScriptedModel([]), BoundaryConfig(), tools, request())
    state = execution.initial_state()
    state.update(hypotheses=[execution.evaluation_schema.model_validate({
        "sufficient": True, "hypotheses": [dict(PLAN["hypotheses"][0], status="confirmed", evidence_ids=["unknown"])],
        "candidates": [], "missing_information": [],
    }).hypotheses[0]], termination_reason="sufficient_evidence")
    result = execution.finalize(state)["result"]
    assert result.termination_reason == "evidence_validation_failed"
    assert result.hypotheses[0].status == "inconclusive"
    assert "unknown_evidence_ids" in result.hypotheses[0].rationale
    assert result.missing_information


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("problem", ["missing", "duplicate", "unknown"])
def test_semantic_review_errors_are_corrected_without_accepting_invalid_reviews(repo, native, problem):
    invalid = review()
    if problem == "missing":
        invalid["findings"] = []
    elif problem == "duplicate":
        invalid["findings"] *= 2
    else:
        invalid["findings"][0]["finding_id"] = "PRIVATE_UNKNOWN_CANDIDATE"
    model = (NativeStructuredModel if native else ScriptedModel)([
        PLAN, call(), AIMessage(content="Ready"), evaluation, invalid, review("rejected"),
    ])
    result = asyncio.run(ArchitectureBoundaryAgent(model).run(toolset(repo), request()))
    assert result.termination_reason == "sufficient_evidence"
    assert result.findings[0].validation_status == ("accepted" if problem == "duplicate" else "rejected")
    issues = result.critical_review.validation_issues
    code = {"missing": "review_missing_candidate", "duplicate": "review_duplicate_candidate_collapsed", "unknown": "review_unknown_candidates"}[problem]
    assert any(code in issue for issue in issues)
    if problem != "duplicate":
        context = json.loads(model.history[-1][1].content)
        assert context["boundary_review_requirements"][0]["candidate_id"] == "f1"
        assert context["prior_critical_review"]["validation_issues"]
        assert "PRIVATE_UNKNOWN_CANDIDATE" not in json.dumps(context)


def test_review_correction_is_reserved_before_investigation_exhausts_calls(repo):
    result, model, _ = audit(repo, [PLAN,
        *[call(identifier=f"read-{i}") for i in range(4)], evaluation,
        {"findings": [], "limitations": []}, review()], max_model_calls=8)
    assert result.model_calls == len(model.history) == 8
    assert result.termination_reason == "sufficient_evidence"
    assert result.findings[0].validation_status == "accepted"


def test_repeated_semantic_review_failure_retains_partial_results(repo):
    invalid = {"findings": [], "limitations": []}
    result, model, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"), evaluation, invalid, invalid])
    assert result.termination_reason == "evidence_validation_failed"
    assert result.model_calls == len(model.history) == 6
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert result.findings[0].evidence
    assert result.critical_review is not None


def test_discarded_hypothesis_is_preserved(repo):
    def dismissed(messages):
        value = evaluation(messages, candidate=False)
        value["hypotheses"][0].update(status="discarded", rationale="An intentional adapter was found.")
        return value
    result, _, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"), dismissed,
                               hypothesis_review()])
    assert not result.findings
    assert result.hypotheses[0].status == "discarded"


def test_native_schemas_and_raw_usage_are_used(repo):
    def measured(value):
        return AIMessage(content=json.dumps(value), usage_metadata={
            "input_tokens": 100, "output_tokens": 25, "total_tokens": 125,
        })
    model = NativeStructuredModel([
        measured(PLAN), call(), AIMessage(content="Ready"), evaluation, lambda messages: measured(review()(messages)),
    ])
    result = asyncio.run(ArchitectureBoundaryAgent(model).run(toolset(repo), request()))
    assert model.schemas == [("InvestigationPlan", "json_schema", True),
                             ("BoundaryEvaluation", "json_schema", True), ("BoundaryReview", "json_schema", True)]
    assert result.plan is not None
    assert result.findings[0].validation_status == "accepted"
    assert result.accounted_tokens - result.estimated_tokens == 250


@pytest.mark.parametrize("native", [False, True])
def test_invalid_plan_is_corrected_once_without_leaking_payload(repo, native):
    invalid = {"objectives": "PRIVATE_SOURCE_OR_KEY", "hypotheses": [],
               "PRIVATE_UNKNOWN_FIELD": "PRIVATE_VALUE"}
    model_type = NativeStructuredModel if native else ScriptedModel
    model = model_type([invalid, PLAN, call(), AIMessage(content="Ready"), evaluation, review()])
    result = asyncio.run(ArchitectureBoundaryAgent(model).run(toolset(repo), request()))
    assert result.plan is not None
    assert result.findings[0].validation_status == "accepted"
    assert result.model_calls == 6
    assert any("components: missing" in issue and "objectives: list_type" in issue
               for issue in result.limitations)
    assert "PRIVATE" not in json.dumps(result.model_dump())
    assert "PRIVATE" not in model.history[1][-1].content
    assert "failed validation" in model.history[1][-1].content


def test_repeated_schema_failure_is_bounded_and_visible(repo):
    result, model, _ = audit(repo, [{"objectives": []}, {"objectives": []}])
    assert result.model_calls == len(model.history) == 2
    assert result.plan is None
    assert result.tool_calls == 0
    assert result.termination_reason == "model_or_schema_error"
    assert any("attempt 2/2" in issue and "hypotheses: missing" in issue for issue in result.limitations)


def test_schema_retry_can_be_disabled_or_limited_by_remaining_calls(repo):
    result, model, _ = audit(repo, [{}], max_schema_retries=0)
    assert len(model.history) == 1
    assert result.termination_reason == "model_or_schema_error"
    result, model, _ = audit(repo, [{}], max_model_calls=4)
    assert result.model_calls == len(model.history) == 1
    assert result.termination_reason == "model_call_limit"


def test_evaluation_and_review_can_correct_invalid_schema(repo):
    result, _, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"),
                               {"sufficient": True}, evaluation, {"findings": "invalid"}, review()])
    assert result.model_calls == 7
    assert result.findings[0].validation_status == "accepted"
    assert any("evaluate_evidence: response_schema" in item for item in result.limitations)
    assert any("review_findings: response_schema" in item for item in result.limitations)


def test_provider_validation_is_distinguished_from_output_validation(repo):
    class ProviderConfig(BaseModel):
        model_config = ConfigDict(extra="forbid")

    try:
        ProviderConfig.model_validate({"max_tokens": "PRIVATE_CREDENTIAL"})
    except ValidationError as error:
        result, model, _ = audit(repo, [error])
    assert len(model.history) == 1  # Do not retry a request/configuration failure.
    assert any("provider_request: ValidationError (max_tokens: extra_forbidden)" in item
               for item in result.limitations)
    assert "PRIVATE_CREDENTIAL" not in json.dumps(result.model_dump())


def test_truncated_json_diagnostic_and_markdown_fallback(repo):
    truncated = AIMessage(content='{"objectives": [', response_metadata={"finish_reason": "MAX_TOKENS"})
    result, _, _ = audit(repo, [truncated, PLAN, call(), AIMessage(content="Ready"), evaluation, review()])
    assert result.plan is not None
    assert any("JSONDecodeError" in item and "output_token_limit_reached" in item for item in result.limitations)
    fenced = AIMessage(content="```json\n" + json.dumps(PLAN) + "\n```")
    result, _, _ = audit(repo, [fenced, call(), AIMessage(content="Ready"), evaluation, review()])
    assert result.findings[0].validation_status == "accepted"


@pytest.mark.parametrize("reinvestigate", [False, True])
def test_gemini_real_adapter_with_offline_transport(repo, monkeypatch, reinvestigate):
    """Exercise real Gemini request preparation, including resumed investigation."""
    from google.genai import types
    from langchain_google_genai import ChatGoogleGenerativeAI

    tools = toolset(repo)
    model = ChatGoogleGenerativeAI(model="gemini-3.5-flash-lite", api_key="offline-test-key", max_tokens=2048)
    requests = []

    evaluated = []
    async def generate_content(**kwargs):
        requests.append(kwargs)
        turn = len(requests)
        phase = turn - 3 if reinvestigate and turn > 4 else turn
        schema = kwargs["config"].response_json_schema
        if schema:
            encoded = json.dumps(schema)
            assert all(hint not in encoded for hint in ("maxItems", "minItems", "maxLength", "minLength"))
            assert schema["additionalProperties"] is False
            assert schema["required"]
        if phase == 2:
            part = types.Part.from_function_call(name="get_source_excerpt", args={
                "path": "storage/db.py" if turn == 5 else "domain/service.py",
                "start_line": 1, "end_line": 2 if turn == 5 else 4,
            })
        else:
            if phase == 1:
                value = PLAN
            elif phase == 3:
                value = "Ready to evaluate."
            elif phase == 4:
                paths = {source.id: source.path for source in tools.accessible_snapshot.files}
                context = {"evidence": [{**r.model_dump(), "path": paths[r.file_id]} for r in tools.retrieved_evidence]}
                value = evaluation([HumanMessage(content=""), HumanMessage(content=json.dumps(context)), ToolMessage(content=json.dumps({
                    "evidence": [r.model_dump() for r in tools.retrieved_evidence],
                }), tool_call_id="offline")], sufficient=not (reinvestigate and turn == 4))
                evaluated.append(value)
            elif phase == 5:
                value = review()([HumanMessage(content=""), HumanMessage(content=json.dumps({"evaluation": evaluated[-1]}))])
            else:
                raise AssertionError("Unexpected extra provider call")
            part = types.Part(text=json.dumps(value) if isinstance(value, dict) else value)
        return types.GenerateContentResponse(
            candidates=[types.Candidate(content=types.Content(role="model", parts=[part]), finish_reason="STOP")],
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=100, candidates_token_count=30, total_token_count=130,
            ),
        )

    monkeypatch.setattr(model.async_client.models, "generate_content", generate_content)
    result = asyncio.run(ArchitectureBoundaryAgent(
        model, BoundaryConfig(max_output_tokens=512),
    ).run(tools, request()))
    assert result.plan is not None, result.limitations
    assert result.model_calls == len(requests) == (8 if reinvestigate else 5)
    assert result.iterations == (2 if reinvestigate else 1)
    assert result.findings[0].validation_status == "accepted"
    assert result.accounted_tokens == 130 * len(requests)
    assert result.estimated_tokens == 0
    assert model.max_output_tokens == 2048  # The caller-owned model was not mutated.
    assert all(item["config"].max_output_tokens == 512 for item in requests)
    assert requests[0]["config"].response_json_schema["title"] == "InvestigationPlan"
    assert requests[3]["config"].response_json_schema["title"] == "BoundaryEvaluation"
    assert requests[-1]["config"].response_json_schema["title"] == "BoundaryReview"
    evaluation_schema = requests[3]["config"].response_json_schema
    assert evaluation_schema["$defs"]["BoundaryClaimCheck"]["properties"]["claim_kind"]["enum"]
    assert "support" in evaluation_schema["$defs"]["BoundaryClaimCheck"]["required"]
    assert requests[1]["config"].tools
    if reinvestigate:
        assert requests[4]["contents"][-1].role == "user"
        assert "Continue the investigation" in requests[4]["contents"][-1].parts[-1].text
        assert requests[5]["contents"][-1].parts[-1].function_response is not None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
