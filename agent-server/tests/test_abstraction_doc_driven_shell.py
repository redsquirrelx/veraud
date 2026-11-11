"""Abstraction agent planning surface and graph contract."""

import asyncio
import json

from langchain_core.messages import AIMessage
from test_abstraction_doc_driven_planning import context
from test_architecture_boundary_planning import tools_for

from config.agents.catalog import describe_agent_config
from server.agents.architecture_context import ArchitectureContextResult
from server.agents.maintainability.v2.reusability.abstraction_doc_driven import (
    AbstractionAgent,
    AbstractionConfig,
    AbstractionRequest,
)
from server.agents.maintainability.v2.reusability.abstraction_doc_driven.execution import (
    AbstractionExecution,
)
from server.agents.maintainability.v2.reusability.coordinator.registry import (
    registered_investigators,
)


class PlanningModel:
    def __init__(self, count=1):
        self.count = count
        self.contexts = []

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages, **kwargs):
        context_message = messages[1].content
        self.contexts.append(json.loads(context_message))
        payload = self.contexts[-1]
        candidates = payload["candidates"][: self.count]
        response = {
            "candidate_ids": [item["id"] for item in candidates],
            "questions": {
                item["id"]: f"Does the abstraction in {item['primary_component']} deliver its purpose "
                    f"for implementations and consumers?" for item in candidates
            },
            "evidence_requirements": {
                item["id"]: [f"{item['abstraction_name']} may fail on substitution when invented payload types cross its boundary",
                    f"{item['abstraction_name']} must behave as a thin contract over its implementations matching its claims"] for item in candidates
            },
        }
        return AIMessage(content=json.dumps(response),
            usage_metadata={"input_tokens": 40, "output_tokens": 20, "total_tokens": 60})


def llm_repository(tmp_path):
    return tools_for(tmp_path, {
        "src/llm/provider.py": "from typing import Protocol\n\nclass LlmProvider(Protocol):\n    def complete(self, prompt): ...\n",
        "src/llm/gemini.py": "class GeminiProvider(LlmProvider):\n    def complete(self, prompt): return 'x'\n",
        "src/app/gateway.py": "from src.llm.provider import LlmProvider\n\nclass Gateway:\n    def use(self, p: LlmProvider):\n        return True\n",
        "src/payments/gateway.py": "from typing import Protocol\n\nclass PaymentGateway(Protocol):\n    def charge(self, amount): ...\n",
        "src/payments/stripe.py": "class StripeGateway(PaymentGateway):\n    def charge(self, amount): return 'ok'\n",
    })


def test_abstraction_shell_is_registered_with_reusability_and_uses_40k_output():
    specs = registered_investigators()
    assert specs["abstraction"].agent_class is AbstractionAgent
    assert specs["abstraction"].request_class is AbstractionRequest
    config = AbstractionConfig()
    assert config.max_output_tokens == 40_000
    assert config.max_planned_investigations >= 1
    assert set(config.prompt_nodes) == {"plan_investigation", "investigate", "synthesize", "finalize"}
    assert describe_agent_config("abstraction", level="developer")["prompt_nodes"] == list(config.prompt_nodes)



def test_execution_shell_compiles_expected_graph_and_initializes_snapshot(tmp_path):
    tools = tools_for(tmp_path, {"app.py": "x = 1\n"})
    model = PlanningModel()
    execution = AbstractionExecution(model, AbstractionConfig(), tools, AbstractionRequest())
    state = execution.initial_state()
    assert set(execution.graph.get_graph().nodes) >= {
        "plan_investigation", "investigate", "tools", "synthesize", "finalize",
    }
    assert state["snapshot_hash"] == tools.accessible_snapshot.repository.snapshot_hash
    assert state["investigation_results"] == []


