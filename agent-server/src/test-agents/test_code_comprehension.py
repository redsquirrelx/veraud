"""Offline regression checks: real graph/tools, scripted model, no credentials or API calls."""

import asyncio
import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError
from test_architecture_boundary import (
    NativeStructuredModel,
    ScriptedModel,
    fingerprints,
    toolset,
)

from config.agents.catalog import (
    describe_agent_config,
    validate_agent_config,
    validate_developer_agent_config,
)
from server.agents.maintainability.analysability.code_comprehension import (
    CodeComprehensionAgent,
    CodeComprehensionConfig,
    CodeComprehensionRequest,
    CodeComprehensionResult,
)
from server.agents.maintainability.analysability.code_comprehension.schemas import (
    InspectedParticipant,
    ProjectRepresentations,
)
from server.blackboard.identity import AuditIdentity
from server.blackboard.impls.memory import MemoryBlackboard
from server.config.schemas import ModelSettings
from server.project_analysis.project_architecture.schemas import (
    ArchitectureReport,
    ArchitectureResult,
)
from server.project_analysis.project_orientation.schemas import (
    Component,
    Observation,
    Orientation,
    OrientationResult,
    StartingPoint,
)
from server.project_analysis.project_semantic_validation.schemas import (
    SemanticValidationResult,
)
from server.reporting.knowledge import category
from server.runtimes.investigation.agent import InvestigationExecution
from server.runtimes.repository.schemas import BudgetUsage
from server.runtimes.repository.telemetry import ExecutionTelemetry

PLAN = {"objectives": ["Understand state-dependent processing"], "components": ["component.py"], "hypotheses": [{
    "id": "h1", "question": "Does process obscure whether a call mutates or formats state?",
    "criterion_id": "comprehension-behavior", "component_ids": ["component.py"],
    "evidence_needed": ["The process implementation and its state transitions"],
}]}


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "component.py").write_text(
        "class Processor:\n"
        "    def __init__(self):\n        self.mode = False\n        self.total = 0\n"
        "    def process(self, value):\n        if self.mode:\n            self.mode = False\n"
        "            return str(self.total)\n        self.total += value\n        self.mode = True\n        return self.total\n",
        encoding="utf-8")
    (root / "caller.py").write_text(
        "def consume(processor):\n    processor.process(3)\n    return processor.process(4)\n", encoding="utf-8")
    return root


def source(path="component.py", start=1, end=11):
    return AIMessage(content="", tool_calls=[{"name": "get_source_excerpt", "id": f"read-{path}-{start}-{end}",
        "args": {"path": path, "start_line": start, "end_line": end}}])


def evaluate(messages, *, clear=False, candidate=True, sufficient=True, basis="behavioral"):
    context = json.loads(messages[1].content)
    refs = context["evidence"]
    ids = [r["id"] for r in refs]
    hypothesis = {**context["hypotheses"][0], "status": "discarded" if clear else "confirmed" if sufficient else "inconclusive",
        "evidence_ids": ids, "rationale": "Local process behavior is established by inspected branches."}
    assessment = {"id": "a1", "hypothesis_id": "h1", "component_id": context["hypotheses"][0]["component_ids"][0],
        "responsibility": "Accumulate totals and format prior state", "observed_behavior": "A call alternates mutation and string formatting.",
        "comprehension_question": "Does this call add its value or return a string?",
        "difficulty": "Hidden mode changes the meaning of the same operation.",
        "comprehension_impact": "Understanding a call requires reconstructing earlier calls and state.",
        "alternative_explanation": "An explicitly documented alternating protocol could justify this interface.",
        "counterevidence_analysis": "The two implementation branches were inspected; the protocol is not explicit in the call signature.",
        "conclusion": "clear" if clear else "problematic" if sufficient else "inconclusive", "basis": basis,
        "supporting_evidence_ids": ids, "counterevidence_ids": [], "participants": [], "limitations": ["Only inspected process behavior."]}
    finding = {"id": "f1", "title": "Implicit alternating operation", "description": assessment["difficulty"],
        "criterion_id": "comprehension-behavior", "kind": "design_observation", "components": [assessment["component_id"]],
        "evidence_ids": ids, "assessment_ids": ["a1"], "justification": assessment["observed_behavior"],
        "modularity_impact": assessment["comprehension_impact"], "severity": "medium", "confidence": 0.8,
        "recommendation": "Expose accumulation and formatting as explicit operations if the alternating protocol is unnecessary."}
    return {"sufficient": sufficient, "hypotheses": [hypothesis], "candidates": [finding] if candidate else [],
        "comprehension_assessments": [assessment], "missing_information": [] if sufficient else ["Inspect remaining implementation."]}


