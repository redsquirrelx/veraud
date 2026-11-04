"""The scaffold retains findings without claiming to have resolved them."""

import asyncio
import json

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from server.agents.finding_resolution import (
    FindingResolutionAgent,
    FindingResolutionConfig,
    FindingResolutionRequest,
    FindingResolutionResult,
)
from server.contracts.audit import Criterion, EvidenceReference, Finding
from server.runtimes.repository.context import RepositoryContext
from server.runtimes.repository.schemas import RepositoryInput
from server.runtimes.repository.tools import RepositoryToolset
from server.services.repository_analysis import RepositoryAnalysisService


class PlanningModel:
    def __init__(self, respond=None):
        self.contexts = []
        self.respond = respond or self.decide

    def bind_tools(self, tools):
        return self

    @staticmethod
    def plan(context):
        return {"finding_id": context["finding"]["id"], "checks": [{
            "question": "Does the consuming implementation still bypass the interface?",
            "evidence_needed": ["Current implementation and consuming access."],
            "queries": [{"id": "read-current", "name": "get_source_excerpt", "arguments": {"path": "service.py"}}],
            "persists_if": "Current usage still directly accesses private state.",
            "resolved_if": "Current implementation and callers consistently use the supported interface.",
        }], "limitations": ["The plan has not retrieved current source yet."]}

    @classmethod
    def decide(cls, context):
        if "plan" not in context:
            return cls.plan(context)
        return {"finding_id": context["finding"]["id"], "action": "close",
            "summary": "This planning test does not inspect source.",
            "limitations": ["Current source was not inspected by this test."]}

    async def ainvoke(self, messages, **kwargs):
        assert len(messages) == 3  # No conversation/history from another finding.
        context = json.loads(messages[1].content)
        self.contexts.append(context)
        return AIMessage(content=json.dumps(self.respond(context)),
            usage_metadata={"input_tokens": 100, "output_tokens": 100, "total_tokens": 200})


@pytest.fixture
def tools(tmp_path):
    (tmp_path / "service.py").write_text("def use(): return 1\n", encoding="utf-8")
    snapshot = RepositoryAnalysisService().analyze_sync(tmp_path)
    return RepositoryToolset(RepositoryContext(snapshot, RepositoryInput(snapshot_hash=snapshot.repository.snapshot_hash)),
        workspace_root=tmp_path.parent)


def planning_agent(model, **overrides):
    return FindingResolutionAgent(model, FindingResolutionConfig(provider_request_interval_seconds=0,
        provider_rate_limits={"requests_per_minute": None, "tokens_per_minute": None}, **overrides))


@pytest.fixture
def finding():
    return Finding(id="f1", title="Original finding", description="Original description.",
        criterion_id="c1", kind="design_observation", components=["service.py"],
        justification="Original reasoning.", modularity_impact="Possible interface bypass.",
        severity="low", confidence=.7, recommendation="Inspect the interface.",
        criterion=Criterion(id="c1", description="Boundary criterion.", origin="inferred", provenance="Code."),
        evidence_ids=["historical-evidence"], evidence=[EvidenceReference(
            id="historical-evidence", snapshot_hash="a" * 64, commit=None, path="service.py", file_id="old-file",
            content_hash="b" * 64, kind="source", start_line=1, end_line=1, tool_call_id="old-call")],
        validation_status="insufficient_evidence", review_rationale="Not reviewed.")


def test_read_finding_and_plan_verification(finding, tools):
    """Run individually with pytest tests/test_finding_resolution.py::test_read_finding_and_plan_verification -s."""
    request = FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path, findings=[finding])
    before = request.model_dump()
    model = PlanningModel()
    agent = planning_agent(model)
    execution = agent.execution_type(model, agent.config, tools, request)
    async def stream():
        with execution.timing.stage("planning-test"):
            return [update async for update in execution.graph.astream(execution.initial_state(), stream_mode="updates")]
    updates = asyncio.run(stream())
    assert [next(iter(update)) for update in updates] == ["read_finding", "plan_verification", "investigate", "read_finding"]
    plan = updates[1]["plan_verification"]["plans"][0]
    assert plan.finding_id == finding.id and plan.checks[0].queries[0].name == "get_source_excerpt"
    assert model.contexts[0]["finding"] == finding.model_dump(mode="json")
    assert request.model_dump() == before
    assert execution.calls == 2 and execution.tokens == 400 and tools.budget_usage.tool_calls == 0
    assert set(execution.graph.get_graph().nodes) == {"__start__", "read_finding", "plan_verification", "investigate", "tools", "__end__"}
    print("\nread_finding -> plan_verification\n" + json.dumps(plan.model_dump(mode="json"), indent=2))