def test_plan_investigation_selects_and_traces_candidates_without_findings(tmp_path):
    tools = llm_repository(tmp_path)
    model = PlanningModel(count=1)
    document = ArchitectureContextResult.model_validate(context(
        knowledge=[{
            "category": "interfaces_and_contracts",
            "subject": "LlmProvider",
            "statement": "LlmProvider is the contract every LLM backend implements.",
            "related_subjects": [],
            "certainty": "explicit",
            "section_ids": ["section-1"],
            "reasoning": "The document declares the abstraction.",
            "constraint": "unspecified",
            "evidence": [{"section_id": "section-1", "start_line": 2, "end_line": 4, "quote": "LlmProvider"}],
        }],
        section_paths={"section-1": "docs/architecture.md"},
    ))
    request = AbstractionRequest(documented_architecture=document)
    execution = AbstractionExecution(model, AbstractionConfig(), tools, request)

    update = asyncio.run(execution.plan_investigation(execution.initial_state()))

    plan = update["plan"]
    result = update["result"]
    candidate = plan.candidates[0]
    assert model.contexts, "the selection model must be consulted"
    assert len(plan.candidates) == 1
    assert candidate.abstraction_name == "LlmProvider"
    assert candidate.document_claim_ids == list(plan.document_claims)
    assert set(candidate.document_claim_ids) <= set(plan.document_claims)
    assert [item.criterion_id for item in plan.hypotheses] == ["abstraction-purpose"]
    assert plan.hypotheses[0].question == candidate.question
    assert result.findings == []
    assert execution.route_after_plan({**execution.initial_state(), **update}) == "investigate"


def test_plan_investigation_empty_menu_never_calls_the_model(tmp_path):
    tools = tools_for(tmp_path, {"app.py": "x = 1\n"})
    model = PlanningModel()
    execution = AbstractionExecution(model, AbstractionConfig(), tools, AbstractionRequest())

    update = asyncio.run(execution.plan_investigation(execution.initial_state()))

    assert update["plan"].candidates == []
    assert model.contexts == []
    assert execution.route_after_plan({**execution.initial_state(), **update}) == "end"


def test_agent_run_stops_honestly_without_model_calls(tmp_path):
    tools = tools_for(tmp_path, {"app.py": "x = 1\n"})
    model = PlanningModel()

    result = asyncio.run(AbstractionAgent(model, AbstractionConfig()).run(tools, AbstractionRequest()))

    assert result.plan is not None and result.plan.candidates == []
    assert result.termination_reason == "planning_completed"
    assert model.contexts == []


def test_plan_investigation_records_missing_documented_architecture_honestly(tmp_path):
    tools = tools_for(tmp_path, {"app.py": "x = 1\n"})
    model = PlanningModel()
    execution = AbstractionExecution(model, AbstractionConfig(), tools, AbstractionRequest())

    update = asyncio.run(execution.plan_investigation(execution.initial_state()))

    assert any("No documented architecture supplied" in item for item in update["limitations"])
    assert execution.route_after_plan({**execution.initial_state(), **update}) == "end"


class EmptySelectionModel(PlanningModel):
    async def ainvoke(self, messages, **kwargs):
        context_message = messages[1].content
        self.contexts.append(json.loads(context_message))
        return AIMessage(content=json.dumps({"candidate_ids": [], "questions": {}}),
            usage_metadata={"input_tokens": 40, "output_tokens": 10, "total_tokens": 50})


def test_shell_selection_may_abstain_from_weak_candidates(tmp_path):
    tools = llm_repository(tmp_path)
    model = EmptySelectionModel()
    execution = AbstractionExecution(model, AbstractionConfig(), tools, AbstractionRequest())

    update = asyncio.run(execution.plan_investigation(execution.initial_state()))

    assert update["plan"].candidates == []
    assert model.contexts, "the menu author must still be consulted"
    assert any("abstained" in item for item in update["limitations"])
    assert execution.route_after_plan({**execution.initial_state(), **update}) == "end"