def review(messages, *, candidate=True, status="accepted", scope=True):
    context = json.loads(messages[1].content)
    ids = [r["id"] for r in context["evidence"]]
    return {"findings": [{"finding_id": "f1", "status": status, "rationale": "Checked state, branches, alternatives and local comprehension impact.",
        "severity": "low", "confidence": 0.7, "scope_supported": scope, "checked_evidence_ids": ids,
        "unverified_claims": []}] if candidate else [], "limitations": [],
        "hypotheses": [{"hypothesis_id": "h1", "status": "supported", "rationale": "Source supports the bounded process interpretation.",
            "assessment_ids": ["a1"], "checked_evidence_ids": ids, "scope_supported": scope, "unverified_claims": []}]}


def run_agent(root, *, evaluator=evaluate, reviewer=review, model_type=ScriptedModel, config=None, request=None, reads=None, **agent_kwargs):
    tools = toolset(root)
    model = model_type([PLAN, *(reads if reads is not None else [source()]), AIMessage(content="Evaluate now"), evaluator, reviewer])
    agent = CodeComprehensionAgent(model, config or CodeComprehensionConfig(max_total_tokens=300_000, max_iterations=1), **agent_kwargs)
    result = asyncio.run(agent.run(tools, request))
    return result, model, tools


def test_real_graph_read_only_traceability_and_accepted_only_finalization(repo, monkeypatch):
    before = fingerprints(repo)
    original = CodeComprehensionAgent.execution_type.finalize

    def finalize(self, state):
        def forbidden(*args, **kwargs):
            pytest.fail("Finalization cannot call a model or repository tool")
        monkeypatch.setattr(self.model, "ainvoke", forbidden)
        monkeypatch.setattr(self.tools, "execute", forbidden)
        return original(self, state)

    monkeypatch.setattr(CodeComprehensionAgent.execution_type, "finalize", finalize)
    result, model, tools = run_agent(repo)
    assert result.termination_reason == "sufficient_evidence"
    assert len(result.findings) == 1 and result.findings[0].validation_status == "accepted"
    assert result.findings[0].severity == "low" and result.findings[0].confidence == 0.7
    assert result.findings[0].subcharacteristic == "analysability"
    assert all(r.path == "component.py" and r.start_line == 1 and r.end_line == 11 and r.symbol_ids for r in result.findings[0].evidence)
    assert fingerprints(repo) == before
    assert result.model_calls == len(model.history) == 5
    assert result.tool_calls == tools.budget_usage.tool_calls == 1
    assert CodeComprehensionAgent.execution_type._build_graph is InvestigationExecution._build_graph
    assert CodeComprehensionResult.model_validate_json(result.model_dump_json()) == result


def test_native_langchain_structured_output(repo):
    result, model, _ = run_agent(repo, model_type=NativeStructuredModel)
    assert result.findings
    assert [name for name, _, _ in model.schemas] == ["CodeComprehensionPlan", "CodeComprehensionEvaluation", "CodeComprehensionReview"]


def test_clear_behavior_discards_hypothesis_without_findings(repo):
    result, _, _ = run_agent(repo, evaluator=lambda m: evaluate(m, clear=True, candidate=False),
        reviewer=lambda m: review(m, candidate=False))
    assert not result.findings
    assert result.discarded_hypotheses[0].id == "h1"
    assert result.termination_reason == "sufficient_evidence"


@pytest.mark.parametrize("basis", ["names_only", "metrics_only", "structure_only"])
def test_navigation_or_metrics_cannot_become_accepted_findings(repo, basis):
    result, _, _ = run_agent(repo, evaluator=lambda m: evaluate(m, basis=basis))
    assert not result.findings
    assert "behavioral_support_required" in result.comprehension_assessments[0].validation_issues
    assert result.candidate_diagnostics and result.hypotheses[0].status == "inconclusive"


@pytest.mark.parametrize("problem", ["unknown_citation", "other_component", "participant", "duplicate", "no_impact", "unknown_assessment",
    "unknown_criterion", "uninspected_finding_component", "nonexplicit_violation"])
