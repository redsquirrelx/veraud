"""Real snapshots/tools/graph with scripted semantic judgments; no paid model calls."""

import asyncio
import json

import pytest
from langchain_core.messages import AIMessage

from config.agents.budgets import BudgetPolicy
from server.agent_services.budgeting import policy
from server.agents.maintainability.v2.reusability.reuse_opportunity_doc_driven.config import (
    ReuseOpportunityConfig,
)
from server.agents.maintainability.v2.reusability.reuse_opportunity_doc_driven.execution import (
    ReuseOpportunityExecution,
)
from server.agents.maintainability.v2.reusability.reuse_opportunity_doc_driven.schemas import (
    ReuseInvestigation,
    ReuseOpportunityDocDrivenRequest,
    ReuseOpportunityDocDrivenResult,
    ReuseOpportunityPlan,
)
from server.contracts.audit import Hypothesis
from server.runtimes.repository.context import RepositoryContext
from server.runtimes.repository.schemas import ExecutionBudget, RepositoryInput
from server.runtimes.repository.tools import RepositoryToolset
from server.services.repository_analysis import RepositoryAnalysisService


class Model:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.contexts = []

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages, **kwargs):
        context = json.loads(messages[1].content)
        self.contexts.append(context)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return AIMessage(content=json.dumps(response(context) if callable(response) else response),
            usage_metadata={"input_tokens": 100, "output_tokens": 100, "total_tokens": 200})


def task(**updates):
    return ReuseInvestigation(**({"id": "task-0", "capability": "Record normalization",
        "question": "Do consumers repeat record normalization or reuse a compatible provider?",
        "document_claim_ids": ["claim-0"], "initial_targets": ["provider.py"],
        "objectives": ["Inspect provider, consumers and local alternatives."],
        "reuse_criteria": ["Equivalent behavior is shareable."],
        "independent_implementation_criteria": ["Different contracts may justify separation."],
        "rationale": "Documented shared normalization.",
        "documented_reuse_expectation": "normalize_record is the shared normalization behavior.",
        "providers": ["normalize_record"], "consumers": [],
        "implementation_uncertainty": "Whether local alternatives reproduce this behavior."} | updates))


class PreparedExecution(ReuseOpportunityExecution):
    """Inject an existing plan; planning logic is deliberately not under test here."""

    async def plan_investigation(self, state):
        plan = self.prepared_plan
        result = ReuseOpportunityDocDrivenResult(repository_id=state["repository_id"], commit=state["commit"],
            snapshot_hash=self.tools.context.input.snapshot_hash, objective=self.request.objective,
            plan=plan, hypotheses=plan.hypotheses, findings=[], missing_information=[], limitations=[],
            termination_reason="planning_completed", model_calls=0, tool_calls=0, iterations=0,
            accounted_tokens=0, estimated_tokens=0)
        return {"plan": plan, "hypotheses": plan.hypotheses, "result": result}


def prepared(tmp_path, sources, responses, tasks=None, **config):
    root = tmp_path / "repo"
    root.mkdir()
    for path, body in sources.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    snapshot = RepositoryAnalysisService().analyze_sync(root)
    budget = ExecutionBudget(max_model_calls=30, max_tool_calls=100, max_input_tokens_per_call=50_000,
        max_total_tokens=200_000, max_tokens_per_objective=200_000, max_retrieved_characters=1_000_000)
    tools = RepositoryToolset(RepositoryContext(snapshot, RepositoryInput(
        snapshot_hash=snapshot.repository.snapshot_hash, budget=budget)), workspace_root=root.parent)
    model = Model(responses)
    settings = ReuseOpportunityConfig(**({"max_model_calls": 30, "max_tool_calls": 100,
        "provider_rate_limits": {"requests_per_minute": None, "tokens_per_minute": None}} | config))
    execution = PreparedExecution(model, settings, tools, ReuseOpportunityDocDrivenRequest())
    tasks = tasks or [task()]
    execution.prepared_plan = ReuseOpportunityPlan(objectives=[execution.request.objective], components=[],
        hypotheses=[Hypothesis(id=item.id, question=item.question) for item in tasks], investigations=tasks,
        document_claims={"claim-0": {"subject": "normalize_record", "statement": "normalize_record is a shared provider.",
            "category": "responsibilities", "constraint": "required", "certainty": "explicit", "section_ids": ["s"],
            "related_subjects": [], "evidence": [{"section_id": "s", "start_line": 1, "end_line": 1, "quote": "Shared provider."}],
            "reasoning": "Architectural intent", "section_paths": {"s": "architecture.md"}}})
    return execution, model