def test_plan_investigation_traces_menu_and_selection_to_stderr(tmp_path, capsys):
    tools = llm_repository(tmp_path)
    model = PlanningModel(count=1)
    execution = AbstractionExecution(model, AbstractionConfig(), tools, AbstractionRequest())

    update = asyncio.run(execution.plan_investigation(execution.initial_state()))

    captured = capsys.readouterr().err
    candidate_id = update["plan"].candidates[0].id if update["plan"].candidates else None
    assert "[DEBUG_PLAN_MENU]" in captured
    assert "[DEBUG_PLAN_MENU_CANDIDATE]" in captured and "abstraction=LlmProvider" in captured
    assert "[DEBUG_PLAN_SELECTION]" in captured
    assert candidate_id and candidate_id in captured
    assert "discarded=[]" not in captured  # multi-candidate menu discards the rest


def test_plan_investigation_prompt_requires_guarantees_and_rejects_functional_questions():
    prompt = (AbstractionExecution.prompt_directory / "plan_investigation.md").read_text(encoding="utf-8")
    assert "specific architectural guarantee" in prompt
    assert "Do not transfer responsibilities" in prompt
    assert "LoginResult" in prompt
    assert "Never select a declaration merely because it exists" in prompt
    assert "listAuditLogsService" in prompt
    assert "SessionPayload" in prompt
    assert "backward compatibility" in prompt


def test_agent_run_drives_investigation_loop_with_tools(tmp_path):
    tools = llm_repository(tmp_path)

    class InvestigateModel:
        def __init__(self):
            self.contexts = []

        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages, **kwargs):
            context = json.loads(messages[1].content)
            self.contexts.append(context)
            if "budget" in context:
                candidates = context["candidates"][:1]
                ids = [candidate["id"] for candidate in candidates]
                response = {"candidate_ids": ids,
                    "questions": {candidate["id"]: f"Does {candidate['abstraction_name']} in {candidate['primary_component']} "
                        f"provide substitutability without consumers depending on implementation details?"
                        for candidate in candidates},
                    "evidence_requirements": {
                        candidate["id"]: [f"{candidate['abstraction_name']} must behave as a thin contract for its implementers and consumers",
                            f"{candidate['abstraction_name']} must not leak vendor-specific details to callers"]
                        for candidate in candidates}}
                usage = {"input_tokens": 30, "output_tokens": 20, "total_tokens": 50}
            else:
                investigation = context["investigation"]
                response = {"action": "close", "queries": [], "conclusion": {
                    "investigation_id": investigation["id"],
                    "status": "inconclusive",
                    "summary": "Investigation closed without source findings.",
                    "justification": "Offline model cannot assess source provenance.",
                    "components": [], "symbol_ids": [], "relationship_ids": [],
                    "evidence_ids": [], "candidates": [],
                    "limitations": ["offline_model_cannot_assess_source"],
                    "claim_assessments": [
                        {"claim_id": claim_id, "status": "inconclusive",
                         "rationale": "offline model cannot assess source",
                         "code_evidence_ids": [], "scope_paths": [],
                         "limitations": ["offline model cannot assess source"]}
                        for claim_id in investigation["document_claim_ids"]
                    ]}}
                usage = {"input_tokens": 20, "output_tokens": 20, "total_tokens": 40}
            return AIMessage(content=json.dumps(response), usage_metadata=usage)

    model = InvestigateModel()
    execution = AbstractionExecution(model, AbstractionConfig(), tools, AbstractionRequest())

    async def investigations():
        state = execution.initial_state()
        state = {**state, **await execution.plan_investigation(state)}
        while True:
            route = execution.route_investigation(state)
            if route == "tools":
                state = {**state, **await execution.execute_investigation_tools(state)}
            elif route == "investigate":
                state = {**state, **await execution.investigate(state)}
            else:
                break
        return state

    state = asyncio.run(investigations())

    conclusion = state["result"].investigation_results[0]
    assert state["termination_reason"] == "investigations_completed"
    assert conclusion.status == "inconclusive"
    assert state["result"].hypotheses[0].status == "inconclusive"
    assert any("offline_model_cannot_assess_source" in limitation
        for limitation in state["result"].limitations)
    # tools must have executed before closing
    assert any("tool_results" in context for context in model.contexts)

