r"""From agent-server: uv run pytest src/test-agents/test_abstraction.py -q.

Offline: real LangGraph, ToolNode, indexes and read-only tools; simulated model.
Live (paid): uv run python src/test-agents/run_abstraction.py C:\repos\project
"""

import asyncio
import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from test_architecture_boundary import (
    NativeStructuredModel,
    ScriptedModel,
    fingerprints,
    toolset,
)

from server.agents.maintainability.abstraction import (
    AbstractionAgent,
    AbstractionConfig,
    AbstractionRequest,
    AbstractionResult,
)
from server.agents.maintainability.abstraction.discovery import discover
from server.agents.modularity_runtime.agent import InvestigationExecution
from server.app.tracing_port import NoOpTracingBackend
from server.config.schemas import ModelSettings


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    sources = {
        "policy.py": "class PricePolicy:\n    def total(self, amounts):\n        return sum(amounts)\n",
        "orders.py": "from policy import PricePolicy\ndef order_total(amounts):\n    return PricePolicy().total(amounts)\n",
        "reports.py": "from policy import PricePolicy\ndef report_total(amounts):\n    return PricePolicy().total(amounts)\n",
        "helpers.py": "def normalize(value):\n    return value.strip()\n",
        "wrapper.py": "from helpers import normalize\ndef normalize_value(value):\n    return normalize(value)\n",
        "client.py": "from wrapper import normalize_value\ndef label(value):\n    return normalize_value(value)\n",
        "port.py": "from typing import Protocol\nclass StoragePort(Protocol):\n    def save(self, value): ...\n",
        "adapter.py": "from port import StoragePort\nclass MemoryStorage(StoragePort):\n    def save(self, value):\n        return {'stored': value}\n",
        "checkout.py": "from port import StoragePort\ndef persist(store: StoragePort, value):\n    return store.save(value)\n",
        "duplicate_a.py": "def format_price(amount):\n    return f'{amount:.2f}'\n",
        "duplicate_b.py": "def display_price(amount):\n    return f'{amount:.2f}'\n",
    }
    for path, content in sources.items():
        (root / path).write_text(content, encoding="utf-8")
    return root


def plan():
    return {"objectives": ["Assess reuse tradeoffs"], "components": [], "hypotheses": [{
        "id": "h1", "question": "Does this abstraction justify its indirection?", "criterion_id": "abstraction-reuse"}]}


def reads(root, paths, *, graph=True):
    calls = [{"name": "get_source_excerpt", "args": {"path": path, "start_line": 1,
        "end_line": len((root / path).read_text(encoding="utf-8").splitlines())}, "id": f"source-{i}"}
        for i, path in enumerate(paths)]
    if graph:
        calls.insert(0, {"name": "list_relationships", "args": {"resolution": "internal", "limit": 50}, "id": "relationships"})
    return AIMessage(content="", tool_calls=calls)


