"""Registration, graph and planning-contract tests for the parametrization shell."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from pydantic_core import PydanticCustomError

from config.agents.catalog import describe_agent_config
from server.agents.architecture_context.schemas import (
    ArchitectureContextResult,
    KnowledgeClaim,
    KnowledgeEvidence,
)
from server.agents.maintainability.v2.reusability.coordinator.registry import (
    registered_investigators,
)
from server.agents.maintainability.v2.reusability.reuse_parametrization_doc_driven import (
    ReuseParametrizationConfig,
    ReuseParametrizationDocDrivenAgent,
    ReuseParametrizationDocDrivenRequest,
    ReuseParametrizationDocDrivenResult,
)
from server.agents.maintainability.v2.reusability.reuse_parametrization_doc_driven.planning import (
    build_parametrization_plan,
)
from server.agents.maintainability.v2.reusability.reuse_parametrization_doc_driven.schemas import (
    ParametrizationCandidate,
    ParametrizationEvidenceAssessment,
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
        raise AssertionError("an empty variation menu must not call the model")


class GenerationModel:
    def __init__(self):
        self.contexts = []

    def bind_tools(self, _tools):
        return self

    def _selection(self, payload):
        questions = {}
        for item in payload["candidates"]:
            primary = item["primary_component"]
            questions[item["id"]] = (
                f"Can callers of {primary} select the documented capability through its mechanism "
                f"without modifying {primary}?"
            )
        return {"candidate_ids": [item["id"] for item in payload["candidates"]], "questions": questions}

    @staticmethod
    def _investigation_refs(payload):
        references = []
        source_ids = []
        visible_symbol_ids = []
        for evidence in payload["evidence"]:
            record = {"id": evidence[0], "path": evidence[1], "kind": evidence[2]}
            if evidence[2] == "source":
                record.update({"lines": evidence[3:5], "symbol_ids": evidence[5]})
                source_ids.append(record["id"])
                visible_symbol_ids.extend(record["symbol_ids"])
            references.append(record)
        return references, source_ids, visible_symbol_ids

    @classmethod
    def _investigation_response(cls, payload):
        task = payload["investigation"]
        references, source_ids, visible_symbol_ids = cls._investigation_refs(payload)
        components = list(dict.fromkeys(record["path"] for record in references))
        assessments = [{
            "claim_id": claim_id,
            "status": "supported",
            "rationale": "The delivered source shows the supplied variation mechanism and its alternatives.",
            "code_evidence_ids": source_ids,
            "scope_paths": components[:1],
            "limitations": [],
        } for claim_id in task["document_claim_ids"]]
        evidence_assessments = [{
            "requirement_index": index,
            "status": "resolved",
            "rationale": "The delivered source resolves this supplied capability obligation.",
            "evidence_ids": source_ids,
            "scope_paths": components[:1],
        } for index, _requirement in enumerate(task["evidence_requirements"])]
        alternatives = task["alternatives"] or task["variation_mechanism"].split()
        candidate_id = f"candidate-{task['id']}"
        return {
            "action": "close",
            "queries": [],
            "conclusion": {
                "investigation_id": task["id"],
                "status": "finding_candidate",
                "summary": f"The delivered source supports {task['variation_mechanism']} reuse selection.",
                "justification": "Contrast the documented variation with the inspected capability frontier; this is a bounded observation, not a global compliance claim.",
                "components": components,
                "symbol_ids": visible_symbol_ids,
                "relationship_ids": list(dict.fromkeys(
                    identifier
                    for item in payload["tool_results"]
                    if item["tool_name"] == "list_relationships"
                    for identifier in [row["id"] for row in item.get("data", {}).get("items", [])]
                )),
                "evidence_ids": source_ids,
                "selection_phase": "startup",
                "selection_sites": components[:1],
                "consumer_impact": "not_required",
                "candidates": [{
                    "id": candidate_id,
                    "title": f"Parametrize {task['variation_mechanism']}",
                    "description": "The behavior can be selected through the documented variation surface.",
                    "criterion_id": "parametrized-reuse",
                    "kind": "design_observation",
                    "components": components,
                    "evidence_ids": source_ids,
                    "justification": "The delivered source names the variation mechanism and alternatives.",
                    "modularity_impact": "Changes the consumers of the selected behavior instead of the component implementation.",
                    "severity": "info",
                    "confidence": 0.8,
                    "recommendation": "Preserve the documented selector as an explicit compatibility surface.",
                    "variation_mechanism": task["variation_mechanism"],
                    "selected_alternatives": alternatives,
                    "implementations": [],
                    "consumers": [],
                    "symbol_ids": visible_symbol_ids,
                    "relationship_ids": [],
                    "document_claim_ids": task["document_claim_ids"],
                }],
                "limitations": [],
                "claim_assessments": assessments,
                "evidence_assessments": evidence_assessments,
            },
        }

    async def ainvoke(self, messages, **_kwargs):
        payload = json.loads(messages[1].content)
        self.contexts.append(payload)
        if "investigation" in payload:
            response = self._investigation_response(payload)
            return AIMessage(content=json.dumps(response),
                usage_metadata={"input_tokens": 40, "output_tokens": 30, "total_tokens": 70})
        if "candidates" in payload:
            response = self._selection(payload)
            return AIMessage(content=json.dumps(response),
                usage_metadata={"input_tokens": 40, "output_tokens": 30, "total_tokens": 70})
        raise AssertionError("Unexpected planning payload: " + json.dumps(payload)[:200])


class UnknownSelectionModel(GenerationModel):
    @staticmethod
    def _investigation_response(payload):
        response = GenerationModel._investigation_response(payload)
        response["conclusion"]["selection_phase"] = "unknown"
        response["conclusion"]["selection_sites"] = []
        return response


def empty_context():
    return ArchitectureContextResult(
        document_index=None,
        knowledge=[],
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


def success_status_claim(**changes):
    return variation_claim(
        subject="RouteHandlerConfig",
        statement="RouteHandlerConfig provides an optional successStatus field that callers may override.",
        related_subjects=["successStatus"],
        evidence=[{"section_id": "section-1", "start_line": 9, "end_line": 10, "quote": "successStatus"}],
    ) | changes


def provider_claim(**changes):
    return variation_claim(
        subject="LlmProvider",
        statement="The adapters for LlmProvider are EchoLlmProvider or a configurable ProviderProvider chosen by configuration.",
        related_subjects=["EchoLlmProvider", "ProviderProvider"],
        evidence=[{"section_id": "section-1", "start_line": 12, "end_line": 13, "quote": "EchoLlmProvider"}],
    ) | changes


def fixed_claim(**changes):
    return variation_claim(
        subject="ESLint",
        statement="A static automated verification rule in ESLint is configured as a warning on Prisma imports.",
        related_subjects=["eslint.config"],
        evidence=[{"section_id": "section-1", "start_line": 15, "end_line": 16, "quote": "no-restricted-imports"}],
    ) | changes


def hierarchy_claim(**changes):
    return variation_claim(
        subject="DomainError",
        statement="DomainError defines a fixed typed exception hierarchy for domain failures.",
        related_subjects=["NotFoundError", "ConflictError", "ValidationError"],
        evidence=[{"section_id": "section-1", "start_line": 17, "end_line": 18, "quote": "DomainError"}],
    ) | changes


def documentary_context(claims):
    return ArchitectureContextResult.model_validate({
        "schema_version": "1",
        "document_index": {"index_id": "index-parametrization", "repository_id": "repo", "commit": "a" * 40},
        "knowledge": claims,
        "knowledge_issues": [],
        "covered_categories": [],
        "pending_categories": [],
        "evaluated_categories": [],
        "coverage_assessment_status": "not_run",
        "consulted_documents": [],
        "section_paths": {"section-1": "docs/architecture.md"},
        "validation_errors": [],
        "execution_status": "partial",
        "finalization_reason": "partial_context",
    })


def variation_claim(**changes):
    return {
        "category": "interfaces_and_contracts",
        "subject": "create_api_handler",
        "statement": "create_api_handler accepts either a validation function or a Zod schema through schema.",
        "related_subjects": ["schema"],
        "certainty": "explicit",
        "section_ids": ["section-1"],
        "reasoning": "The architecture document names the variation boundary.",
        "constraint": "unspecified",
        "evidence": [{"section_id": "section-1", "start_line": 2, "end_line": 4, "quote": "schema"}],
    } | changes


def toolset(root):
    root.mkdir(exist_ok=True)
    (root / "handler.py").write_text(
        "class RouteHandlerConfig:\n"
        "    pass\n\n"
        "def create_api_handler(schema, require_auth=None, permission=None, success_status=200):\n"
        "    return schema, require_auth, permission, success_status\n",
        encoding="utf-8",
    )
    (root / "llm.py").write_text(
        "class LlmProvider:\n"
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


def test_configuration_and_reusability_catalog_registration():
    assert describe_agent_config("reuse_parametrization_doc_driven")["agent_id"] == "reuse_parametrization_doc_driven"
    assert ReuseParametrizationConfig().max_planned_investigations == 16
    assert ReuseParametrizationConfig().max_documentary_claims_per_candidate == 6
    spec = registered_investigators()["reuse_parametrization_doc_driven"]

    assert spec.agent_class is ReuseParametrizationDocDrivenAgent
    assert spec.request_class is ReuseParametrizationDocDrivenRequest
    assert spec.result_class is ReuseParametrizationDocDrivenResult
    assert spec.completed_reasons == ()
    assert spec.capability.id == "reuse_parametrization_doc_driven"


def test_graph_extends_through_investigation(tmp_path):
    request = ReuseParametrizationDocDrivenRequest()
    execution = ReuseParametrizationDocDrivenAgent.execution_type(
        UnexpectedModel(), ReuseParametrizationConfig(max_model_calls=4),
        toolset(tmp_path), request)

    node_names = set(execution.graph.get_graph().nodes)

    assert "plan_investigation" in node_names
    assert "investigate" in node_names
    assert "tools" in node_names
    assert "synthesize" not in node_names
    assert "finalize" not in node_names


def test_debug_output_reports_menu_raw_response_and_selection(tmp_path, capsys):
    request = ReuseParametrizationDocDrivenRequest(documented_architecture=documentary_context([variation_claim()]))
    result = asyncio.run(ReuseParametrizationDocDrivenAgent(
        GenerationModel(), ReuseParametrizationConfig(max_model_calls=4)).run(
            toolset(tmp_path), request))

    captured = capsys.readouterr().err
    assert result.model_calls == 2
    assert "[DEBUG_PLAN_MENU]" in captured
    assert "[DEBUG_PLAN_MENU_CANDIDATE]" in captured
    assert "[DEBUG_PLAN_SELECTION]" in captured
    assert "[DEBUG_LLM_RAW plan_investigation]" in captured
    assert '"candidate_ids"' in captured
    assert "[DEBUG_INVESTIGATE_CONTEXT]" in captured
    assert result.status == "investigation_completed"
    assert len(result.investigation_results) == len(result.plan.candidates)


def test_empty_context_is_valid_and_needs_no_model_call(tmp_path):
    request = ReuseParametrizationDocDrivenRequest(documented_architecture=empty_context())
    result = asyncio.run(ReuseParametrizationDocDrivenAgent(
        UnexpectedModel(), ReuseParametrizationConfig(max_model_calls=4)).run(
            toolset(tmp_path), request))

    assert isinstance(result, ReuseParametrizationDocDrivenResult)
    assert result.status == "investigation_completed"
    assert result.termination_reason == "investigations_completed"
    assert result.plan.hypotheses == []
    assert result.investigation_results == []
    assert result.plan.hypotheses == []
    assert result.findings == []
    assert result.model_calls == 0
    assert result.tool_calls == 0
    assert result.planning_diagnostics["documentary_context_supplied"] is True


def investigation_execution(tmp_path):
    request = ReuseParametrizationDocDrivenRequest(documented_architecture=empty_context())
    execution = ReuseParametrizationDocDrivenAgent.execution_type(
        UnexpectedModel(), ReuseParametrizationConfig(max_model_calls=4), toolset(tmp_path), request)
    candidate = ParametrizationCandidate(
        id="candidate-scope-test",
        priority="medium",
        scope=["handler.py"],
        primary_component="handler.py",
        variation_mechanism="schema validation",
        alternatives=["validation function", "Zod schema"],
        documented_capability="Handler selects schema validation mode.",
        variation_basis="explicit",
        initial_locations=["handler.py"],
        observed_indicators=["Handler accepts a schema parameter."],
        question="Can handler.py use schema validation to choose the alternative?",
        evidence_needed=["Inspect handler.py for schema selection.", "Inspect one selection site."],
        document_claim_ids=[],
    )
    plan = ParametrizationPlan(
        objectives=[request.objective], components=["handler.py"],
        hypotheses=[Hypothesis(id=candidate.id, question=candidate.question,
            criterion_id="parametrized-reuse", priority="medium",
            evidence_needed=candidate.evidence_needed)],
        candidates=[candidate], limitations=[], document_claims={})
    return request, execution, execution.initial_state() | {"plan": plan}


def test_investigation_context_uses_compact_provenance(tmp_path):
    _request, execution, state = investigation_execution(tmp_path)
    candidate = state["plan"].candidates[0]
    pending = execution._initial_queries(candidate)

    result = asyncio.run(execution.execute_investigation_tools({**state, "pending_queries": pending,
        "initial_evidence_loaded": True}))
    context = execution._investigation_context({**state, **result, "pending_queries": []})

    assert "visible_symbol_ids" not in context
    assert "query_inventory" not in context
    assert "reusable_queries" not in context
    assert all(len(item) >= 3 for item in context["evidence"])
    assert all(set(item) <= {"id", "description"} for item in context["criteria"])
    assert all(set(item) <= {"t", "a", "s", "e"} for item in context["query_history"])


def test_invalid_scope_query_does_not_discard_valid_queries(tmp_path):
    _request, execution, state = investigation_execution(tmp_path)
    turn = ParametrizationInvestigationTurn(action="tools", queries=[
        ParametrizationToolQuery(tool="get_source_excerpt",
            arguments={"path": "handler.py", "start_line": 1, "end_line": 20},
            reason="Inspect in-scope capability selection."),
        ParametrizationToolQuery(tool="get_source_excerpt",
            arguments={"path": "tests/test_handler.py", "start_line": 1, "end_line": 20},
            reason="An omitted expansion reason is invalid."),
    ])

    prepared = execution.prepare_structured_result("investigate", turn, state)

    assert [query.arguments["path"] for query in prepared.queries] == ["handler.py"]
    assert any("discarded invalid query" in issue for issue in execution.issues)


def test_explicit_scope_expansion_keeps_the_query(tmp_path):
    _request, execution, state = investigation_execution(tmp_path)
    turn = ParametrizationInvestigationTurn(action="tools", queries=[
        ParametrizationToolQuery(tool="find_symbols",
            arguments={"file_path": "tests/test_handler.py", "limit": 10},
            reason="Verify the exact test boundary for the selection contract.",
            scope_expansion="The handler's declared schema boundary is exercised by this otherwise out-of-scope test file."),
    ])

    prepared = execution.prepare_structured_result("investigate", turn, state)

    assert [query.arguments["file_path"] for query in prepared.queries] == ["tests/test_handler.py"]


def test_definitive_close_requires_a_classified_selection_phase(tmp_path):
    request = ReuseParametrizationDocDrivenRequest(
        documented_architecture=documentary_context([variation_claim()]))

    result = asyncio.run(ReuseParametrizationDocDrivenAgent(
        UnknownSelectionModel(), ReuseParametrizationConfig(max_model_calls=8)).run(
            toolset(tmp_path), request))

    assert result.status == "investigation_completed"
    assert result.investigation_results
    assert result.investigation_results[0].status == "inconclusive"


def test_documentary_success_status_and_provider_selection_are_investigated(tmp_path):
    alpha = documentary_context([success_status_claim(), provider_claim()])
    request = ReuseParametrizationDocDrivenRequest(documented_architecture=alpha)
    model = GenerationModel()

    result = asyncio.run(ReuseParametrizationDocDrivenAgent(
        model, ReuseParametrizationConfig(max_model_calls=4)).run(
            toolset(tmp_path), request))

    assert {item.primary_component for item in result.plan.candidates} == {
        "handler.py",
        "llm.py",
    }
    assert result.model_calls == 3


def test_static_claims_are_excluded_without_relaxing_valid_variants(tmp_path):
    document = documentary_context([
        variation_claim(),
        variation_claim(
            statement="create_api_handler exposes requireAuth and permission through configurable options.",
            related_subjects=["permission", "requireAuth"],
        ),
        fixed_claim(),
        hierarchy_claim(),
    ])
    request = ReuseParametrizationDocDrivenRequest(documented_architecture=document)

    result = asyncio.run(ReuseParametrizationDocDrivenAgent(
        GenerationModel(), ReuseParametrizationConfig(max_model_calls=4)).run(
            toolset(tmp_path), request))

    assert [item.primary_component for item in result.plan.candidates] == ["handler.py"]
    assert result.model_calls == 2
    candidate = result.plan.candidates[0]
    assert set(candidate.document_claim_ids) == {"claim-0", "claim-1"}
    assert set(result.plan.document_claims) == {"claim-0", "claim-1"}
    assert "ESLint" not in json.dumps([record.claim.subject for record in result.plan.document_claims.values()])
    assert "DomainError" not in json.dumps([record.claim.subject for record in result.plan.document_claims.values()])


def test_initial_locations_are_bounded_to_ten(tmp_path):
    from types import SimpleNamespace

    def file(identifier, path):
        return SimpleNamespace(id=identifier, path=path, module_name=None, project_id="p", language="python", size_bytes=1, status="processed")

    files = [file("f0", "handler.py"), *(file(f"c{index}", f"consumer_{index}.py") for index in range(18))]
    relationships = [SimpleNamespace(source_id=f"c{index}", target_id="f0", resolution="internal") for index in range(18)]
    claim = KnowledgeClaim(
        category="interfaces_and_contracts",
        subject="handler",
        statement="handler supports HTTP 200 and HTTP 201.",
        related_subjects=["successStatus"],
        certainty="explicit",
        section_ids=["section-1"],
        reasoning="Extracted documentary obligation.",
        constraint="unspecified",
        evidence=[KnowledgeEvidence(section_id="section-1", start_line=2, end_line=4, quote="successStatus")])
    document = SimpleNamespace(
        knowledge=[claim],
        section_paths={"section-1": "docs/architecture.md"},
        document_index=None,
        consulted_documents=[],
    )
    files_by_path = {item.path: item for item in files}
    module_name = files_by_path["handler.py"]
    module_name.module_name = "handler"
    snapshot = SimpleNamespace(
        files=files, symbols=[], relationships=relationships, testing=[],
        coverage=SimpleNamespace(unsupported_source_languages=[], issues=[]),
        repository=SimpleNamespace(snapshot_hash="abc"),
        projects=[],
    )
    request = ReuseParametrizationDocDrivenRequest().model_copy(update={"documented_architecture": document})

    plan = build_parametrization_plan(snapshot, request,
        check=lambda: None, max_investigations=2)

    assert len(plan.candidates) == 1
    assert len(plan.candidates[0].initial_locations) == 10
    assert plan.candidates[0].initial_locations[0] == "handler.py"



class AbstainingModel(GenerationModel):
    def _selection(self, _payload):
        return {"candidate_ids": [], "questions": {}}


def test_model_abstention_selects_no_variation_questions(tmp_path):
    request = ReuseParametrizationDocDrivenRequest(documented_architecture=documentary_context([
        variation_claim(statement="create_api_handler represents an API handler.", related_subjects=[]),
    ]))
    result = asyncio.run(ReuseParametrizationDocDrivenAgent(
        AbstainingModel(), ReuseParametrizationConfig(max_model_calls=4)).run(
            toolset(tmp_path), request))

    assert result.plan.candidates == []
    assert result.plan.hypotheses == []
    assert result.model_calls == 1
    assert any("abstained" in limitation for limitation in result.limitations)


def test_plan_investigation_selects_bounded_variation_questions(tmp_path):
    document = documentary_context([
        variation_claim(),
        variation_claim(
            statement="create_api_handler exposes requireAuth and permission through configurable options.",
            related_subjects=["permission", "requireAuth"],
            evidence=[{"section_id": "section-1", "start_line": 6, "end_line": 7, "quote": "requireAuth"}],
        ),
    ])
    request = ReuseParametrizationDocDrivenRequest(documented_architecture=document)
    model = GenerationModel()

    result = asyncio.run(ReuseParametrizationDocDrivenAgent(
        model, ReuseParametrizationConfig(max_model_calls=4)).run(
            toolset(tmp_path), request))

    assert result.model_calls == 2
    assert [item.id for item in result.plan.candidates] == [item.id for item in result.plan.hypotheses]
    assert len(result.plan.candidates) == 1
    candidate = result.plan.candidates[0]
    assert candidate.primary_component == "handler.py"
    assert set(candidate.document_claim_ids) == {"claim-0", "claim-1"}
    assert set(result.plan.document_claims) == {"claim-0", "claim-1"}
    assert all("without modifying" in item.question for item in result.plan.hypotheses)
    assert candidate.evidence_needed
    assert model.contexts[0]["candidates"], "plan model must receive the host menu"
    menu_ids = {item["id"] for item in model.contexts[0]["candidates"]}
    assert menu_ids == {candidate.id}
    assert {item["primary_component"] for item in model.contexts[0]["candidates"]} == {"handler.py"}




def delivered_investigation_state(execution, state):
    pending = execution._initial_queries(execution._current(state))
    result = asyncio.run(execution.execute_investigation_tools({**state, "pending_queries": pending,
        "initial_evidence_loaded": True}))
    return {**state, **result, "pending_queries": []}


def test_coverage_recovery_checks_the_source_tool_not_the_component_path(tmp_path):
    request, execution, state = investigation_execution(tmp_path)
    task = execution._current(state)

    queries = execution._coverage_recovery_queries(state, [])

    assert any(query.tool == "get_source_excerpt"
        and query.arguments["path"] == task.primary_component for query in queries)
    disabled = ReuseParametrizationDocDrivenAgent.execution_type(
        UnexpectedModel(), ReuseParametrizationConfig(max_model_calls=4, tools=["list_files"]),
        toolset(tmp_path), request)
    disabled_state = disabled.initial_state() | {"plan": state["plan"]}
    assert disabled._coverage_recovery_queries(disabled_state, []) == []


def test_not_applicable_requires_basis_and_cannot_exclude_code_obligations(tmp_path):
    _request, execution, state = investigation_execution(tmp_path)
    state = delivered_investigation_state(execution, state)
    task = execution._current(state)
    references = {record.id: record for record in execution.references()}
    source_id = next(record.id for record in references.values() if record.kind == "source")

    def codes(assessment, plan=task):
        errors = []
        execution._validate_evidence_requirements(
            SimpleNamespace(status="finding_candidate", evidence_assessments=[assessment]), plan, references, errors)
        return [item["code"] for item in errors]

    resolved_without_scope = ParametrizationEvidenceAssessment(
        requirement_index=0, status="resolved", rationale="The delivered source resolves this obligation.",
        evidence_ids=[source_id], scope_paths=[])
    assert "evidence_requirement_source_required" in codes(resolved_without_scope)

    code_verified_without_source = ParametrizationEvidenceAssessment(
        requirement_index=0, status="not_applicable",
        rationale="The inspected implementation excludes this obligation for the bounded capability.",
        exclusion_basis="code_verified")
    assert "evidence_requirement_source_required" in codes(code_verified_without_source)

    missing_basis = ParametrizationEvidenceAssessment(
        requirement_index=0, status="not_applicable",
        rationale="The inspected implementation excludes this obligation for the bounded capability.")
    assert "evidence_requirement_exclusion_basis_required" in codes(missing_basis)

    excluded_code_obligation = ParametrizationEvidenceAssessment(
        requirement_index=0, status="not_applicable",
        rationale="Documentation availability was confirmed by the architecture owner.",
        exclusion_basis="not_code_dependent")
    assert "evidence_requirement_not_applicable_unjustified" in codes(excluded_code_obligation)

    non_code_task = task.model_copy(update={"evidence_needed": [
        "Documentation availability was confirmed by the architecture owner."]})
    accepted = ParametrizationEvidenceAssessment(
        requirement_index=0, status="not_applicable",
        rationale="Documentation availability was confirmed by the architecture owner.",
        exclusion_basis="not_code_dependent")
    assert codes(accepted, non_code_task) == []


def finding_turn(execution, state, *, candidate_changes=None, conclusion_changes=None):
    task = execution._current(state)
    source = next(record for record in execution.references()
        if record.kind == "source" and record.path == task.primary_component)
    evidence_ids = [source.id]
    components = [task.primary_component]
    candidate = {
        "id": "finding-1",
        "title": "Primary component contradicts the variation contract",
        "description": "Inspected source shows consumers cannot select the documented alternative.",
        "criterion_id": "parametrized-reuse",
        "kind": "design_observation",
        "components": components,
        "evidence_ids": evidence_ids,
        "justification": "The inspected primary component contradicts the documented variation contract.",
        "modularity_impact": "Consumers must change implementation code to select the alternative.",
        "severity": "info",
        "confidence": 0.7,
        "recommendation": "Expose the variation through the declared contract.",
        "variation_mechanism": task.variation_mechanism,
        "selected_alternatives": ["validation function"],
        "implementations": [],
        "consumers": [],
        "symbol_ids": [],
        "relationship_ids": [],
        "document_claim_ids": [],
    }
    candidate.update(candidate_changes or {})
    conclusion = {
        "investigation_id": task.id,
        "status": "finding_candidate",
        "summary": "The primary component violates substitutability.",
        "justification": "Inspected source establishes the contract violation and its impact.",
        "components": components,
        "symbol_ids": [],
        "relationship_ids": [],
        "evidence_ids": evidence_ids,
        "selection_phase": "startup",
        "selection_sites": components,
        "consumer_impact": "not_required",
        "candidates": [candidate],
        "limitations": [],
        "claim_assessments": [],
        "evidence_assessments": [{
            "requirement_index": index,
            "status": "resolved",
            "rationale": "The delivered primary source resolves this obligation.",
            "evidence_ids": evidence_ids,
            "scope_paths": components,
        } for index, _requirement in enumerate(task.evidence_needed)],
    }
    conclusion.update(conclusion_changes or {})
    return ParametrizationInvestigationTurn.model_validate(
        {"action": "close", "queries": [], "conclusion": conclusion})


def test_finding_may_be_supported_by_the_primary_component_alone(tmp_path):
    (tmp_path / "consumer.py").write_text("from handler import create_api_handler\n", encoding="utf-8")
    _request, execution, state = investigation_execution(tmp_path)
    candidate = state["plan"].candidates[0].model_copy(update={
        "scope": ["handler.py", "consumer.py"],
        "initial_locations": ["handler.py", "consumer.py"]})
    state = {**state, "plan": state["plan"].model_copy(update={"candidates": [candidate]})}
    state = delivered_investigation_state(execution, state)

    prepared = execution.prepare_structured_result("investigate", finding_turn(execution, state), state)

    assert prepared.conclusion.status == "finding_candidate"
    assert prepared.conclusion.candidates[0].components == ["handler.py"]


def test_validation_accumulates_field_and_index_diagnostics(tmp_path):
    _request, execution, state = investigation_execution(tmp_path)
    state = delivered_investigation_state(execution, state)
    source = next(record for record in execution.references()
        if record.kind == "source" and record.path == "handler.py")
    turn = finding_turn(execution, state,
        candidate_changes={"implementations": ["consumer.py"]},
        conclusion_changes={"selection_phase": "unknown", "selection_sites": [],
            "consumer_impact": "not_verified",
            "evidence_assessments": [
                {"requirement_index": 0, "status": "resolved",
                 "rationale": "The delivered source resolves this obligation.",
                 "evidence_ids": [source.id], "scope_paths": []},
                {"requirement_index": 1, "status": "not_applicable",
                 "rationale": "Documentation availability was confirmed by the architecture owner.",
                 "exclusion_basis": None},
            ]})

    with pytest.raises(PydanticCustomError):
        execution.prepare_structured_result("investigate", turn, state)

    codes = {item["code"] for item in execution._last_validation_errors}
    assert {"selection_phase_unresolved", "consumer_impact_unresolved",
        "uninspected_variation_scope", "evidence_requirement_source_required",
        "evidence_requirement_exclusion_basis_required"} <= codes
    context = execution.structured_correction_context("investigate", state)
    assert context["validation_errors"] == execution._last_validation_errors
    assert all({"code", "field", "message"} <= set(item) for item in context["validation_errors"])


def test_get_evidence_recovers_a_previously_delivered_fragment(tmp_path):
    _request, execution, state = investigation_execution(tmp_path)
    state = delivered_investigation_state(execution, state)
    source = next(record for record in execution.references()
        if record.kind == "source" and record.path == "handler.py")
    query = ParametrizationToolQuery(tool="get_evidence", arguments={"evidence_id": source.id},
        reason="Recover the earlier delivered fragment.")
    _args, key = execution._normalize_query(query, execution._current(state))

    result = asyncio.run(execution.execute_investigation_tools({**state, "pending_queries": [query]}))
    view = result["query_cache"][key]

    assert view["status"] == "ok"
    assert view["tool_name"] == "get_source_excerpt"
    assert view["data"]["path"] == "handler.py"
    assert "create_api_handler" in view["data"]["content"]


def test_context_offers_bounded_recovery_for_older_fragments(tmp_path):
    _request, execution, state = investigation_execution(tmp_path)
    state = delivered_investigation_state(execution, state)

    context = execution._investigation_context({**state, "pending_queries": []})

    assert context["recoverable_evidence"]
    assert any(item["path"] == "handler.py" for item in context["recoverable_evidence"])
    assert all({"id", "path", "start_line", "end_line", "tool", "arguments"}
        <= set(item) for item in context["recoverable_evidence"])
    assert len(context["tool_results"]) <= 2