def test_host_checks_source_identity_and_scoped_support(repo, problem):
    def evaluator(messages):
        value = evaluate(messages)
        assessment = value["comprehension_assessments"][0]
        if problem == "unknown_citation":
            assessment["supporting_evidence_ids"] = ["fabricated"]
        elif problem == "other_component":
            assessment["component_id"] = "caller.py"
        elif problem == "participant":
            assessment["participants"] = [{"component_id": "caller.py", "observed_behavior": "Consumer uses process twice",
                "evidence_ids": assessment["supporting_evidence_ids"]}]
        elif problem == "duplicate":
            value["comprehension_assessments"].append(dict(assessment))
        elif problem == "no_impact":
            assessment["comprehension_impact"] = " "
        elif problem == "unknown_assessment":
            value["candidates"][0]["assessment_ids"] = ["invented"]
        elif problem == "unknown_criterion":
            value["candidates"][0]["criterion_id"] = "invented"
        elif problem == "uninspected_finding_component":
            value["candidates"][0]["components"].append("caller.py")
        else:
            value["candidates"][0]["kind"] = "violation"
        return value
    result, _, _ = run_agent(repo, evaluator=evaluator)
    assert not result.findings
    assert result.candidate_diagnostics
    assert all(i != "fabricated" for a in result.comprehension_assessments for i in a.supporting_evidence_ids)


@pytest.mark.parametrize("problem", ["reject", "scope", "hypothesis_review", "checked_citation"])
def test_independent_review_can_block_model_acceptance(repo, problem):
    def reviewer(messages):
        value = review(messages, status="rejected" if problem == "reject" else "accepted", scope=problem != "scope")
        if problem == "hypothesis_review":
            value["hypotheses"] = []
        elif problem == "checked_citation":
            value["findings"][0]["checked_evidence_ids"] = ["invented"]
        return value
    result, _, _ = run_agent(repo, reviewer=reviewer)
    if problem == "hypothesis_review":
        assert result.hypotheses[0].status == "inconclusive"
        assert result.termination_reason == "evidence_validation_failed"
    else:
        assert not result.findings


def test_missing_review_never_accepts_and_retains_source(repo, monkeypatch):
    execution = CodeComprehensionAgent.execution_type
    original = execution.call

    async def call(self, node, *args, **kwargs):
        if node == "review_findings":
            self.stop = "token_limit"
            return None
        return await original(self, node, *args, **kwargs)

    monkeypatch.setattr(execution, "call", call)
    result, _, _ = run_agent(repo)
    assert not result.findings and result.evidence
    assert result.critical_review is None and result.hypotheses[0].status == "inconclusive"


def test_insufficient_evidence_reenters_investigation_without_recommending_satisfied_reads(repo):
    tools = toolset(repo)
    model = ScriptedModel([PLAN, source(end=4), AIMessage(content="Partial"),
        lambda m: evaluate(m, sufficient=False, candidate=False), source(start=5), AIMessage(content="Ready"), evaluate, review])
    result = asyncio.run(CodeComprehensionAgent(model, CodeComprehensionConfig(max_total_tokens=300_000)).run(tools))
    assert result.iterations == 2 and result.findings
    assert "Inspect remaining implementation" in model.history[4][1].content
    # Once the full original range is delivered, there is no suggestion to repeat it.
    execution = CodeComprehensionAgent.execution_type(ScriptedModel([]), CodeComprehensionConfig(), tools, CodeComprehensionRequest())
    state = execution.initial_state()
    state["hypotheses"] = []
    assert not any(r["arguments"]["path"] == "component.py" for r in execution._context(state)["next_source_reads"])


def test_identical_unsatisfied_round_stops_with_no_progress(repo):
    tools = toolset(repo)
    partial = lambda m: evaluate(m, sufficient=False, candidate=False)
    model = ScriptedModel([PLAN, source(), AIMessage(content="Partial"), partial, AIMessage(content="No new evidence"), partial,
        lambda m: review(m, candidate=False)])
    result = asyncio.run(CodeComprehensionAgent(model, CodeComprehensionConfig(max_total_tokens=300_000)).run(tools))
    assert result.termination_reason == "no_investigation_progress"
    assert result.iterations == 2 and result.tool_calls == 1
    assert result.hypotheses[0].status == "inconclusive"


