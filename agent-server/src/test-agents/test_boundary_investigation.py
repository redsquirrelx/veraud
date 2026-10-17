"""Regression checks for discovery, coverage, progress and provider context retention."""

import asyncio
import json
from types import SimpleNamespace

from langchain_core.messages import AIMessage, ToolMessage
from test_architecture_boundary import (
    PLAN,
    ScriptedModel,
    audit,
    call,
    evaluation,
    request,
    review,
    toolset,
)

from server.agents.maintainability.modularity.architecture_boundary import (
    ArchitectureBoundaryAgent,
    BoundaryConfig,
)
from server.agents.maintainability.modularity.architecture_boundary.discovery import (
    BoundaryDiscovery,
)
from server.agents.maintainability.modularity.architecture_boundary.support import (
    supports_role,
)
from server.runtimes.investigation.messages import compact_tool_history

pytest_plugins = ["test_architecture_boundary"]


def test_discovery_exposes_unvisited_boundaries_without_creating_evidence(repo):
    tools = toolset(repo)
    discovery = BoundaryDiscovery(tools.accessible_snapshot)
    coverage = discovery.coverage([])
    assert coverage["boundary_count"] >= 1
    assert any("storage/db.py" in item["uninspected_paths"] for item in coverage["boundaries"])
    assert not tools.retrieved_evidence
    result, model, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"), evaluation, review()])
    assert result.investigation_coverage["inspected_file_count"] == 1
    assert json.loads(model.history[0][1].content)["boundary_coverage"]["boundary_count"] >= 1


def test_cycle_claim_cannot_override_observed_cycle_with_complete_flag(repo):
    (repo / "storage" / "db.py").write_text("from domain.service import execute\n\ndef save():\n    return execute()\n")

    def no_cycles(messages):
        value = evaluation(messages)
        context = json.loads(messages[1].content)
        sources = [item for item in context["evidence"] if item["kind"] == "source"]
        for check in value["claim_checks"]:
            check.update(claim_kind="absence_of_cycles", coverage_complete=True,
                scope_paths=[item["path"] for item in sources],
                support=[{"evidence_id": item["id"], "role": "dependency", "observation": "Import inspected"}
                    for item in sources])
        return value

    result, _, _ = audit(repo, [PLAN, call(),
        call(arguments={"path": "storage/db.py", "start_line": 1, "end_line": 4}, identifier="db"),
        AIMessage(content="Ready"), no_cycles, review()], max_iterations=1)
    assert result.findings[0].validation_status == "insufficient_evidence"
    assert "boundary_indexed_cycle_observed" in result.findings[0].validation_issues


def test_isolation_requires_support_for_known_third_endpoint(repo):
    (repo / "client.py").write_text("from storage.db import save\n\ndef run():\n    save()\n")

    def isolation(messages):
        value = evaluation(messages)
        sources = [item for item in json.loads(messages[1].content)["evidence"] if item["kind"] == "source"]
        for check in value["claim_checks"]:
            check.update(claim_kind="isolation", coverage_complete=True,
                scope_paths=[item["path"] for item in sources],
                support=[{"evidence_id": item["id"], "role": role, "observation": "Source inspected"}
                    for item in sources for role in ("implementation", "usage", "composition")])
        return value

    result, _, _ = audit(repo, [PLAN, call(),
        call(arguments={"path": "storage/db.py", "start_line": 1, "end_line": 2}, identifier="db"),
        AIMessage(content="Ready"), isolation, review()], max_iterations=1)
    assert "boundary_related_endpoints_not_supported" in result.findings[0].validation_issues


def test_repeated_nonempty_investigation_stops_and_retains_closing_review(repo):
    result, _, _ = audit(repo, [PLAN, call(), AIMessage(content="Ready"),
        lambda messages: evaluation(messages, sufficient=False),
        call(identifier="repeat-1"), call(identifier="repeat-2"), call(identifier="repeat-3"), review()],
        max_iterations=10)
    assert result.termination_reason == "no_investigation_progress"
    assert result.critical_review is not None
    assert result.evidence


