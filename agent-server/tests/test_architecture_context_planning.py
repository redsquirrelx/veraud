"""Single-call retrieval planning, grounded paths, and shared runtime budgets."""

import asyncio
import json
from copy import deepcopy
from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from config.agents.budgets import BudgetPolicy
from config.agents.execution import AgentExecutionConfig
from server.agents.architecture_context import (
    ArchitectureContextState,
    ReadTask,
    RetrievalPlan,
    RetrievalRecord,
    SearchTask,
    plan_retrieval,
    planning,
)
from server.agents.architecture_context.schemas import KnowledgeClaim, KnowledgeIssue
from server.runtimes.repository.budgeted_model import BudgetedModel
from server.runtimes.repository.shared_tokens import SharedTokenBudget
from server.runtimes.repository.timing import ActiveDeadline
from server.services.document_indexing import DocumentRecord, DocumentSection


@pytest.fixture
def state():
    return {
        "documents": [
            DocumentRecord(
                index_id="index",
                repository_id="repository",
                commit="commit",
                path="docs/architecture.md",
                content_hash="hash",
                line_count=10,
            )
        ],
        "document_discovery_status": "ready",
    }


def managed_model(payload, **options):
    provider = SimpleNamespace(
        ainvoke=AsyncMock(
            return_value=SimpleNamespace(
                content=json.dumps(payload),
                usage_metadata={"input_tokens": 100, "output_tokens": 30},
            )
        )
    )
    limits = AgentExecutionConfig(
        max_provider_retries=0,
        provider_request_interval_seconds=0,
        provider_rate_limits={"requests_per_minute": None, "tokens_per_minute": None},
        **options,
    )
    tokens = SharedTokenBudget(100_000)
    return provider, BudgetedModel(provider, limits, tokens, ActiveDeadline(10)), tokens


def test_langgraph_planner_returns_only_structured_plan_and_accounts_usage(state):
    provider, model, tokens = managed_model(
        {
            "tasks": [
                {
                    "category": "components",
                    "operation": "read",
                    "path": "docs/architecture.md",
                },
                {
                    "category": "interfaces_and_contracts",
                    "operation": "search",
                    "query": "API contract",
                },
            ]
        }
    )
    original = deepcopy(state)
    graph = StateGraph(ArchitectureContextState)
    graph.add_node("plan_retrieval", partial(plan_retrieval, model=model))
    graph.add_edge(START, "plan_retrieval")
    graph.add_edge("plan_retrieval", END)
    output = asyncio.run(graph.compile().ainvoke(state))
    plan = output["retrieval_plan"]
    assert isinstance(plan, RetrievalPlan)
    assert isinstance(plan.tasks[0], ReadTask) and isinstance(plan.tasks[1], SearchTask)
    assert plan.tasks[0].path == state["documents"][0].path
    assert provider.ainvoke.await_count == 1 and tokens.used == 130
    assert state == original
    assert set(output) == {*state, "retrieval_plan", "retrieval_round"}
    prompt = provider.ainvoke.call_args.args[0][0].content
    assert "Response schema:" in prompt and "architectural_decisions" in prompt
    assert "content_hash" not in prompt and "repository_id" not in prompt


@pytest.mark.parametrize(
    "tasks",
    [
        [{"category": "invented", "operation": "search", "query": "architecture"}],
        [{"category": "components", "operation": "read", "path": "invented.md"}],
        [{"category": "components", "operation": "search", "query": "  "}],
        [{"category": "components", "operation": "search", "query": "!!!"}],
        [
            {
                "category": "components",
                "operation": "execute",
                "path": "docs/architecture.md",
            }
        ],
        [
            {
                "category": "components",
                "operation": "read",
                "path": "docs/architecture.md",
                "query": "extra",
            }
        ],
        [
            {
                "category": "components",
                "operation": "read",
                "path": "docs/architecture.md",
            },
            {
                "category": "interfaces_and_contracts",
                "operation": "read",
                "path": "docs/architecture.md",
            },
        ],
        [
            {"category": "components", "operation": "search", "query": "API gateway"},
            {
                "category": "interfaces_and_contracts",
                "operation": "search",
                "query": "gateway api API",
            },
        ],
        [
            {"category": "components", "operation": "search", "query": f"term{number}"}
            for number in range(5)
        ],
    ],
)
def test_invalid_plans_are_rejected_without_llm_correction_calls(state, tasks):
    provider, model, _ = managed_model({"tasks": tasks})
    with pytest.raises(ValidationError):
        asyncio.run(plan_retrieval(state, model=model))
    assert provider.ainvoke.await_count == 1