def test_rereading_identical_bytes_is_not_new_investigation_progress(repo):
    tools = toolset(repo)
    partial = lambda m: evaluate(m, sufficient=False, candidate=False)
    model = ScriptedModel([PLAN, source(), AIMessage(content="Partial"), partial,
        source(), AIMessage(content="Same evidence"), partial, lambda m: review(m, candidate=False)])
    result = asyncio.run(CodeComprehensionAgent(model, CodeComprehensionConfig(max_total_tokens=300_000)).run(tools))
    assert result.termination_reason == "no_investigation_progress"
    assert result.tool_calls == 2 and len(result.evidence) == 2


@pytest.mark.parametrize("limits, expected", [({"max_total_tokens": 1000}, "token_limit"),
    ({"max_model_calls": 4}, "model_call_limit"), ({"max_context_characters": 4000}, "context_limit")])
def test_hard_limits_preserve_uncertainty(repo, limits, expected):
    options = {"max_total_tokens": 300_000, "max_iterations": 1, **limits}
    result, _, _ = run_agent(repo, config=CodeComprehensionConfig(**options),
        reads=[] if "max_model_calls" in limits else None)
    assert result.termination_reason == expected
    assert not result.findings


def test_component_and_participant_limits_affect_execution(repo):
    tools = toolset(repo)
    config = CodeComprehensionConfig(max_components=1, max_related_components_per_assessment=1)
    request = CodeComprehensionRequest(targets=["component.py", "caller.py"])
    execution = CodeComprehensionAgent.execution_type(ScriptedModel([]), config, tools, request)
    assert execution.selected == [execution.paths["component.py"]]
    assert any("omitted 1" in issue for issue in execution.issues)
    execution.hypothesis_scopes = {"h1": set(execution.selected)}
    tools.execute("get_source_excerpt", {"path": "component.py", "start_line": 1, "end_line": 11}, tool_call_id="own")
    refs = {r.id: r for r in execution.references()}
    context = execution.initial_state()
    context["hypotheses"] = [CodeComprehensionAgent.execution_type.plan_schema.model_validate(PLAN).hypotheses[0]]
    context["hypotheses"][0] = context["hypotheses"][0].model_copy(update={"component_ids": execution.selected})
    value = evaluate([None, SimpleNamespace(content=json.dumps(execution._context(context)))])
    assessment = execution.evaluation_schema.model_validate(value).comprehension_assessments[0]
    participant = {"component_id": "caller.py", "observed_behavior": "Consumes state", "evidence_ids": list(refs)}
    assessment = assessment.model_copy(update={"participants": [InspectedParticipant(**participant), InspectedParticipant(**participant)]})
    assert "related_component_limit" in execution.normalize(assessment, refs, set()).validation_issues


def test_invalid_targets_and_plans_do_not_silently_select_other_components(repo):
    result, _, tools = run_agent(repo, request=CodeComprehensionRequest(targets=["missing.py"]))
    assert result.termination_reason == "invalid_plan" and not result.findings
    assert tools.budget_usage.tool_calls == 0


def project_results(tools):
    identity = {f.path: f.id for f in tools.accessible_snapshot.files}
    common = {"snapshot_hash": tools.context.input.snapshot_hash, "completion_status": "partial",
        "usage": BudgetUsage(), "telemetry": ExecutionTelemetry()}
    orientation = OrientationResult(**common, orientation=Orientation(
        components=(Component(name="Processor", file_ids=(identity["component.py"],), responsibility=Observation(
            statement="Possibly alternate accumulation and formatting", status="hypothesis", limitations=("Inspect state",))),),
        starting_points=(StartingPoint(file_id=identity["component.py"], reason="Follow process state"),)))
    architecture = ArchitectureResult(**common, architecture=ArchitectureReport(uncertainties=("Consumer protocol unresolved",)))
    semantic = SemanticValidationResult(**common, original_result=architecture, report_hash="earlier-report",
        verdict="inconclusive", selected_target_ids=(), pending_target_ids=())
    return ProjectRepresentations(orientation=orientation, architecture=architecture, semantic_validation=semantic)