def run(execution):
    return asyncio.run(execution.graph.ainvoke(execution.initial_state(), {"recursion_limit": 200}))["result"]


PROVIDER = "def normalize_record(value):\n    return value.strip().lower()\n"
CONSUMER = "from provider import normalize_record\ndef handle(value):\n    return normalize_record(value)\n"
ALTERNATIVE = "def normalize_local(value):\n    return value.strip().lower()\n"


def close(context, *, outcome="correct_reuse", role="consumer", other="handle", status=None):
    symbols = {item["name"]: item for item in context["symbols"]}
    shared = symbols["normalize_record"]
    independent = symbols[other]
    def refs(item):
        return [ref["id"] for ref in context["evidence"] if ref["path"] == item["path"] and ref["kind"] == "source"]
    comparison = {"shared_symbol_id": shared["id"], "other_symbol_id": independent["id"],
        "shared_evidence_ids": refs(shared), "other_evidence_ids": refs(independent),
        "other_role": role, "outcome": outcome, "responsibility": "Normalize records.",
        "inputs_outputs": "String in, stripped lowercase string out.", "effects": "Pure computation.",
        "rules_and_errors": "No extra validation.", "architectural_constraints": "No prohibited consolidation in fixture.",
        "rationale": "Scripted assessment of the delivered source bodies."}
    status = status or ("reuse_opportunity" if outcome == "equivalent_shareable" else "no_reuse_opportunity")
    evidence = list(dict.fromkeys(refs(shared) + refs(independent)))
    paths = sorted({shared["path"], independent["path"]})
    candidate = {"id": "candidate", "criterion_id": "reuse-opportunity", "kind": "design_observation",
        "title": "Independent normalization duplicates shared behavior.", "description": "Local normalization has equivalent behavior.",
        "components": paths, "evidence_ids": evidence, "justification": "Both function bodies inspected.",
        "modularity_impact": "Redundant normalization maintenance.", "severity": "low", "confidence": 0.8,
        "recommendation": "Consider shared normalization if constraints remain compatible.",
        "shared_component": shared["path"], "independent_implementations": [independent["path"] + "#" + independent["name"]],
        "shared_behavior": "Normalize strings.", "independent_behavior": "Normalize strings locally.",
        "behavior_comparison": "Same observable transformation.",
        "shared_symbol_ids": [shared["id"]], "independent_symbol_ids": [independent["id"]],
        "reuse_hypothesis": "functional_duplication", "symbol_ids": [shared["id"], independent["id"]]}
    return {"action": "close", "conclusion": {"investigation_id": context["investigation"]["id"], "status": status,
        "summary": "Scoped reuse decision.", "justification": "Decision grounded in the compared source bodies.",
        "components": paths, "inspected_scope": paths, "evidence_ids": evidence,
        "candidates": [candidate] if status == "reuse_opportunity" else [], "comparisons": [comparison]}}


@pytest.mark.parametrize("padding", [0, 160])
def test_symbol_discovery_reads_relevant_function_not_file_beginning(tmp_path, padding):
    execution, model = prepared(tmp_path, {"provider.py": "\n" * padding + PROVIDER, "consumer.py": CONSUMER}, [close])
    result = run(execution)
    assert result.investigation_results[0].status == "no_reuse_opportunity"
    assert result.candidates == []
    assert any(ref.path == "provider.py" and ref.start_line == padding + 1 for ref in result.evidence if ref.kind == "source")
    assert result.model_calls == 1
    assert len(model.contexts) == 1