def test_prior_retrieval_and_pending_needs_are_used_without_extracting(state):
    old = SearchTask(
        category="components", operation="search", query="gateway boundary"
    )
    state.update(
        retrieval_history=[old],
        pending_categories=["interfaces_and_contracts"],
        processed_section_ids=["section"],
        retrieved_sections=[
            DocumentSection(
                **state["documents"][0].model_dump(),
                section_id="section",
                start_line=1,
                end_line=2,
                headings=[],
                content="already recovered gateway responsibilities",
            )
        ],
    )
    provider, model, _ = managed_model(
        {
            "tasks": [
                {
                    "category": "interfaces_and_contracts",
                    "operation": "search",
                    "query": "API schema",
                },
            ]
        }
    )
    output = asyncio.run(plan_retrieval(state, model=model))
    assert set(output) == {"retrieval_plan", "retrieval_round"}
    prompt = provider.ainvoke.call_args.args[0][0].content
    assert "gateway boundary" in prompt
    assert "already recovered gateway responsibilities" not in prompt
    assert '"processed_document_paths": ["docs/architecture.md"]' in prompt
    assert '"pending_categories": ["interfaces_and_contracts"]' in prompt
    _, repeated_model, _ = managed_model(
        {
            "tasks": [
                {
                    "category": "interfaces_and_contracts",
                    "operation": "search",
                    "query": "boundary GATEWAY",
                },
            ]
        }
    )
    with pytest.raises(ValidationError, match="Repeated retrieval"):
        asyncio.run(plan_retrieval(state, model=repeated_model))
    _, wrong_category, _ = managed_model(
        {
            "tasks": [
                {
                    "category": "components",
                    "operation": "search",
                    "query": "API schema",
                },
            ]
        }
    )
    with pytest.raises(ValidationError, match="pending need"):
        asyncio.run(plan_retrieval(state, model=wrong_category))


def test_previous_plan_is_not_repeated(state):
    state["retrieval_plan"] = RetrievalPlan(
        tasks=[
            ReadTask(
                category="components",
                operation="read",
                path="docs/architecture.md",
            )
        ]
    )
    _, model, _ = managed_model(
        {
            "tasks": [
                {
                    "category": "components",
                    "operation": "read",
                    "path": "docs/architecture.md",
                },
            ]
        }
    )
    with pytest.raises(ValidationError, match="Repeated retrieval"):
        asyncio.run(plan_retrieval(state, model=model))


@pytest.mark.parametrize("change", [{"documents": []}, {"pending_categories": []}])
def test_empty_catalog_or_no_pending_needs_skips_model(state, change):
    state.update(change)
    provider, model, _ = managed_model({"tasks": []})
    assert asyncio.run(plan_retrieval(state, model=model)) == {
        "retrieval_plan": RetrievalPlan(tasks=[])
    }
    provider.ainvoke.assert_not_awaited()


def test_discovery_failure_is_not_treated_as_empty_catalog(state):
    state.update(documents=[], document_discovery_status="error")
    provider, model, _ = managed_model({"tasks": []})
    with pytest.raises(ValueError, match="unavailable"):
        asyncio.run(plan_retrieval(state, model=model))
    provider.ainvoke.assert_not_awaited()