def evaluate(messages, *, primary="policy.py", category="useful_abstraction", participants=None,
             finding=True, mutate=None):
    context = json.loads(messages[1].content)
    target = next(c for c in context["abstraction_candidates"] if c["path"] == primary)
    envelopes = [json.loads(m.content) for m in messages if isinstance(m, ToolMessage)]
    references = context["evidence"]
    by_path = {r["path"]: r for r in references if r["kind"] == "source"}
    source_ids = [r["id"] for r in references if r["kind"] == "source"]
    edges = [r for e in envelopes if e.get("tool_name") == "list_relationships" and e.get("data")
             for r in e["data"].get("items", []) if r["kind"] != "contains" and r["target_id"]]
    roles = participants if participants is not None else [("orders.py", "consumer"), ("reports.py", "consumer")]
    related = []
    files = {r["path"]: r["file_id"] for r in references}
    # Missing reads remain missing evidence: no synthetic source IDs are manufactured.
    for path, role in roles:
        if path not in files:
            continue
        primary_file = files.get(primary)
        pair = (primary_file, files[path]) if role in {"delegate", "contract"} else (files[path], primary_file)
        edge = next((r for r in edges if (r["source_id"], r["target_id"]) == pair), None)
        related.append({"component_id": files[path], "role": role, "relationship_id": edge["id"] if edge else None,
            "evidence_ids": [by_path[path]["id"]] if path in by_path else [],
            "usage_explanation": "The inspected source uses the declaration through the cited static dependency."})
    assessment = {
        "id": "a1", "hypothesis_id": "h1", "declaration_id": target["component_id"], "conclusion": category,
        "participants": related, "observed_facts": ["The declaration and use sites are present in the inspected source."],
        "supporting_evidence_ids": source_ids, "counterevidence_ids": [],
        "variation_points": "Amount collections vary while the aggregation rule is shared.",
        "reuse_benefit": "Orders and reports reuse the aggregation behavior rather than copying its implementation.",
        "indirection_cost": "The caller crosses a forwarding function with no transformation in the inspected body.",
        "coupling_consequence": "Consumers construct the concrete policy; replacing that construction requires adapting them.",
        "duplication_comparison": "Both inspected formatting functions implement the same numeric formatting behavior.",
        "boundary_justification": "The consumer accepts a StoragePort parameter instead of constructing the one observed implementation.",
        "counterevidence_analysis": "Considered translation, test substitution and intentional contracts; no runtime/history claims are made.",
        "proportional_alternative": "Consider direct use of the helper if no independent contract is intended.",
        "uncertainty": "medium", "limitations": ["Static fixture evidence only; runtime substitution was not exercised."],
    }
    candidate = {
        "id": "ABS-001", "title": "Observed abstraction tradeoff", "description": "Source-backed scoped reuse observation.",
        "criterion_id": "abstraction-reuse", "kind": "design_observation", "components": [target["component_id"]],
        "evidence_ids": source_ids, "justification": "Inspected declaration and actual consumers.",
        "modularity_impact": "Relevant to independent reuse of the observed behavior.",
        "severity": "info" if category == "useful_abstraction" else "medium", "confidence": 0.8,
        "recommendation": "Review the documented tradeoff before changing the design.",
        "category": category if category != "justified_boundary" else "unnecessary_abstraction",
        "assessment_ids": ["a1"], "basis": "usage_evidence",
    }
    value = {"sufficient": True, "hypotheses": [{**plan()["hypotheses"][0],
        "status": "discarded" if category == "justified_boundary" else "confirmed", "rationale": "Evaluated against source."}],
        "candidates": [candidate] if finding else [], "missing_information": [], "abstraction_assessments": [assessment]}
    if mutate:
        mutate(value)
    return value


def review(*identifiers, status="accepted"):
    return {"findings": [{"finding_id": i, "status": status, "rationale": "Inspected source and tradeoffs support this scoped conclusion.",
                          "severity": "medium", "confidence": 0.8} for i in identifiers], "limitations": []}


def run(root, responses, *, target="policy.py", native=True, **updates):
    tools = toolset(root)
    config = AbstractionConfig(**({"max_iterations": 1, "max_total_tokens": 300_000,
        "provider_rate_limits": {"requests_per_minute": None, "tokens_per_minute": None}} | updates))
    model = (NativeStructuredModel if native else ScriptedModel)(responses)
    result = asyncio.run(AbstractionAgent(model, config).run(tools, AbstractionRequest(targets=[target])))
    return result, model, tools


def normal(root, *, primary="policy.py", category="useful_abstraction", roles=None, finding=True, mutate=None, **config):
    roles = roles if roles is not None else [("orders.py", "consumer"), ("reports.py", "consumer")]
    return run(root, [plan(), reads(root, [primary, *[p for p, _ in roles]]), AIMessage(content="Ready to validate"),
        lambda m: evaluate(m, primary=primary, category=category, participants=roles, finding=finding, mutate=mutate),
        review("ABS-001") if finding else review()], target=primary, **config)