def test_large_directory_selects_named_behavior_not_first_files(tmp_path):
    sources = {f"pkg/a{i:03d}.py": f"def irrelevant{i}():\n    return 0\n" for i in range(40)}
    sources.update({"pkg/zprovider.py": PROVIDER, "pkg/zconsumer.py": CONSUMER.replace("from provider", "from pkg.zprovider")})
    execution, _ = prepared(tmp_path, sources, [close], tasks=[task(initial_targets=["pkg"])])
    result = run(execution)
    assert result.investigation_results[0].status == "no_reuse_opportunity"
    inspected = {ref.path for ref in result.evidence if ref.kind == "source"}
    assert "pkg/zprovider.py" in inspected and "pkg/zconsumer.py" in inspected
    assert not any(path.startswith("pkg/a") for path in inspected)


@pytest.mark.parametrize(("filename", "provider_name", "consumer_name"), [
    ("auth.service.ts", "authorizeUser", "proxy"), ("audit.service.ts", "listAuditLogsService", "loadAudit"),
])
def test_correct_typescript_consumers_are_not_independent_implementations(tmp_path, filename, provider_name, consumer_name):
    sources = {filename: f"export function {provider_name}(value: string) {{ return value; }}\n",
        "proxy.ts": f"import {{ {provider_name} }} from './{filename[:-3]}';\nexport function {consumer_name}(value: string) {{ return {provider_name}(value); }}\n"}
    def decision(context):
        # Use the same comparison helper with a normalized test-only symbol alias.
        context["symbols"] = [{**item, "name": "normalize_record" if item["name"] == provider_name else item["name"]}
            for item in context["symbols"]]
        return close(context, other=consumer_name)
    execution, _ = prepared(tmp_path, sources, [decision], tasks=[task(initial_targets=[filename], providers=[provider_name])])
    result = run(execution)
    assert result.investigation_results[0].status == "no_reuse_opportunity"
    assert result.candidates == []


def test_real_independent_behavior_needs_two_sided_comparison(tmp_path):
    execution, _ = prepared(tmp_path, {"provider.py": PROVIDER, "alternative.py": ALTERNATIVE},
        [lambda context: close(context, outcome="equivalent_shareable", role="independent_implementation", other="normalize_local")])
    result = run(execution)
    assert result.investigation_results[0].status == "reuse_opportunity"
    assert len(result.candidates) == 1
    assert result.hypotheses[0].status == "confirmed"


def test_contract_difference_can_justify_independence(tmp_path):
    execution, _ = prepared(tmp_path, {"provider.py": PROVIDER,
        "alternative.py": "def normalize_local(value):\n    return value.strip()\n"},
        [lambda context: close(context, outcome="justified_independence", role="independent_implementation", other="normalize_local")])
    result = run(execution)
    assert result.investigation_results[0].status == "no_reuse_opportunity"


def test_premature_close_continues_to_a_new_consumer_body(tmp_path):
    def premature(context):
        return {"action": "close", "conclusion": {"investigation_id": context["investigation"]["id"],
            "status": "inconclusive", "summary": "Consumers not inspected.", "justification": "Need consumer source.",
            "limitations": ["Consumers not inspected."]}}
    execution, model = prepared(tmp_path, {"provider.py": PROVIDER, "consumer.py": CONSUMER}, [premature, close])
    # Only the provider is initially known; the consumer must be found by tool search.
    original_seed = execution._seed_entities
    def provider_only(state, workspace):
        original_seed(state, workspace)
        workspace["entities"] = {key: value for key, value in workspace["entities"].items() if value["path"] == "provider.py"}
    execution._seed_entities = provider_only
    # Allow first source interpretation before deterministic missing-consumer recovery.
    original_gap = execution._coverage_gap
    def gaps(state, task_, refs, conclusion=None):
        values = original_gap(state, task_, refs, conclusion)
        if conclusion is None and not model.contexts:
            return [value for value in values if value != "consumer_or_alternative_source_missing"]
        return values
    execution._coverage_gap = gaps
    result = run(execution)
    assert len(model.contexts) == 2
    assert result.investigation_results[0].status == "no_reuse_opportunity"
    assert any(ref.path == "consumer.py" and ref.kind == "source" for ref in result.evidence)