def test_existing_representations_are_typed_snapshot_bound_navigation_not_proof(repo):
    tools = toolset(repo)
    representations = project_results(tools)
    request = CodeComprehensionRequest(representations=representations)
    execution = CodeComprehensionAgent.execution_type(ScriptedModel([]), CodeComprehensionConfig(), tools, request)
    context = execution.model_context("plan_investigation", execution.initial_state())
    assert context["project_representations"]["orientation"]["components"][0]["responsibility"]["status"] == "hypothesis"
    assert context["project_representations"]["semantic_validation"]["verdict"] == "inconclusive"
    assert context["evidence"] == [] and tools.budget_usage.tool_calls == 0
    assert execution.selected[0] == execution.paths["component.py"]
    representations = representations.model_copy(update={
        "orientation": representations.orientation.model_copy(update={"snapshot_hash": "0" * 64}),
        "semantic_validation": representations.semantic_validation.model_copy(update={
            "original_result": representations.architecture.model_copy(update={"limitations": ("Other version",)})})})
    request = request.model_copy(update={"representations": representations})
    execution = CodeComprehensionAgent.execution_type(ScriptedModel([]), CodeComprehensionConfig(), tools, request)
    assert "orientation" not in execution.navigation and "semantic_validation" not in execution.navigation
    assert len(execution.issues) == 2


def test_configuration_levels_and_effective_prompt_resources():
    panel = describe_agent_config("code_comprehension")
    assert "max_components" not in panel["defaults"]
    with pytest.raises(ValidationError):
        validate_agent_config("code_comprehension", {"max_components": 2})
    config = validate_developer_agent_config("code_comprehension", {"max_components": 2})
    assert config.max_components == 2
    detail = describe_agent_config("code_comprehension", level="developer")
    assert set(detail["prompt_defaults"]) == {"plan_investigation", "investigate", "evaluate_evidence", "review_findings"}
    assert detail["field_levels"]["max_related_components_per_assessment"] == "developer"


def test_blackboard_publishes_only_accepted_findings_and_categorizes_analysability(repo):
    board = MemoryBlackboard()
    identity = AuditIdentity(run_id="comprehension-audit", invocation_id="comprehension-invocation")
    result, _, _ = run_agent(repo, blackboard=board, audit_identity=identity)
    findings = board.query_findings(identity.run_id)
    assert len(findings) == len(result.findings) == 1
    assert category(findings[0]) == ("maintainability", "analysability")
    assert board.query_evidence(identity.run_id)[0].symbol_ids
    second = AuditIdentity(run_id="rejected-audit", invocation_id="rejected-invocation")
    run_agent(repo, reviewer=lambda m: review(m, status="rejected"), blackboard=board, audit_identity=second)
    assert not board.query_findings(second.run_id)
    assert board.query_evidence(second.run_id)[0].details["investigation"]["candidate_diagnostics"]