def test_shared_abstraction_graph_and_provenance(repo):
    before = fingerprints(repo)
    result, model, tools = normal(repo)
    assert result.status == "completed" and result.quality_attribute == "reusability"
    assert result.findings[0].validation_status == "accepted" and result.findings[0].category == "useful_abstraction"
    assert result.findings[0].severity == "info"
    assert len(model.history) == result.model_calls == 5
    assert result.tool_calls == 4
    assert len(model.bound_tools) == 7
    assert AbstractionAgent.execution_type._build_graph is InvestigationExecution._build_graph
    assert any(isinstance(m, ToolMessage) for m in model.history[2])
    assert {r.path for r in result.findings[0].evidence if r.kind == "source"} == {"policy.py", "orders.py", "reports.py"}
    assert all(e.snapshot_hash == tools.context.input.snapshot_hash for e in result.findings[0].evidence)
    assert all(e.start_line >= 1 and e.end_line <= next(f.line_count for f in tools.accessible_snapshot.files if f.id == e.file_id)
               for e in result.findings[0].evidence if e.kind == "source")
    assert result.coverage.assessed_declarations and not result.coverage.exhaustive
    assert fingerprints(repo) == before
    assert AbstractionResult.model_validate_json(result.model_dump_json()) == result


def test_pass_through_requires_actual_consumer_and_delegate(repo):
    result, _, _ = normal(repo, primary="wrapper.py", category="unnecessary_abstraction",
        roles=[("client.py", "consumer"), ("helpers.py", "delegate")])
    assert result.status == "completed"
    assert result.findings[0].validation_status == "accepted"


def test_single_implementation_with_valid_contract_is_not_overengineering(repo):
    result, _, _ = normal(repo, primary="port.py", category="justified_boundary",
        roles=[("checkout.py", "consumer"), ("adapter.py", "implementation")], finding=False)
    assert result.status == "completed" and not result.findings
    assert result.hypotheses[0].status == "discarded"
    assert result.abstractions_investigated[0].conclusion == "justified_boundary"


def test_missed_reuse_requires_comparison_of_distinct_sources(repo):
    result, _, _ = normal(repo, primary="duplicate_a.py", category="missed_reuse", roles=[("duplicate_b.py", "duplicate")])
    assert result.findings[0].validation_status == "accepted"


def test_coupling_requires_concrete_usage_consequence(repo):
    result, _, _ = normal(repo, category="coupling")
    assert result.findings[0].validation_status == "accepted"


@pytest.mark.parametrize("basis", ["metrics_only", "names_only", "structure_only"])
def test_structural_indicators_are_not_proof(repo, basis):
    result, _, _ = normal(repo, mutate=lambda v: v["candidates"][0].update(basis=basis))
    assert result.status == "partial" and result.findings[0].validation_status == "insufficient_evidence"


@pytest.mark.parametrize("fault", ["declaration", "consumer", "relationship", "anchor", "cost", "unknown_citation", "self_duplicate"])
def test_host_rejects_unverified_abstraction_claims(repo, fault):
    def corrupt(value):
        assessment = value["abstraction_assessments"][0]
        if fault == "declaration":
            assessment["declaration_id"] = "invented-component"
        elif fault == "consumer":
            assessment["participants"] = []
        elif fault == "relationship":
            assessment["participants"][0]["relationship_id"] = "invented-edge"
        elif fault == "anchor":
            assessment["participants"][0]["evidence_ids"] = []
        elif fault == "cost":
            assessment["reuse_benefit"] = ""
        elif fault == "unknown_citation":
            assessment["supporting_evidence_ids"].append("invented-evidence")
        else:
            assessment["participants"][0].update(role="duplicate", component_id=assessment["declaration_id"])
    result, _, _ = normal(repo, mutate=corrupt)
    assert result.status == "partial"
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert result.abstractions_investigated[0].validation_issues
    assert result.inconclusive_investigations


def test_host_gap_drives_another_inspection(repo):
    roles = [("orders.py", "consumer")]
    result, model, _ = run(repo, [plan(), reads(repo, ["policy.py"]), AIMessage(content="Validate"),
        lambda m: evaluate(m, participants=roles), reads(repo, ["orders.py"], graph=False), AIMessage(content="Revalidate"),
        lambda m: evaluate(m, participants=roles), review("ABS-001")], max_iterations=2)
    assert result.status == "completed" and result.iterations == 2
    assert result.findings[0].validation_status == "accepted"
    assert "actual_consumer_required" in json.loads(model.history[4][1].content)["missing_information"][0]