def test_empty_request_does_not_invent_findings(tools):
    model = PlanningModel()
    state = asyncio.run(planning_agent(model).run(FindingResolutionRequest(
        repository_path=tools.accessible_snapshot.repository.root_path, findings=[]), tools=tools))
    assert state["plans"] == [] and state["termination_reason"] == "no_findings"
    assert model.contexts == [] and state["consumption"].model_calls == tools.budget_usage.tool_calls == 0


def test_findings_have_independent_contexts_and_leave_originals_unchanged(finding, tools):
    second = finding.model_copy(update={"id": "f2", "description": "Independent second problem.",
        "components": ["missing.py"], "justification": "Second historical justification."}, deep=True)
    request = FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path, findings=[finding, second])
    before = request.model_dump()
    model = PlanningModel()
    state = asyncio.run(planning_agent(model).run(request, tools=tools))
    assert [plan.finding_id for plan in state["plans"]] == [finding.id, second.id]
    planning_contexts = [context for context in model.contexts if "plan" not in context]
    assert [context["finding"] for context in planning_contexts] == [item.model_dump(mode="json") for item in request.findings]
    assert model.contexts[0]["affected_paths"] == [{"path": "service.py", "in_current_snapshot": True}]
    assert planning_contexts[1]["affected_paths"] == [{"path": "missing.py", "in_current_snapshot": False}]
    assert all(context["historical_evidence_only"] for context in model.contexts)
    assert state["finding"] is None and state["finding_context"] == {} and state["messages"] == []
    assert state["termination_reason"] == "investigations_completed" and state["consumption"].accounted_tokens == 800
    assert request.model_dump() == before and tools.retrieved_evidence == ()


@pytest.mark.parametrize("invalid", ["finding_id", "tool", "arguments"])
def test_invalid_plans_are_not_retained(finding, tools, invalid):
    def respond(context):
        plan = PlanningModel.plan(context)
        if invalid == "finding_id":
            plan["finding_id"] = "unknown"
        elif invalid == "tool":
            plan["checks"][0]["queries"][0]["name"] = "write_source"
        else:
            plan["checks"][0]["queries"][0]["arguments"] = {"path": "service.py", "start_line": -1}
        return plan
    state = asyncio.run(planning_agent(PlanningModel(respond), max_schema_retries=0).run(
        FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path, findings=[finding]), tools=tools))
    assert state["plans"] == [] and state["next_finding"] == 0
    assert state["termination_reason"] == "model_or_schema_error" and state["limitations"]
    assert state["consumption"].model_calls == 1 and tools.budget_usage.tool_calls == 0


def test_shared_token_budget_blocks_planning_before_provider_call(finding, tools, finite_token_budget):
    model = PlanningModel()
    state = asyncio.run(planning_agent(model, max_total_tokens=1000).run(
        FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path, findings=[finding]), tools=tools))
    assert state["termination_reason"] == "token_limit" and state["plans"] == [] and model.contexts == []


def test_shared_call_budget_retains_completed_plans(finding, tools):
    request = FindingResolutionRequest(repository_path=tools.accessible_snapshot.repository.root_path,
        findings=[finding.model_copy(update={"id": f"f{index}"}) for index in range(5)])
    state = asyncio.run(planning_agent(PlanningModel(), max_model_calls=4).run(request, tools=tools))
    assert len(state["plans"]) == len(state["investigations"]) == 2
    assert state["consumption"].model_calls == 4
    assert state["next_finding"] == 2 and state["termination_reason"] == "model_call_limit"