def test_git_commit_attribution_and_checkout_preservation(repo):
    for command in (["init"], ["add", "."], ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-m", "fixture"]):
        subprocess.run(["git", "-C", str(repo), *command], check=True, capture_output=True)
    before = fingerprints(repo)
    result, _, _ = run_agent(repo)
    assert all(r.commit_verification in {"exact", "line_endings_equivalent"} and r.git_blob_id for r in result.evidence)
    assert fingerprints(repo) == before


def test_unverifiable_commit_does_not_trigger_repeated_source_reads(repo, monkeypatch):
    from server.runtimes.investigation.provenance import CommitVerification

    tools = toolset(repo)
    snapshot = tools.context.snapshot
    repository = snapshot.repository.model_copy(update={"commit": "a" * 40})
    snapshot = snapshot.model_copy(update={"repository": repository})
    from server.runtimes.repository.context import RepositoryContext
    from server.runtimes.repository.tools import RepositoryToolset

    tools = RepositoryToolset(RepositoryContext(snapshot, tools.context.input), workspace_root=repo.parent)
    monkeypatch.setattr("server.runtimes.investigation.agent.verify_commit",
        lambda *args: CommitVerification(matched=False, reason="git_object_unavailable", blob_id=None))
    model = ScriptedModel([PLAN, source(), AIMessage(content="Ready"), evaluate, review])
    result = asyncio.run(CodeComprehensionAgent(model, CodeComprehensionConfig(max_total_tokens=300_000)).run(tools))
    assert result.termination_reason == "provenance_unverifiable"
    assert result.iterations == 1 and result.tool_calls == 1 and not result.findings
    assert result.evidence[0].commit is None and result.evidence[0].commit_verification == "unverified"


def test_tool_error_is_not_source_evidence(repo):
    result, _, _ = run_agent(repo, reads=[source(path="missing.py")],
        evaluator=lambda m: evaluate(m, sufficient=False, candidate=False), reviewer=lambda m: review(m, candidate=False))
    assert not result.evidence and not result.findings
    assert result.hypotheses[0].status == "inconclusive"


@pytest.mark.parametrize("read", [source(end=1), AIMessage(content="", tool_calls=[{
    "name": "list_files", "id": "metadata", "args": {"limit": 10}}])])
def test_declarations_and_metadata_alone_do_not_establish_behavior(repo, read):
    result, _, _ = run_agent(repo, reads=[read])
    assert not result.findings
    assert "component_body_not_inspected" in result.comprehension_assessments[0].validation_issues


def test_tool_budget_still_allows_bounded_evaluation_and_review(repo):
    tools = toolset(repo)
    model = ScriptedModel([PLAN, source(), lambda m: evaluate(m, sufficient=False, candidate=False),
        lambda m: review(m, candidate=False)])
    result = asyncio.run(CodeComprehensionAgent(model, CodeComprehensionConfig(
        max_total_tokens=300_000, max_tool_calls=1)).run(tools))
    assert result.termination_reason == "tool_call_limit"
    assert result.critical_review is not None and result.tool_calls == 1 and not result.findings


def test_expired_time_limit_prevents_provider_calls(repo, monkeypatch):
    monkeypatch.setattr(CodeComprehensionAgent.execution_type, "remaining_seconds", lambda self: 0)
    result, model, _ = run_agent(repo)
    assert result.termination_reason == "time_limit"
    assert not model.history and not result.findings


def test_provider_failure_retains_inspected_bytes(repo):
    tools = toolset(repo)
    model = ScriptedModel([PLAN, source(), ValueError("simulated provider failure")])
    result = asyncio.run(CodeComprehensionAgent(model, CodeComprehensionConfig(max_total_tokens=300_000)).run(tools))
    assert result.termination_reason == "model_or_schema_error"
    assert result.evidence and not result.findings
    assert result.hypotheses[0].status == "inconclusive"


def test_provider_history_compaction_keeps_cited_source(repo):
    tools = toolset(repo)
    model = ScriptedModel([])
    execution = CodeComprehensionAgent.execution_type(model, CodeComprehensionConfig(), tools, CodeComprehensionRequest())
    tools.execute("get_source_excerpt", {"path": "component.py", "start_line": 1, "end_line": 11}, tool_call_id="read")
    from langchain_core.messages import ToolMessage

    record = execution.references()[0]
    state = execution.initial_state()
    state["hypotheses"] = [CodeComprehensionAgent.execution_type.plan_schema.model_validate(PLAN).hypotheses[0].model_copy(
        update={"evidence_ids": [record.id]})]
    state["messages"] = [source(), ToolMessage(content=json.dumps({"evidence": [record.model_dump()], "data": {"content": "inspected body"}}),
        name="get_source_excerpt", tool_call_id="source"), AIMessage(content="Continue")]
    history = execution.provider_history(state, [], overhead_characters=1_000_000)
    assert "inspected body" in history[1].content
    assert "history_compacted" not in state["messages"][1].content


@pytest.mark.parametrize("output_mode", ["raw", "readable"])
def test_standalone_runner_prints_result_and_closes_client(repo, monkeypatch, capsys, output_mode):
    path = Path(__file__).with_name("run_code_comprehension.py")
    spec = importlib.util.spec_from_file_location("comprehension_demo", path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    model = ScriptedModel([PLAN, source(), AIMessage(content="Ready"), evaluate, review])
    monkeypatch.setattr(runner, "load_test_model", lambda _: (model, ModelSettings(provider="openai", name="offline", temperature=0, max_tokens=4000)))
    closed = []

    async def close(wrapper):
        closed.append(wrapper.llm)
    monkeypatch.setattr(runner, "close_model_clients", close)
    args = SimpleNamespace(repository=str(repo), request=None, config=None, agent_config="dummy", max_files=20, output=output_mode)
    asyncio.run(runner.run(args))
    text = capsys.readouterr().out
    if output_mode == "raw":
        output = json.loads(text)
        assert output["findings"] and output["evidence"] and output["termination_reason"] == "sufficient_evidence"
    else:
        assert "HALLAZGOS ACEPTADOS (1)" in text and "component.py:1–11" in text
        assert "CONCLUSIÓN" in text and "sufficient_evidence" in text
    assert closed == [model]
