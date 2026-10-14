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
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import BaseModel, ConfigDict, ValidationError

from server.agents.maintainability.architecture_boundary import (
    ArchitectureBoundaryAgent,
    AuditRequest,
    BoundaryConfig,
    Criterion,
)
from server.agents.repository_runtime.context import RepositoryContext
from server.agents.repository_runtime.schemas import ExecutionBudget, RepositoryInput
from server.agents.repository_runtime.tools import RepositoryToolset
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
    return {"sufficient": sufficient, "hypotheses": [dict(PLAN["hypotheses"][0],
             status="confirmed" if sufficient else "inconclusive")],
            "candidates": [finding] if candidate else [],
            "missing_information": [] if sufficient else ["Inspect storage endpoint"]}


def review(status="accepted"):
    return {"findings": [{"finding_id": "f1", "status": status, "rationale": "Rule and inspected import agree.",
                          "severity": "medium", "confidence": 0.8}], "limitations": []}


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


def test_discarded_hypothesis_is_preserved(repo):
    def dismissed(messages):
        value = evaluation(messages, candidate=False)
        value["hypotheses"][0].update(status="discarded", rationale="An intentional adapter was found.")
        return value
    result, _, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"), dismissed,
                               {"findings": [], "limitations": []}])
    assert not result.findings
    assert result.hypotheses[0].status == "discarded"


def test_native_schemas_and_raw_usage_are_used(repo):
    def measured(value):
        return AIMessage(content=json.dumps(value), usage_metadata={
            "input_tokens": 100, "output_tokens": 25, "total_tokens": 125,
        })
    model = NativeStructuredModel([
        measured(PLAN), call(), AIMessage(content="Ready"), evaluation, measured(review()),
    ])
    result = asyncio.run(ArchitectureBoundaryAgent(model).run(toolset(repo), request()))
    assert model.schemas == [("InvestigationPlan", "json_schema", True),
                             ("Evaluation", "json_schema", True), ("Review", "json_schema", True)]
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


def test_gemini_real_adapter_with_offline_transport(repo, monkeypatch):
    """Regression: Gemini rejects max_tokens at invoke time before any HTTP call."""
    from google.genai import types
    from langchain_google_genai import ChatGoogleGenerativeAI

    tools = toolset(repo)
    model = ChatGoogleGenerativeAI(model="gemini-3.5-flash-lite", api_key="offline-test-key", max_tokens=2048)
    requests = []

    async def generate_content(**kwargs):
        requests.append(kwargs)
        turn = len(requests)
        if turn == 2:
            part = types.Part.from_function_call(name="get_source_excerpt", args={
                "path": "domain/service.py", "start_line": 1, "end_line": 4,
            })
        else:
            if turn == 1:
                value = PLAN
            elif turn == 3:
                value = "Ready to evaluate."
            elif turn == 4:
                value = evaluation([ToolMessage(content=json.dumps({
                    "evidence": [r.model_dump() for r in tools.retrieved_evidence],
                }), tool_call_id="offline")])
            elif turn == 5:
                value = review()
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
    assert result.model_calls == len(requests) == 5
    assert result.findings[0].validation_status == "accepted"
    assert result.accounted_tokens == 650
    assert result.estimated_tokens == 0
    assert model.max_output_tokens == 2048  # The caller-owned model was not mutated.
    assert all(item["config"].max_output_tokens == 512 for item in requests)
    assert requests[0]["config"].response_json_schema["title"] == "InvestigationPlan"
    assert requests[3]["config"].response_json_schema["title"] == "Evaluation"
    assert requests[4]["config"].response_json_schema["title"] == "Review"
    assert requests[1]["config"].tools


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