@pytest.mark.parametrize("limit", ["tools", "tokens", "context", "models"])
def test_execution_limits_are_explicit(repo, limit):
    config = {"max_tool_calls": 0} if limit == "tools" else {"max_total_tokens": 1000} if limit == "tokens" else {
        "max_context_characters": 4000} if limit == "context" else {"max_model_calls": 4}
    result, _, _ = normal(repo, **config)
    assert result.status in {"partial", "failed"}
    assert not any(f.validation_status == "accepted" for f in result.findings)
    assert result.termination_reason


def test_tool_failure_does_not_fabricate_source(repo):
    def failed_read(messages):
        message = reads(repo, ["policy.py", "orders.py"])
        message.tool_calls[1]["args"]["path"] = "missing.py"
        return message
    result, model, _ = run(repo, [plan(), failed_read, AIMessage(content="Validate"),
        lambda m: evaluate(m, participants=[("orders.py", "consumer")]), review("ABS-001")])
    assert result.status == "partial"
    assert result.tool_failures
    assert not any(f.validation_status == "accepted" for f in result.findings)
    assert any(json.loads(m.content)["status"] == "error" for messages in model.history for m in messages if isinstance(m, ToolMessage))


def test_review_can_reject_valid_source_supported_conclusion(repo):
    result, _, _ = run(repo, [plan(), reads(repo, ["policy.py", "orders.py", "reports.py"]), AIMessage(content="Validate"),
        evaluate, review("ABS-001", status="rejected")])
    assert result.findings[0].validation_status == "rejected"


def test_no_actionable_gap_finalizes_without_unconditional_loop(repo):
    result, model, _ = normal(repo, mutate=lambda value: value.update(sufficient=False), max_iterations=3)
    assert result.status == "partial" and result.termination_reason == "no_actionable_gap"
    assert result.iterations == 1 and len(model.history) == 5


def test_single_implementation_without_cost_evidence_cannot_establish_harm(repo):
    def counts_only(value):
        assessment = value["abstraction_assessments"][0]
        assessment.update(indirection_cost="", proportional_alternative="")
    result, _, _ = normal(repo, primary="port.py", category="unnecessary_abstraction",
        roles=[("checkout.py", "consumer"), ("adapter.py", "implementation")], mutate=counts_only)
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert "concrete_indirection_cost_and_alternative_required" in result.abstractions_investigated[0].validation_issues


def test_design_principle_cannot_be_reported_as_normative_violation(repo):
    result, _, _ = normal(repo, primary="wrapper.py", category="unnecessary_abstraction",
        roles=[("client.py", "consumer"), ("helpers.py", "delegate")],
        mutate=lambda value: value["candidates"][0].update(kind="violation"))
    assert result.findings[0].validation_status == "insufficient_evidence"


def test_duplicate_concerns_preserve_history_and_single_accepted_finding(repo):
    def duplicate(value):
        value["candidates"].append({**value["candidates"][0], "id": "ABS-002"})
    result, _, _ = run(repo, [plan(), reads(repo, ["policy.py", "orders.py", "reports.py"]), AIMessage(content="Validate"),
        lambda m: evaluate(m, mutate=duplicate), review("ABS-001", "ABS-002")])
    assert len(result.findings) == 2
    assert sum(f.validation_status == "accepted" for f in result.findings) == 1
    assert result.findings[1].duplicate_of == "ABS-001"


def test_discovery_is_deterministic_bounded_and_scope_checked(repo):
    snapshot = toolset(repo).accessible_snapshot
    selected, count = discover(snapshot, AbstractionRequest(), 2)
    assert len(selected) == 2 and count > 2
    assert discover(snapshot, AbstractionRequest(), 2) == (selected, count)
    assert len(discover(snapshot, AbstractionRequest(targets=["port.py"]), 12)[0]) == 1
    with pytest.raises(ValueError):
        discover(snapshot, AbstractionRequest(targets=["../outside"]), 12)
    with pytest.raises(ValueError):
        discover(snapshot, AbstractionRequest(targets=["README.md"]), 12)