def test_shared_call_budget_applies_across_iterations(state):
    provider, model, _ = managed_model({"tasks": []}, max_model_calls=4)
    for _ in range(4):
        assert (
            asyncio.run(plan_retrieval(state, model=model))["retrieval_plan"].tasks
            == []
        )
    with pytest.raises(ValueError, match="model_call_budget_exhausted"):
        asyncio.run(plan_retrieval(state, model=model))
    assert provider.ainvoke.await_count == 4


def test_architecture_context_cannot_opt_out_of_global_call_budget(state):
    provider, model, _ = managed_model({"tasks": []}, max_model_calls=4)
    state["retrieval_round"] = 1
    model.attempts = model.limits.max_model_calls
    model.enforce_model_call_limit = False
    result = asyncio.run(plan_retrieval(state, model=model))
    assert result["context_stop_reason"] == "planning_budget_exhausted"
    provider.ainvoke.assert_not_awaited()
    assert model.attempts == model.limits.max_model_calls


def test_shared_token_budget_blocks_provider(state, finite_token_budget):
    provider, model, _ = managed_model({"tasks": []})
    model.tokens = SharedTokenBudget(1000)
    with pytest.raises(ValueError, match="shared_token_budget_exhausted"):
        asyncio.run(plan_retrieval(state, model=model))
    provider.ainvoke.assert_not_awaited()


@pytest.mark.usefixtures("finite_token_budget")
def test_later_round_budget_stop_preserves_accumulated_state(state):
    state["retrieval_round"] = 1
    original = deepcopy(state)
    provider, model, _ = managed_model({"tasks": []})
    model.tokens = SharedTokenBudget(1)
    result = asyncio.run(plan_retrieval(state, model=model))
    assert not result["retrieval_plan"].tasks
    assert result["context_stop_reason"] == "planning_budget_exhausted"
    assert state == original
    provider.ainvoke.assert_not_awaited()


def test_global_disabled_budgets_allow_later_planning_past_ledger_limit(state, monkeypatch):
    from server.agent_services.budgeting import policy

    monkeypatch.setattr(policy, "token_budget_policy", lambda: BudgetPolicy(budgets_enabled=False))
    state["retrieval_round"] = 1
    provider, model, _ = managed_model({"tasks": []})
    model.tokens = SharedTokenBudget(1)
    result = asyncio.run(plan_retrieval(state, model=model))
    assert result["retrieval_round"] == 2
    assert "context_stop_reason" not in result and model.tokens.used > 1
    provider.ainvoke.assert_awaited_once()


def test_large_catalog_is_compact_and_still_prioritizes_architecture_paths(state):
    template = state["documents"][0]
    state["documents"] += [
        template.model_copy(update={"path": f"misc/{number:04}-notes.md"})
        for number in range(1000)
    ]
    provider, model, _ = managed_model({"tasks": []}, max_context_characters=10_000)
    asyncio.run(plan_retrieval(state, model=model))
    prompt = provider.ainvoke.call_args.args[0][0].content
    assert len(prompt) <= model.limits.max_context_characters
    assert "docs/architecture.md" in prompt
    assert "misc/0999-notes.md" not in prompt
    assert '"omitted_documents":' in prompt


@pytest.fixture
def prompt_context(monkeypatch):
    captured = []
    original = planning.measure_json

    def capture(value, **kwargs):
        captured.append(value)
        return original(value, **kwargs)

    monkeypatch.setattr(planning, "measure_json", capture)
    return captured


@pytest.mark.parametrize(
    "category,path",
    [
        ("architectural_style", "architecture.md"),
        ("components", "components.md"),
        ("responsibilities", "responsibilities.md"),
        ("relationships", "relationships.md"),
        ("constraints", "constraints.md"),
        ("interfaces_and_contracts", "contracts.md"),
        ("architectural_decisions", "decisions.md"),
    ],
)
def test_catalog_priority_tracks_pending_categories(
    state, prompt_context, category, path
):
    template = state["documents"][0]
    paths = [
        "architecture.md",
        "components.md",
        "responsibilities.md",
        "relationships.md",
        "constraints.md",
        "interfaces.md",
        "contracts.md",
        "decisions.md",
        "README.md",
    ]
    state.update(
        documents=[template.model_copy(update={"path": name}) for name in paths],
        pending_categories=[category],
    )
    provider, model, _ = managed_model({"tasks": []})
    asyncio.run(plan_retrieval(state, model=model))
    menu = prompt_context[0]["catalog_path_line_pairs"]
    assert menu[0][0] == path
    assert all(len(entry) == 2 for entry in menu)  # No fabricated catalog headings.
    assert provider.ainvoke.await_count == 1