def test_cache_reuse_requires_explicit_activation_per_investigation(tmp_path):
    execution, _ = prepared(tmp_path, {"provider.py": PROVIDER, "consumer.py": CONSUMER}, [close, close],
        tasks=[task(id="one"), task(id="two")])
    result = run(execution)
    assert len(result.investigation_results) == 2
    assert result.investigation_results[1].status == "no_reuse_opportunity"
    # Same queries activated through tools, not executed/charged twice.
    first = result.investigation_results[0].diagnostics["queries_executed"]
    assert first == result.tool_calls
    state = execution.initial_state()
    state.update(plan=execution.prepared_plan, active_query_keys=[], query_cache={"foreign": {
        "status": "ok", "tool_name": "get_source_excerpt", "data": {"path": "provider.py", "start_line": 1, "end_line": 2}}})
    assert execution._delivered_ranges(state) == {}
    assert execution._delivered_ids(state) == set()


def test_missing_source_tool_does_not_confirm_from_metadata(tmp_path):
    def cannot_compare(context):
        return {"action": "close", "conclusion": {"investigation_id": context["investigation"]["id"],
            "status": "inconclusive", "summary": "No source tool.", "justification": "Source unavailable.", "limitations": ["Source unavailable."]}}
    execution, _ = prepared(tmp_path, {"provider.py": PROVIDER, "consumer.py": CONSUMER}, [cannot_compare], tools=["find_symbols"])
    result = run(execution)
    assert result.investigation_results[0].status == "inconclusive"
    assert not result.candidates


def test_both_bodies_without_comparisons_triggers_one_targeted_reinterpretation(tmp_path):
    def premature(context):
        return {"action": "close", "conclusion": {"investigation_id": context["investigation"]["id"],
            "status": "inconclusive", "summary": "Bodies read but no comparison recorded.",
            "justification": "Need structural comparison.", "limitations": ["Comparison omitted."]}}

    execution, model = prepared(tmp_path, {"provider.py": PROVIDER, "alternative.py": ALTERNATIVE},
        [premature, lambda context: close(context, outcome="equivalent_shareable",
            role="independent_implementation", other="normalize_local")])
    result = run(execution)
    assert len(model.contexts) == 2
    comparison = result.investigation_results[0].comparisons[0]
    assert comparison.outcome == "equivalent_shareable"


def test_missing_sources_do_not_spend_interpretation_turn(tmp_path):
    def no_source_explanation(context):
        return {"action": "close", "conclusion": {"investigation_id": context["investigation"]["id"],
            "status": "inconclusive", "summary": "No source tool available.",
            "justification": "Only metadata tools are enabled.", "limitations": ["Source unavailable."]}}

    execution, model = prepared(tmp_path, {"provider.py": PROVIDER},
        [no_source_explanation], tools=["find_symbols"])
    result = run(execution)
    assert result.investigation_results[0].status == "inconclusive"
    assert not result.candidates
    assert len(model.contexts) == 1


def test_global_conclusion_from_scoped_sample_is_not_accepted(tmp_path):
    def global_close(context):
        response = close(context)
        response["conclusion"]["scope"] = "repository"
        return response
    execution, _ = prepared(tmp_path, {"provider.py": PROVIDER, "consumer.py": CONSUMER}, [global_close] * 5)
    result = run(execution)
    assert result.investigation_results[0].status == "inconclusive"
    assert "scope_not_supported" in result.investigation_results[0].limitations


def test_repeated_query_without_new_information_stops(tmp_path):
    repeated = {"action": "tools", "queries": [{"tool": "search_repository_text", "arguments": {"query": "nothing"},
        "reason": "Search for an alternative."}]}
    execution, model = prepared(tmp_path, {"provider.py": PROVIDER}, [repeated] * 10)
    result = run(execution)
    assert result.investigation_results[0].status == "inconclusive"
    assert len(model.contexts) < 10
    assert not result.candidates


