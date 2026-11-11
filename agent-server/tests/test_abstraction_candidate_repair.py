"""Repair pack keeps a model close valid when its citations are drawable, not invented."""

import asyncio

from test_abstraction_doc_driven_investigation import (
    SequenceModel,
    llm_repository,
    requirement_assessments,
)

from server.agents.architecture_context import ArchitectureContextResult
from server.agents.maintainability.v2.reusability.abstraction_doc_driven import (
    AbstractionConfig,
    AbstractionRequest,
)
from server.agents.maintainability.v2.reusability.abstraction_doc_driven.execution import (
    AbstractionExecution,
)


def documentary_context():
    return ArchitectureContextResult.model_validate({
        "schema_version": "1",
        "document_index": {"index_id": "index-sha", "repository_id": "repo", "commit": "a" * 40},
        "knowledge": [
            {
                "category": "interfaces_and_contracts",
                "subject": "LlmProvider",
                "statement": "LlmProvider is the contract every LLM backend implements.",
                "related_subjects": [],
                "certainty": "explicit",
                "section_ids": ["section-1"],
                "reasoning": "The document declares the abstraction.",
                "constraint": "unspecified",
                "evidence": [{"section_id": "section-1", "start_line": 2, "end_line": 4, "quote": "LlmProvider"}],
            },
            {
                "category": "architectural_decisions",
                "subject": "LlmProvider",
                "statement": "The project abstracts model transport behind LlmProvider.",
                "related_subjects": [],
                "certainty": "explicit",
                "section_ids": ["section-1"],
                "reasoning": "The document decides the abstraction boundary.",
                "constraint": "unspecified",
                "evidence": [{"section_id": "section-1", "start_line": 10, "end_line": 12, "quote": "LlmProvider"}],
            },
        ],
        "knowledge_issues": [],
        "covered_categories": [],
        "pending_categories": [],
        "evaluated_categories": [],
        "coverage_assessment_status": "not_run",
        "consulted_documents": [],
        "section_paths": {"section-1": "docs/architecture.md"},
        "validation_errors": [],
        "execution_status": "partial",
        "finalization_reason": "test",
    })


def test_close_with_log_failures_is_repaired_not_rejected(tmp_path):
    """Uncited components dropped with a note; bare supported claim downgraded; contradicted claim auto-linked."""
    tools = llm_repository(tmp_path)

    def close(context):
        source = [item for item in context["evidence"] if item["kind"] == "source"]
        assert source, "initial evidence must deliver source at investigation start"
        provider = next((item for item in source if item["path"] == "src/llm/provider.py"), source[0])
        implementer = next((item for item in source if item["path"] == "src/llm/gemini.py"), source[0])
        assessment_evidence = [provider["id"], implementer["id"]]
        return {
            "action": "close",
            "queries": [],
            "conclusion": {
                "investigation_id": context["investigation"]["id"],
                "status": "finding_candidate",
                "summary": "Log replay: the contract fails to exclude backend-specific coupling.",
                "justification": "The implementer depends on concrete internals the contract cannot exclude.",
                "components": [
                    "src/llm/provider.py",
                    "src/app/gateway.py",
                    "src/llm/uninspected.py",
                ],
                "symbol_ids": [], "relationship_ids": [],
                "evidence_ids": assessment_evidence,
                "candidates": [{
                    "id": "candidate-1",
                    "title": "Log-replay candidate",
                    "description": "Consumer depends on implementation details.",
                    "criterion_id": "abstraction-purpose",
                    "kind": "design_observation",
                    "components": ["src/llm/provider.py", "src/llm/uninspected.py"],
                    "evidence_ids": assessment_evidence,
                    "justification": "Implementer fails the shared contract.",
                    "modularity_impact": "Substitutability lost.",
                    "severity": "medium",
                    "confidence": 0.7,
                    "recommendation": "Restore the contract boundary.",
                    "guarantees": ["substitutability"],
                    "implementers": ["src/llm/gemini.py"],
                    "consumers": [],
                }],
                "claim_assessments": [
                    {"claim_id": "claim-0", "status": "contradicted",
                        "rationale": "The contract does not exclude backend-specific coupling.",
                        "code_evidence_ids": assessment_evidence,
                        "scope_paths": ["src/llm/provider.py"]},
                    {"claim_id": "claim-1", "status": "supported",
                        "rationale": "The interface is declared."},
                ],
                "evidence_assessments": requirement_assessments(context),
            },
        }

    model = SequenceModel([close])
    request = AbstractionRequest(documented_architecture=documentary_context())
    execution = AbstractionExecution(model, AbstractionConfig(), tools, request)
    state = execution.initial_state()
    state = {**state, **asyncio.run(execution.plan_investigation(state))}

    async def loop():
        while True:
            route = execution.route_investigation(state)
            if route == "tools":
                state.update(**(await execution.execute_investigation_tools(state)))
            elif route == "investigate":
                state.update(**(await execution.investigate(state)))
            else:
                return state

    final = asyncio.run(loop())
    result = final["result"]
    conclusion = result.investigation_results[0]
    assert conclusion.status == "finding_candidate"
    # Uncited components were pruned with a note.
    assert "src/llm/uninspected.py" not in conclusion.components
    assert any("components not backed" in note for note in conclusion.limitations)
    assert conclusion.candidates and conclusion.candidates[0].document_claim_ids == ["claim-0"]
    # Bare supported claim was downgraded instead of invalidating the close.
    supported = next(item for item in conclusion.claim_assessments if item.claim_id == "claim-1")
    assert supported.status == "inconclusive"
    assert supported.limitations