def test_conceptual_question_gets_actionable_module_level_configuration_read(repo):
    (repo / "database_config.py").write_text('DATABASE_URL = "sqlite:///shared.db"\n')
    plan = {**PLAN, "hypotheses": [{"id": "h1", "question": "Is database configuration shared?",
        "evidence_needed": ["Inspect database construction and configuration"]}]}

    def unresolved(messages):
        return {"sufficient": False, "hypotheses": [{**plan["hypotheses"][0], "status": "inconclusive"}],
            "candidates": [], "claim_checks": [], "missing_information": ["Inspect database configuration"]}

    result, model, _ = audit(repo, [plan, AIMessage(content="Need database configuration"),
        unresolved, {"findings": [], "limitations": []}], max_iterations=1)
    tasks = json.loads(model.history[-1][1].content)["evidence_recovery_tasks"]
    reads = next(item for item in tasks if item["id"] == "h1")["next_source_reads"]
    assert reads[0]["arguments"]["path"] == "database_config.py"
    assert not result.evidence  # Navigation did not silently inspect the suggested code.


def test_compaction_preserves_cited_source_and_native_tool_pairs():
    messages = []
    for index in range(4):
        messages.extend([call(identifier=str(index)), ToolMessage(tool_call_id=str(index),
            content=json.dumps({"evidence": [{"id": str(index)}], "source": "x" * 5000}))])
    compacted = compact_tool_history(messages, 1000, {"0"})
    assert compacted[1].content == messages[1].content
    assert json.loads(compacted[3].content)["history_compacted"] is True
    assert len(compacted) == len(messages)
    assert compacted[-1].content == messages[-1].content
    assert "history_compacted" not in messages[3].content


def test_configuration_and_typescript_module_extensions_have_bounded_support():
    for path, content in [("config.json", '{"database": "shared"}'),
                          ("config.yaml", "database: shared"),
                          ("client.mts", "export const client = createClient();")]:
        source = SimpleNamespace(path=path, content=content)
        reference = SimpleNamespace(kind="source", start_line=1, end_line=1)
        assert supports_role(source, reference, "declaration")
        if path.endswith("yaml"):
            assert not supports_role(source, reference, "implementation")


def test_token_headroom_stops_exploration_but_preserves_critical_review(repo):
    class MeteredModel(ScriptedModel):
        async def ainvoke(self, messages, **kwargs):
            response = await super().ainvoke(messages, **kwargs)
            return response.model_copy(update={"usage_metadata": {
                "input_tokens": 10_000, "output_tokens": 1, "total_tokens": 10_001}})

    model = MeteredModel([PLAN, call(), AIMessage(content="Ready"),
        lambda messages: evaluation(messages, sufficient=False), review()])
    result = asyncio.run(ArchitectureBoundaryAgent(model, BoundaryConfig(
        max_total_tokens=60_000, provider_rate_limits={"requests_per_minute": None, "tokens_per_minute": None},
    )).run(toolset(repo), request()))
    assert result.termination_reason == "token_limit"
    assert result.critical_review is not None
    assert result.findings[0].validation_status == "accepted"
    assert result.hypotheses[0].status == "inconclusive"
    assert result.missing_information
    assert result.accounted_tokens == 50_005
    assert result.model_calls == 5
    assert any("token_budget_reserved_for_closing" in item and "effective_limit=60000" in item
        for item in result.limitations)


def test_model_tool_envelope_retains_source_without_repeating_provenance(repo):
    result, model, tools = audit(repo, [PLAN, call(), AIMessage(content="Ready"), evaluation, review()])
    response = next(item for item in model.history[2] if isinstance(item, ToolMessage))
    payload = json.loads(response.content)
    assert "from storage.db import save" in json.dumps(payload["data"])
    assert "budget_usage" not in payload
    assert all("snapshot_hash" not in item and "content_hash" not in item for item in payload["evidence"])
    assert result.evidence[0].content_hash == tools.retrieved_evidence[0].content_hash
    context = json.loads(model.history[-1][1].content)
    assert "boundary_coverage" not in context
    assert "hypotheses" not in context["evaluation"]
    assert context["hypotheses"]


def test_structured_nodes_drop_inventory_payload_but_keep_cited_source():
    source = ToolMessage(tool_call_id="read", content=json.dumps({
        "evidence": [{"id": "source", "kind": "source"}], "data": {"content": "save()"}}))
    inventory = ToolMessage(tool_call_id="list", content=json.dumps({
        "evidence": [{"id": "metadata", "kind": "metadata"}], "data": {"items": ["file"] * 500}}))
    messages = [call(identifier="read"), source, call(identifier="list"), inventory]
    compacted = compact_tool_history(messages, 100_000, {"source"}, compact_metadata=True)
    assert compacted[1].content == source.content
    assert json.loads(compacted[3].content)["history_compacted"]
    assert "items" in json.loads(inventory.content)["data"]
