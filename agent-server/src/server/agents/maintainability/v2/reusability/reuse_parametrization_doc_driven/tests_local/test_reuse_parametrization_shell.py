"""Registration, graph and planning-contract tests for the parametrization shell."""

import asyncio
import json

from langchain_core.messages import AIMessage

from config.agents.catalog import describe_agent_config
from server.agents.architecture_context.schemas import (
    ArchitectureContextResult,
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
    ConsolidationProposal,
    ParametrizationCandidate,
    ParametrizationConsolidationResponse,
    ParametrizationInvestigationTurn,
    ParametrizationPlan,
    ParametrizationProposal,
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

    def _proposal(self, claims, subject_fragment, path, symbol_name, variation_mechanism, alternatives, claim_ids):
        matching = next(
            claim for claim in claims if subject_fragment.casefold() in claim["subject"].casefold()
        )
        return {
            "primary_component": path,
            "symbol_name": symbol_name,
            "variation_mechanism": variation_mechanism,
            "variation_basis": "explicit",
            "alternatives": alternatives,
            "documented_capability": matching["statement"],
            "question": (
                f"Can {path} use {variation_mechanism} to choose between {', '.join(alternatives)} "
                "without modifying its implementation?"
            ),
            "evidence_needed": [
                f"Inspect `{path}` to determine how `{symbol_name or path}` selects the documented alternatives.",
                (
                    f"Inspect callers of `{symbol_name or path}` in `{path}` to determine how they choose between "
                    f"{alternatives[0]} and {alternatives[1]}."
                ),
            ],
            "document_claim_ids": claim_ids,
        }

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
        if "provisional_candidates" in payload:
            claims = payload["claims"]
            fixed_ids = [claim["id"] for claim in claims
                if "ESLint" in claim.get("subject", "") or "DomainError" in claim.get("subject", "")]
            response = {
                "candidates": payload["provisional_candidates"],
                "exclusions": [{"claim_ids": fixed_ids, "reason": "No selectable variation or alternatives are documented."}] if fixed_ids else [],
                "limitations": [],
            }
            return AIMessage(content=json.dumps(response),
                usage_metadata={"input_tokens": 40, "output_tokens": 30, "total_tokens": 70})
        claims = payload["claims"]
        references = payload["code_references"]
        schema_id = next((claim["id"] for claim in claims if "Zod" in claim["statement"]), None)
        auth_id = next((claim["id"] for claim in claims if "requireAuth" in claim["statement"]), None)
        success_id = next((claim["id"] for claim in claims if "successStatus" in claim["statement"]), None)
        provider_id = next((claim["id"] for claim in claims if "adapters for LlmProvider" in claim["statement"]), None)
        fixed_ids = [claim["id"] for claim in claims if "ESLint" in claim["subject"] or "DomainError" in claim["subject"]]
        code_by_path = {item["path"] for item in references}

        proposals = []
        if "handler.py" in code_by_path:
            if schema_id is not None:
                proposals.append(self._proposal(
                    claims, "create_api_handler", "handler.py", "create_api_handler",
                    "schema validation", ["validation function", "Zod schema"], [schema_id]))
            if auth_id is not None:
                proposals.append(self._proposal(
                    claims, "create_api_handler", "handler.py", "create_api_handler",
                    "requireAuth and permission", ["requireAuth boolean", "permission list"], [auth_id]))
            if success_id is not None:
                proposals.append(self._proposal(
                    claims, "RouteHandlerConfig", "handler.py", "RouteHandlerConfig",
                    "successStatus", ["HTTP 200", "HTTP 201"], [success_id]))
        if "llm.py" in code_by_path and provider_id is not None:
            proposals.append(self._proposal(
                claims, "LlmProvider", "llm.py", "LlmProvider",
                "provider adapter selection", ["MockLlmProvider", "ProviderProvider"], [provider_id]))

        response = {
            "candidates": proposals,
            "exclusions": [{"claim_ids": fixed_ids, "reason": "No selectable variation or alternatives are documented."}] if fixed_ids else [],
            "limitations": [],
        }
        return AIMessage(content=json.dumps(response),
            usage_metadata={"input_tokens": 40, "output_tokens": 30, "total_tokens": 70})


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
        statement="The adapters for LlmProvider are MockLlmProvider or a configurable ProviderProvider chosen by configuration.",
        related_subjects=["MockLlmProvider", "ProviderProvider"],
        evidence=[{"section_id": "section-1", "start_line": 12, "end_line": 13, "quote": "MockLlmProvider"}],
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
    assert result.model_calls == 3
    assert "[DEBUG_PLAN_BATCH]" in captured
    assert "batch=1/1" in captured
    assert "[DEBUG_PLAN_RESPONSE]" in captured
    assert "candidates=1" in captured
    assert "mechanism=schema validation" in captured
    assert "[DEBUG_LLM_RAW plan_investigation]" in captured
    assert '"candidates"' in captured
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

    assert {item.variation_mechanism for item in result.plan.candidates} == {
        "successStatus",
        "provider adapter selection",
    }


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

    assert {item.variation_mechanism for item in result.plan.candidates} == {
        "schema validation",
        "requireAuth and permission",
    }
    assert result.model_calls == 4
    assert any("exclusion" in limitation.casefold() for limitation in result.limitations)


def semantic_planning(claims):
    from types import SimpleNamespace

    claim_records = []
    for index, statement in enumerate(claims):
        claim_records.append({
            "id": f"index-sha:{index}",
            "category": "interfaces_and_contracts",
            "subject": "handler",
            "statement": statement,
            "related_subjects": ["schema", "validation"],
            "certainty": "explicit",
            "constraint": "unspecified",
            "section_ids": ["section-1"],
            "evidence": [{"section_id": "section-1", "start_line": index + 2, "end_line": index + 4, "quote": statement}],
            "document_index": None,
            "section_paths": {"section-1": "docs/architecture.md"},
        })
    planning = {
        "objective": "Test objective",
        "snapshot_hash": "snapshot",
        "claims": claim_records,
        "code_references": [{
            "kind": "file",
            "path": "handler.py",
            "file_id": "file:handler",
            "module_name": "handler",
            "symbol_id": None,
            "symbol_name": None,
            "symbol_kind": None,
        }],
        "consumers_by_path": {"handler.py": []},
        "symbols_by_file": {},
        "files": {"file:handler": SimpleNamespace(id="file:handler", path="handler.py")},
        "max_investigations": 2,
        "limitations": [],
    }
    return planning


def build_schema_proposal(claim_ids, mechanism):
    return ParametrizationProposal(
        primary_component="handler.py",
        variation_mechanism=mechanism,
        variation_basis="explicit",
        alternatives=["validation function", "Zod schema"],
        documented_capability="handler accepts either a validation function or a Zod schema through schema.",
        question="Can handler.py use schema validation to choose between validation function and Zod schema?",
        evidence_needed=[
            "Inspect `handler.py` to verify how the schema parameter accepts validation functions and Zod schemas.",
            "Inspect at least one caller of `handler` in `consumer_0.py` to verify the selected schema mode.",
        ],
        document_claim_ids=claim_ids)


def test_semantically_equivalent_batches_are_consolidated():
    planning = semantic_planning([
        "handler accepts either a validation function or a Zod schema through schema.",
        "handler supports both contracted validation functions and Zod schemas.",
    ])
    response = ParametrizationConsolidationResponse(candidates=[ConsolidationProposal(
        source_proposal_ids=["proposal-1"],
        **build_schema_proposal(["index-sha:0", "index-sha:1"], "schema validation").model_dump())])

    plan = build_parametrization_plan(planning, response)

    assert len(plan.candidates) == 1
    assert set(plan.candidates[0].document_claim_ids) == {"index-sha:0", "index-sha:1"}


def test_initial_locations_are_bounded_to_ten(tmp_path):
    from types import SimpleNamespace

    from server.agents.maintainability.v2.reusability.reuse_parametrization_doc_driven.planning import (
        build_parametrization_plan,
    )

    file_record = SimpleNamespace(id="file:handler", path="handler.py")
    claim = {
        "id": "index-sha:0",
        "category": "interfaces_and_contracts",
        "subject": "handler",
        "statement": "handler supports HTTP 200 and HTTP 201.",
        "related_subjects": ["successStatus"],
        "certainty": "explicit",
        "constraint": "unspecified",
        "section_ids": ["section-1"],
        "evidence": [{"section_id": "section-1", "start_line": 2, "end_line": 4, "quote": "successStatus"}],
        "document_index": None,
        "section_paths": {"section-1": "docs/architecture.md"},
    }
    planning = {
        "objective": "Test objective",
        "snapshot_hash": "snapshot",
        "claims": [claim],
        "code_references": [{
            "kind": "file",
            "path": "handler.py",
            "file_id": "file:handler",
            "module_name": "handler",
            "symbol_id": None,
            "symbol_name": None,
            "symbol_kind": None,
        }],
        "consumers_by_path": {"handler.py": [f"consumer_{index}.py" for index in range(18)]},
        "symbols_by_file": {},
        "files": {"file:handler": file_record},
        "max_investigations": 1,
        "limitations": [],
    }
    response = ParametrizationConsolidationResponse(candidates=[ConsolidationProposal(
        source_proposal_ids=["proposal-1"],
        primary_component="handler.py",
        variation_mechanism="successStatus",
        variation_basis="explicit",
        alternatives=["HTTP 200", "HTTP 201"],
        documented_capability="handler chooses between HTTP 200 and HTTP 201.",
        question="Can handler.py use successStatus to choose between HTTP 200 and HTTP 201?",
        evidence_needed=[
            "Inspect `handler.py` to verify `successStatus` handling.",
            "Inspect at least one caller of `handler` in `consumer_0.py` to verify HTTP 200 or HTTP 201.",
        ],
        document_claim_ids=["index-sha:0"])])

    plan = build_parametrization_plan(planning, response)

    assert len(plan.candidates) == 1
    assert len(plan.candidates[0].initial_locations) == 10
    assert plan.candidates[0].initial_locations[0] == "handler.py"



def test_claim_without_documented_variation_does_not_create_a_question(tmp_path):
    request = ReuseParametrizationDocDrivenRequest(documented_architecture=documentary_context([
        variation_claim(statement="create_api_handler represents an API handler.", related_subjects=[]),
    ]))
    result = asyncio.run(ReuseParametrizationDocDrivenAgent(
        GenerationModel(), ReuseParametrizationConfig(max_model_calls=4)).run(
            toolset(tmp_path), request))

    assert result.plan.candidates == []
    assert result.plan.hypotheses == []
    assert result.model_calls == 1


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

    assert result.model_calls == 4
    assert [item.id for item in result.plan.candidates] == [item.id for item in result.plan.hypotheses]
    assert len(result.plan.candidates) == 2
    assert {item.variation_mechanism for item in result.plan.candidates} == {
        "schema validation",
        "requireAuth and permission",
    }
    assert all(item.primary_component == "handler.py" for item in result.plan.candidates)
    assert all(document.section_paths for item in result.plan.candidates if item.document_claim_ids)
    assert all("without modifying its implementation" in item.question for item in result.plan.hypotheses)
    schema_evidence = next(item for item in result.plan.candidates if item.variation_mechanism == "schema validation").evidence_needed
    auth_evidence = next(item for item in result.plan.candidates if item.variation_mechanism == "requireAuth and permission").evidence_needed
    assert any("validation function" in item for item in schema_evidence)
    assert any("permission" in item and "requireAuth" in item for item in auth_evidence)
    assert schema_evidence != auth_evidence
    assert model.contexts[0]["claims"], "plan model must receive normalized claims"
    assert model.contexts[0]["code_references"], "plan model must receive indexed code references"