def test_exhausted_tokens_close_without_calling_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "token_budget_policy", lambda: BudgetPolicy(budgets_enabled=True))
    execution, model = prepared(tmp_path, {"provider.py": PROVIDER, "consumer.py": CONSUMER}, [], max_total_tokens=1000)
    execution.tokens = 1000
    result = run(execution)
    assert result.investigation_results[0].status == "inconclusive"
    assert "token_limit" in result.investigation_results[0].justification
    assert not model.contexts


def test_tool_failure_is_retried_without_semantic_schema_repair(tmp_path):
    execution, _ = prepared(tmp_path, {"provider.py": PROVIDER, "consumer.py": CONSUMER}, [close])
    real_execute = execution.tools.execute
    attempts = []
    def flaky(name, args, **kwargs):
        if name == "get_source_excerpt" and args["path"] == "provider.py":
            attempts.append(name)
            if len(attempts) == 1:
                raise ValueError("Temporary fixture read error")
        return real_execute(name, args, **kwargs)
    execution.tools.execute = flaky
    result = run(execution)
    assert len(attempts) == 2
    assert result.investigation_results[0].status == "no_reuse_opportunity"
    assert result.model_calls == 1


def test_structural_schema_failure_does_not_poison_next_investigation(tmp_path):
    invalid_close = {"action": "close", "conclusion": {"investigation_id": "wrong", "status": "inconclusive",
        "summary": "Invalid task ID.", "justification": "Fixture.", "limitations": ["Fixture."]}}
    execution, model = prepared(tmp_path, {"provider.py": PROVIDER, "consumer.py": CONSUMER},
        [invalid_close, invalid_close, close], tasks=[task(id="one"), task(id="two")])
    result = run(execution)
    assert result.investigation_results[0].status == "inconclusive"
    assert result.investigation_results[1].status == "no_reuse_opportunity"
    assert len(model.contexts) == 3


def test_long_symbol_reads_successive_ranges_without_extra_model_calls(tmp_path):
    body = "def normalize_record(value):\n" + "    value = value.strip()\n" * 180 + "    return value.lower()\n"
    execution, _ = prepared(tmp_path, {"provider.py": body, "consumer.py": CONSUMER}, [close])
    result = run(execution)
    assert result.investigation_results[0].status == "no_reuse_opportunity"
    assert result.model_calls == 1
    ranges = [(ref.start_line, ref.end_line) for ref in result.evidence if ref.kind == "source" and ref.path == "provider.py"]
    assert any(low > 1 for low, high in ranges)
    assert max(high for low, high in ranges) == 182


def test_temporary_provider_failure_uses_shared_recovery_and_accounting(tmp_path):
    class Unavailable(Exception):
        status_code = 503
    execution, model = prepared(tmp_path, {"provider.py": PROVIDER, "consumer.py": CONSUMER},
        [Unavailable("Temporary provider outage"), close], provider_retry_backoff_seconds=0)
    result = run(execution)
    assert result.investigation_results[0].status == "no_reuse_opportunity"
    assert result.model_calls == 2
    assert result.accounted_tokens > 200  # The failed, unreported attempt remains conservatively charged.
    assert result.estimated_tokens > 0
    assert not result.deferred_stages
    assert len(model.contexts) == 2


def test_consumer_cannot_become_redundant_implementation_without_comparison(tmp_path):
    def false_candidate(context):
        return close(context, status="reuse_opportunity", outcome="correct_reuse", role="consumer")
    execution, _ = prepared(tmp_path, {"provider.py": PROVIDER, "consumer.py": CONSUMER}, [false_candidate] * 5)
    result = run(execution)
    assert not result.candidates
    assert result.investigation_results[0].status == "inconclusive"
    assert any("independent_behavior_not_demonstrated" in gap
        for gap in result.investigation_results[0].diagnostics["gaps"])