@pytest.mark.parametrize("dirty", [False, True])
def test_commit_provenance_is_checked(repo, dirty):
    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    git("init")
    git("-c", "core.autocrlf=false", "add", ".")
    git("-c", "user.name=Offline Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture")
    if dirty:
        with (repo / "policy.py").open("a", encoding="utf-8") as stream:
            stream.write("# uncommitted change\n")
    before = fingerprints(repo)
    result, _, _ = normal(repo)
    assert (result.findings[0].validation_status == "accepted") is (not dirty)
    assert fingerprints(repo) == before


def test_live_harness_reuses_configuration_and_tracing(repo, capsys):
    spec = importlib.util.spec_from_file_location("abstraction_harness", Path(__file__).with_name("run_architecture_boundary.py"))
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    spans = []
    class Trace(NoOpTracingBackend):
        async def wrap_stage(self, coro, *, name, **metadata):
            spans.append((name, metadata))
            return await coro
    model = NativeStructuredModel([plan(), reads(repo, ["policy.py", "orders.py", "reports.py"]),
        AIMessage(content="Validate"), evaluate, review("ABS-001")])
    asyncio.run(harness.run_audit(SimpleNamespace(max_files=100), repo, AbstractionRequest(targets=["policy.py"]),
        AbstractionConfig(max_total_tokens=300_000), model,
        ModelSettings(provider="google", name="offline-model", temperature=0, max_tokens=4000),
        tracing_backend=Trace(), agent_class=AbstractionAgent))
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "completed"
    assert spans[0][0] == "abstraction" and spans[0][1]["agent_type"] == "abstraction"


def test_integration_useful_pass_through_and_justified_interface_in_one_audit(repo):
    before = fingerprints(repo)
    hypotheses = [{**plan()["hypotheses"][0], "id": "h" + str(i)} for i in range(1, 4)]
    def combined(messages):
        cases = [
            ("policy.py", "useful_abstraction", [("orders.py", "consumer"), ("reports.py", "consumer")], True),
            ("wrapper.py", "unnecessary_abstraction", [("client.py", "consumer"), ("helpers.py", "delegate")], True),
            ("port.py", "justified_boundary", [("checkout.py", "consumer"), ("adapter.py", "implementation")], False),
        ]
        value = {"sufficient": True, "hypotheses": [], "candidates": [], "missing_information": [], "abstraction_assessments": []}
        for index, (primary, category, roles, finding) in enumerate(cases, 1):
            part = evaluate(messages, primary=primary, category=category, participants=roles, finding=finding)
            part["hypotheses"][0]["id"] = "h" + str(index)
            assessment = part["abstraction_assessments"][0]
            assessment.update(id="a" + str(index), hypothesis_id="h" + str(index))
            for candidate in part["candidates"]:
                candidate.update(id="ABS-00" + str(index), assessment_ids=["a" + str(index)])
            for key in ("hypotheses", "candidates", "abstraction_assessments"):
                value[key].extend(part[key])
        return value
    paths = ["policy.py", "orders.py", "reports.py", "wrapper.py", "client.py", "helpers.py", "port.py", "checkout.py", "adapter.py"]
    model = NativeStructuredModel([{**plan(), "hypotheses": hypotheses}, reads(repo, paths),
        AIMessage(content="Validate all three selected candidates"), combined, review("ABS-001", "ABS-002")])
    result = asyncio.run(AbstractionAgent(model, AbstractionConfig(max_total_tokens=300_000, max_candidates=3)).run(
        toolset(repo), AbstractionRequest(targets=["policy.py", "wrapper.py", "port.py"])))
    assert result.status == "completed"
    assert {f.category for f in result.findings if f.validation_status == "accepted"} == {"useful_abstraction", "unnecessary_abstraction"}
    assert len(result.abstractions_investigated) == len(result.coverage.assessed_declarations) == 3
    assert result.hypotheses[-1].status == "discarded"
    assert fingerprints(repo) == before


def test_source_ranges_must_cover_usage_declarations(repo):
    message = reads(repo, ["policy.py", "orders.py", "reports.py"])
    for call in message.tool_calls:
        if call["name"] == "get_source_excerpt" and call["args"]["path"] != "policy.py":
            call["args"]["start_line"] = 2  # reads the consumer body but omits the import anchor
    result, _, _ = run(repo, [plan(), message, AIMessage(content="Validate"), evaluate, review("ABS-001")])
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert any("usage_declaration_not_inspected" in p.validation_issues for p in result.abstractions_investigated[0].participants)


