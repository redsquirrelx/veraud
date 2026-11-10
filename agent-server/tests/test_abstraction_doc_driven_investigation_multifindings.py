"""Multiple findings per investigation are preserved end to end."""

import asyncio

from server.agents.maintainability.v2.reusability.abstraction_doc_driven import (
    AbstractionConfig,
    AbstractionRequest,
)
from server.agents.maintainability.v2.reusability.abstraction_doc_driven.execution import (
    AbstractionExecution,
)
from tests.test_abstraction_doc_driven_investigation import (
    SequenceModel,
    llm_repository,
    requirement_assessments,
)


def double_candidate(context):
    evidence = context["evidence"]
    provider_ids = [item["id"] for item in evidence if item["path"] == "src/llm/provider.py"]
    gemini_ids = [item["id"] for item in evidence if item["path"] == "src/llm/gemini.py"]
    gateway_ids = [item["id"] for item in evidence if item["path"] == "src/app/gateway.py"]
    gemini = gemini_ids[0] if gemini_ids else provider_ids[0]
    gateway = gateway_ids[0] if gateway_ids else provider_ids[0]

    def candidate(identifier, path, ev, guarantees, implementers):
        return {
            "id": identifier,
            "title": f"Candidate for {identifier}",
            "description": "Candidate abstraction not delivering its contract purpose.",
            "criterion_id": "abstraction-purpose",
            "kind": "design_observation",
            "components": [path],
            "evidence_ids": [ev],
            "justification": "Evidence shows the implementer depends on contract surface but also on internals.",
            "modularity_impact": "low",
            "severity": "low",
            "confidence": 0.6,
            "recommendation": "Choose a narrower dependency edge or abstract the internal helper.",
            "guarantees": guarantees,
            "implementers": implementers,
            "consumers": [] if implementers else ["src/app/gateway.py"],
            "symbol_ids": [],
            "relationship_ids": [],
            "document_claim_ids": [],
        }

    return {"action": "close", "queries": [], "conclusion": {
        "investigation_id": context["investigation"]["id"],
        "status": "finding_candidate",
        "summary": "Two abstraction candidates emerged from the inspected evidence.",
        "justification": "Deterministic offline model; two independent abstraction candidates observed.",
        "components": ["src/llm/provider.py", "src/llm/gemini.py"],
        "symbol_ids": [], "relationship_ids": [],
        "evidence_ids": provider_ids + gemini_ids + gateway_ids,
        "candidates": [
            candidate("abstraction-candidate-1", "src/llm/gemini.py", gemini,
                ["substitutability"], ["src/llm/gemini.py"]),
            candidate("abstraction-candidate-2", "src/app/gateway.py", gateway,
                ["encapsulation"], []),
        ],
        "limitations": [], "claim_assessments": [],
        "evidence_assessments": requirement_assessments(context)}}


def test_finding_candidate_allows_multiple_findings_per_investigation(tmp_path):
    tools = llm_repository(tmp_path)
    model = SequenceModel([double_candidate])

    execution = AbstractionExecution(model, AbstractionConfig(), tools, AbstractionRequest())

    async def run():
        current = execution.initial_state()
        current = {**current, **await execution.plan_investigation(current)}
        while True:
            route = execution.route_investigation(current)
            if route == "tools":
                current = {**current, **await execution.execute_investigation_tools(current)}
            elif route == "investigate":
                current = {**current, **await execution.investigate(current)}
            else:
                return current

    result = asyncio.run(run())

    conclusion = result["result"].investigation_results[0]
    assert conclusion.status == "finding_candidate"
    assert len(conclusion.candidates) == 2
    assert {candidate.id for candidate in conclusion.candidates} == {
        "abstraction-candidate-1", "abstraction-candidate-2"}
    hypothesis = result["result"].hypotheses[0]
    assert hypothesis.status == "confirmed"


def test_synthesis_finalize_produces_provisional_findings(tmp_path):
    tools = llm_repository(tmp_path)
    model = SequenceModel([double_candidate])

    execution = AbstractionExecution(model, AbstractionConfig(), tools, AbstractionRequest())

    async def run():
        current = execution.initial_state()
        current = {**current, **await execution.plan_investigation(current)}
        while True:
            route = execution.route_investigation(current)
            if route == "tools":
                current = {**current, **await execution.execute_investigation_tools(current)}
            elif route == "investigate":
                current = {**current, **await execution.investigate(current)}
            else:
                break
        current = {**current, **execution.synthesis(current)}
        current = {**current, **execution.finalize(current)}
        return current

    result = asyncio.run(run())

    findings = result["result"].findings
    assert {finding.id for finding in findings} == {"abstraction-candidate-1", "abstraction-candidate-2"}
    assert {finding.validation_status for finding in findings} == {"insufficient_evidence"}
    assert all(finding.criterion.id == "abstraction-purpose" for finding in findings)
    assert result["result"].documentary_synthesis["selected_claims"] == 0
    assert "abstraction-candidate-1" in result["result"].candidate_origins
    assert "abstraction-candidate-2" in result["result"].candidate_origins
    assert result["result"].termination_reason == "investigations_completed"
    assert result["result"].candidate_origins
    assert result["result"].missing_information == []