def test_planned_and_executed_tasks_are_not_conflated_with_recovered_sections(
    state, prompt_context
):
    executed = SearchTask(
        category="interfaces_and_contracts", operation="search", query="old terms"
    )
    planned = ReadTask(
        category="interfaces_and_contracts",
        operation="read",
        path=state["documents"][0].path,
    )
    state.update(
        retrieval_history=[executed],
        retrieval_plan=RetrievalPlan(tasks=[planned]),
        pending_categories=["interfaces_and_contracts"],
    )
    original = deepcopy(state)
    _, model, _ = managed_model(
        {
            "tasks": [
                {
                    "category": "interfaces_and_contracts",
                    "operation": "search",
                    "query": "new terms",
                },
            ]
        }
    )
    output = asyncio.run(plan_retrieval(state, model=model))
    context = prompt_context[0]
    assert context["executed_tasks"] == [executed.model_dump()]
    assert context["planned_not_executed"] == [planned.model_dump()]
    assert "retrieved_sections" not in context
    assert context["pending_categories"] == ["interfaces_and_contracts"]
    assert set(output) == {"retrieval_plan", "retrieval_round"} and state == original


def test_prompt_history_is_bounded_but_duplicate_validation_uses_full_history(
    state, prompt_context
):
    history = [
        SearchTask(category="components", operation="search", query=f"term{number:04}")
        for number in range(1000)
    ]
    state["retrieval_history"] = history
    provider, model, _ = managed_model(
        {
            "tasks": [
                {"category": "components", "operation": "search", "query": "term0000"},
            ]
        },
        max_context_characters=10_000,
    )
    with pytest.raises(ValidationError, match="Repeated retrieval"):
        asyncio.run(plan_retrieval(state, model=model))
    context = prompt_context[0]
    assert context["omitted_history"]["executed_tasks"] > 0
    assert context["executed_tasks"][-1]["query"] == "term0999"
    assert not any(task["query"] == "term0000" for task in context["executed_tasks"])
    assert (
        len(provider.ainvoke.call_args.args[0][0].content)
        <= model.limits.max_context_characters
    )
    assert state["retrieval_history"] == history and provider.ainvoke.await_count == 1