def test_native_structured_output_uses_the_same_plan_contract(finding, tools):
    class StructuredModel(PlanningModel):
        def with_structured_output(self, schema, **kwargs):
            parent = self
            class Structured:
                async def ainvoke(self, messages, **options):
                    raw = await parent.ainvoke(messages, **options)
                    return {"raw": raw, "parsed": schema.model_validate_json(raw.content)}
            return Structured()
    state = asyncio.run(planning_agent(StructuredModel()).run(FindingResolutionRequest(
        repository_path=tools.accessible_snapshot.repository.root_path, findings=[finding]), tools=tools))
    assert state["plans"][0].finding_id == finding.id and state["consumption"].model_calls == 2


def test_input_contract_has_exactly_two_required_fields_and_reuses_finding():
    schema = FindingResolutionRequest.model_json_schema()
    assert set(schema["properties"]) == set(schema["required"]) == {"repository_path", "findings"}
    assert FindingResolutionRequest.model_fields["findings"].annotation == list[Finding]
    request = FindingResolutionRequest(repository_path="repository", findings=[])
    assert FindingResolutionRequest.model_validate_json(request.model_dump_json()) == request


@pytest.mark.parametrize("values", [
    {"findings": []}, {"repository_path": "repository"},
    {"repository_path": "", "findings": []},
    {"repository_path": "repository", "findings": [], "commit": "abc123"},
])
def test_input_rejects_missing_fields_empty_path_and_additional_parameters(values):
    with pytest.raises(ValidationError):
        FindingResolutionRequest.model_validate(values)


@pytest.mark.parametrize("status", ["resolved", "persists", "inconclusive"])
def test_output_accepts_each_status_and_retains_evidence_ids(finding, status):
    request = FindingResolutionRequest(repository_path="repository", findings=[finding])
    result = FindingResolutionResult.model_validate({"results": [
        {"finding_id": finding.id, "status": status, "reason": "Source-backed decision.", "evidence_ids": ["e1"]}
    ]}, context={"request": request})
    assert result.results[0].status == status and result.results[0].evidence_ids == ["e1"]


@pytest.mark.parametrize("ids", [[], ["f1", "f1"], ["unknown"], ["f1", "unknown"]])
def test_output_rejects_missing_duplicate_and_unknown_results(finding, ids):
    request = FindingResolutionRequest(repository_path="repository", findings=[finding])
    with pytest.raises(ValidationError):
        FindingResolutionResult.model_validate({"results": [
            {"finding_id": identifier, "status": "inconclusive", "reason": "Not verified.", "evidence_ids": []}
            for identifier in ids
        ]}, context={"request": request})


@pytest.mark.parametrize("changes", [
    {"status": "pending"}, {"reason": ""}, {"reason": "   "}, {"evidence_ids": None},
])
def test_output_rejects_invalid_result_fields(finding, changes):
    request = FindingResolutionRequest(repository_path="repository", findings=[finding])
    item = {"finding_id": finding.id, "status": "inconclusive", "reason": "Not verified.", "evidence_ids": []}
    with pytest.raises(ValidationError):
        FindingResolutionResult.model_validate({"results": [item | changes]}, context={"request": request})


def test_output_requires_original_request_for_coverage_validation():
    with pytest.raises(ValidationError, match="original FindingResolutionRequest"):
        FindingResolutionResult.model_validate({"results": []})


def test_output_rejects_ambiguous_original_ids(finding):
    request = FindingResolutionRequest(repository_path="repository", findings=[finding, finding])
    with pytest.raises(ValidationError, match="Original finding IDs must be unique"):
        FindingResolutionResult.model_validate({"results": []}, context={"request": request})


def test_output_accepts_one_result_per_finding_independent_of_order(finding):
    request = FindingResolutionRequest(repository_path="repository", findings=[finding, finding.model_copy(update={"id": "f2"})])
    result = FindingResolutionResult.model_validate({"results": [
        {"finding_id": identifier, "status": "inconclusive", "reason": "Not verified.", "evidence_ids": []}
        for identifier in ["f2", "f1"]
    ]}, context={"request": request})
    assert [item.finding_id for item in result.results] == ["f2", "f1"]