def test_source_header_alone_does_not_cover_function_behavior(tmp_path):
    execution, _ = prepared(tmp_path, {"provider.py": PROVIDER}, [])
    symbol = next(item for item in execution.tools.accessible_snapshot.symbols if item.name == "normalize_record")
    execution.tools.execute("get_source_excerpt", {"path": "provider.py", "start_line": 1, "end_line": 1}, tool_call_id="header")
    assert not execution._symbol_covered(symbol, execution.references())


def test_exact_symbol_marker_is_required_no_fuzzy_suffix(tmp_path):
    execution, _ = prepared(tmp_path, {"provider.py": PROVIDER}, [])
    with pytest.raises(Exception, match="independent_implementations"):
        execution._resolve_implementation("provider.py#record")
    path, symbols = execution._resolve_implementation("provider.py#normalize_record")
    assert path == "provider.py" and len(symbols) == 1


def test_context_recovery_restores_original_documentary_evidence(tmp_path):
    def request_claim(context):
        assert "claim-0" not in context["documentary_context"]["original_claims"]
        return {"action": "tools", "read_document_claim_ids": ["claim-0"]}
    def decide(context):
        assert context["documentary_context"]["original_claims"]["claim-0"]["evidence"][0]["quote"] == "Shared provider."
        return close(context)
    execution, _ = prepared(tmp_path, {"provider.py": PROVIDER, "consumer.py": CONSUMER}, [request_claim, decide])
    result = run(execution)
    assert result.investigation_results[0].status == "no_reuse_opportunity"
    assert result.model_calls == 2


def test_priority_pruning_preserves_strong_leads_and_defseres():
    from server.agents.maintainability.v2.reusability.reuse_opportunity_doc_driven.investigation_workspace import (
        _prune_workspace,
    )

    workspace = {"entities": {}, "deferred_entities": []}
    for index in range(14):
        workspace["entities"][f"alternative-{index}"] = {
            "path": f"alt/{index}.py",
            "symbol_id": f"alternative-{index}",
            "roles": ["alternative"],
            "reasons": ["weak token overlap"],
            "line": 1 + index,
            "relevance": index,
        }
    workspace["entities"]["provider"] = {"path": "provider.py", "symbol_id": "provider",
        "roles": ["provider"], "reasons": ["explicit target"], "line": 1, "relevance": 0}
    workspace["entities"]["consumer"] = {"path": "consumer.py", "symbol_id": "consumer",
        "roles": ["consumer"], "reasons": ["incoming relationship"], "line": 1, "relevance": 0}

    _prune_workspace(workspace, keep=4)

    remaining = workspace["entities"]
    assert remaining["provider"] and remaining["consumer"]
    assert len([item for item in remaining.values() if item["roles"] == ["alternative"]]) == 4
    assert {item["path"] for item in workspace["deferred_entities"]} == {
        f"alt/{index}.py" for index in range(10)
    }


def test_investigation_diagnostics_are_compact_not_raw_workspace():
    from server.agents.maintainability.v2.reusability.reuse_opportunity_doc_driven.investigation import (
        _compact_diagnostics,
    )

    workspace = {
        "entities": {f"id-{index}": {"path": f"file/{index}.py", "symbol_id": f"id-{index}",
            "roles": ["alternative" if index else "provider"], "reasons": ["lead"],
            "line": index, "relevance": index} for index in range(8)},
        "comparisons": [{"outcome": "justified_independence"}],
        "gaps": [],
        "blocked": [],
        "rejected_paths": [{"path": "rejected.py"}],
        "deferred_entities": [{"path": "deferred.py"}],
        "queries_executed": 3,
        "progress": [{"step": index} for index in range(5)],
        "decisions": ["one", "two"],
        "remaining_budget": {"tokens": None},
    }

    diagnostics = _compact_diagnostics(workspace)

    assert diagnostics["queries_executed"] == 3
    assert diagnostics["evidence_entities"]["count"] == 8
    assert len(diagnostics["evidence_entities"]["retained"]) <= 6
    assert "entities" not in diagnostics
    assert diagnostics["comparisons"]["by_outcome"] == {"justified_independence": 1}
    assert diagnostics["progress_steps"] == 5