def test_planning_context_ignores_claim_volume_but_keeps_open_reference_and_task(
    state, prompt_context
):
    state.update(
        pending_categories=["interfaces_and_contracts"],
        knowledge=[
            KnowledgeClaim(
                category="components",
                subject=f"Component {index}",
                statement="A long accumulated statement " * 20,
                certainty="explicit",
                    section_ids=["section"],
                    reasoning="A long source rationale " * 20,
                    evidence=[{
                        "section_id": "section",
                        "start_line": 1,
                        "end_line": 1,
                        "quote": "documentary source",
                    }],
            )
            for index in range(500)
        ],
        knowledge_issues=[
            KnowledgeIssue(
                category="interfaces_and_contracts",
                kind="unknown",
                question="Which guarantees does the registry document define?",
                section_ids=["section"],
                document_references=["docs/contracts/registry-v2.md", "SPEC-X17"],
            )
        ],
        retrieval_history=[
            SearchTask(
                category="interfaces_and_contracts",
                operation="search",
                query="contract registry",
            )
        ],
        processed_section_ids=["section"],
        retrieved_sections=[
            DocumentSection(
                **state["documents"][0].model_dump(),
                section_id="section",
                start_line=1,
                end_line=10,
                headings=[],
                content="Private recovered source content " * 3000,
            )
        ],
    )
    state["documents"].append(
        state["documents"][0].model_copy(
            update={
                "path": "docs/contracts/registry-v2.md",
                "content_hash": "registry",
                "line_count": 2000,
            }
        )
    )
    provider, model, _ = managed_model(
        {
            "tasks": [
                {
                    "category": "interfaces_and_contracts",
                    "operation": "read",
                    "path": "docs/contracts/registry-v2.md",
                }
            ]
        }
    )
    asyncio.run(plan_retrieval(state, model=model))
    prompt = provider.ainvoke.call_args.args[0][0].content
    context = prompt_context[0]
    assert "docs/contracts/registry-v2.md" in prompt
    assert "SPEC-X17" in prompt
    assert "Which guarantees does the registry document define?" in prompt
    assert "contract registry" in prompt
    assert "Private recovered source content" not in prompt
    assert "Component 499" not in prompt and "A long source rationale" not in prompt
    assert "knowledge" not in context and "retrieved_sections" not in context
    assert len(prompt) <= model.limits.max_context_characters
    large_context_size = len(json.dumps(context, ensure_ascii=False))
    old_context = {
        "pending_categories": state["pending_categories"],
        "catalog_path_line_pairs": context["catalog_path_line_pairs"],
        "omitted_documents": context["omitted_documents"],
        "executed_tasks": [
            task.model_dump(mode="json") for task in state["retrieval_history"]
        ],
        "planned_not_executed": [],
        "retrieved_sections": [
            {
                "path": section.path,
                "start_line": section.start_line,
                "end_line": section.end_line,
                "headings": [],
                "excerpt": section.content[:500],
            }
            for section in state["retrieved_sections"]
        ],
        "knowledge": [claim.model_dump(mode="json") for claim in state["knowledge"]],
        "open_issues": [
            issue.model_dump(mode="json") for issue in state["knowledge_issues"]
        ],
        "retrieval_suggestions": RetrievalPlan(tasks=[]).model_dump(mode="json"),
        "omitted_history": {
            "executed_tasks": 0,
            "planned_not_executed": 0,
            "retrieved_sections": 0,
        },
    }
    old_context_size = len(json.dumps(old_context, ensure_ascii=False))
    current_context_text = prompt.split("Retrieval context:\n", 1)[1]
    old_prompt_size = len(prompt) - len(current_context_text) + old_context_size
    assert old_prompt_size > len(prompt) * 10

    state.pop("knowledge")
    _, small_model, _ = managed_model(
        {
            "tasks": [
                {
                    "category": "interfaces_and_contracts",
                    "operation": "read",
                    "path": "docs/contracts/registry-v2.md",
                }
            ]
        }
    )
    asyncio.run(plan_retrieval(state, model=small_model))
    assert len(json.dumps(prompt_context[-1], ensure_ascii=False)) == large_context_size


def test_planner_consumes_retrieval_outcomes_without_confusing_limits_with_execution(
    state, prompt_context
):
    attempted = SearchTask(
        category="interfaces_and_contracts", operation="search", query="HTTP schema"
    )
    blocked = SearchTask(
        category="interfaces_and_contracts", operation="search", query="API contract"
    )
    state["retrieval_history"] = [
        RetrievalRecord(task=attempted, index_id="index", status="no_results"),
        RetrievalRecord(
            task=blocked,
            index_id="index",
            status="limited",
            executed=False,
            error="budget exhausted",
        ),
    ]
    _, model, _ = managed_model({"tasks": [blocked.model_dump()]})
    result = asyncio.run(plan_retrieval(state, model=model))
    assert result["retrieval_plan"].tasks == [blocked]
    assert prompt_context[0]["executed_tasks"][0]["status"] == "no_results"
    assert len(prompt_context[0]["executed_tasks"]) == 1
    _, repeated, _ = managed_model({"tasks": [attempted.model_dump()]})
    with pytest.raises(ValidationError, match="Repeated retrieval"):
        asyncio.run(plan_retrieval(state, model=repeated))