def test_metadata_and_counts_without_source_are_insufficient(repo):
    message = AIMessage(content="", tool_calls=[{"name": "list_relationships", "args": {"resolution": "internal", "limit": 50}, "id": "graph"}])
    def metadata_claim(messages):
        value = evaluate(messages)
        ids = [r["id"] for r in json.loads(messages[1].content)["evidence"]][:6]
        value["candidates"][0]["evidence_ids"] = ids
        value["abstraction_assessments"][0]["supporting_evidence_ids"] = ids
        return value
    result, _, _ = run(repo, [plan(), message, AIMessage(content="Validate"), metadata_claim, review("ABS-001")])
    assert result.status == "partial"
    assert result.findings[0].validation_status == "insufficient_evidence"


def test_duplicate_assessment_ids_cannot_support_acceptance(repo):
    def duplicate(value):
        value["abstraction_assessments"].append(value["abstraction_assessments"][0].copy())
    result, _, _ = normal(repo, mutate=duplicate)
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert all("duplicate_assessment_id" in a.validation_issues for a in result.abstractions_investigated)


def test_provider_failure_returns_failed_and_retains_diagnostic(repo):
    result, _, _ = run(repo, [RuntimeError("simulated provider failure")])
    assert result.status == "failed" and result.termination_reason == "model_or_schema_error"
    assert not result.findings
    assert any("provider_request" in s for s in result.limitations)


def test_google_adapter_native_schemas_tools_and_usage_with_mocked_transport(repo, monkeypatch):
    from google.genai import types
    from langchain_core.messages import HumanMessage
    from langchain_google_genai import ChatGoogleGenerativeAI

    tools = toolset(repo)
    request = AbstractionRequest(targets=["policy.py"])
    config = AbstractionConfig(max_output_tokens=512, max_total_tokens=300_000)
    model = ChatGoogleGenerativeAI(model="gemini-3.5-flash-lite", api_key="offline-test-key",
        max_tokens=2048, max_retries=0)
    requests, responses = [], []
    execute = tools.execute
    def observe(*args, **kwargs):
        response = execute(*args, **kwargs)
        responses.append(response)
        return response
    monkeypatch.setattr(tools, "execute", observe)
    async def generate_content(**kwargs):
        requests.append(kwargs)
        turn = len(requests)
        if turn == 2:
            parts = [types.Part.from_function_call(name=c["name"], args=c["args"])
                     for c in reads(repo, ["policy.py", "orders.py", "reports.py"]).tool_calls]
        else:
            if turn == 1:
                value = plan()
            elif turn == 3:
                value = "Ready to validate"
            elif turn == 4:
                schema = kwargs["config"].response_json_schema
                assert schema["title"] == "AbstractionEvaluation" and "maxItems" not in json.dumps(schema)
                selected, _ = discover(tools.accessible_snapshot, request, config.max_candidates)
                context = {"abstraction_candidates": [c.model_dump() for c in selected],
                    "evidence": [r.model_dump() for r in InvestigationExecution.references(SimpleNamespace(tools=tools))]}
                value = evaluate([HumanMessage(content=""), HumanMessage(content=json.dumps(context)),
                    *[ToolMessage(content=r.model_dump_json(), tool_call_id=r.tool_call_id) for r in responses]])
            elif turn == 5:
                value = review("ABS-001")
            else:
                raise AssertionError("Unexpected provider call")
            parts = [types.Part(text=json.dumps(value) if isinstance(value, dict) else value)]
        return types.GenerateContentResponse(candidates=[types.Candidate(
            content=types.Content(role="model", parts=parts), finish_reason="STOP")],
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=100, candidates_token_count=30, total_token_count=130))
    monkeypatch.setattr(model.async_client.models, "generate_content", generate_content)
    result = asyncio.run(AbstractionAgent(model, config).run(tools, request))
    assert result.status == "completed" and result.findings[0].validation_status == "accepted"
    assert result.model_calls == len(requests) == 5
    assert result.accounted_tokens == 650 and result.estimated_tokens == 0
    assert model.max_output_tokens == 2048
    assert all(r["config"].max_output_tokens == 512 for r in requests)
