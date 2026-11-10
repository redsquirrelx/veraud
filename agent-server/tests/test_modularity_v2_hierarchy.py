"""Actual Manager -> V2 coordinator -> documentary investigator, offline model."""

import asyncio
import json

import pytest
from langchain_core.messages import AIMessage
from test_architecture_boundary_doc_driven_investigation import (
    Model,
    assess_all,
    verified_tools,
)
from test_architecture_boundary_doc_driven_planning import claim, context

from server.agents.maintainability.v2.manager import (
    AuditResult,
    MaintainabilityManager,
    MaintainabilityRequest,
)
from server.agents.maintainability.v2.manager.config import MaintainabilityConfig
from server.agents.maintainability.v2.modularity.coordinator import AssessmentResult
from server.agents.maintainability.v2.modularity.coordinator.config import (
    ModularityConfig,
)
from server.runtimes.repository.context import RepositoryContext


@pytest.mark.parametrize("provisional", [False, True])
@pytest.mark.parametrize("budgets_on", [True, False])
def test_real_investigator_hierarchy_retains_documentary_context_and_provenance(tmp_path, provisional, budgets_on, monkeypatch):
    from config.agents.budgets import BudgetPolicy
    from server.agent_services.budgeting import policy
    from server.blackboard.identity import AuditIdentity
    from server.blackboard.impls.memory import MemoryBlackboard

    monkeypatch.setattr(policy, "token_budget_policy", lambda: BudgetPolicy(budgets_enabled=budgets_on))
    tools = verified_tools(tmp_path, {"app/__init__.py": "", "app/api.py": "from .store import Store\ndef use(): return Store()\n",
        "app/store.py": "class Store: pass\n"})
    tools.context = RepositoryContext(tools.context.snapshot, tools.context.input.model_copy(update={
        "budget": tools.context.input.budget.model_copy(update={"max_model_calls": 64, "max_tool_calls": 100})}))
    if not budgets_on:
        tools.context = RepositoryContext(tools.context.snapshot, tools.context.input.model_copy(update={
            "budget": tools.context.input.budget.model_copy(update={"max_model_calls": 1, "max_tool_calls": 1,
                "max_total_tokens": 1000, "max_tokens_per_objective": 1000, "max_elapsed_seconds": .001,
                "max_retrieved_characters": 1})}))
        tools.retrieval_budget.limit = 1
    documented = context(tools, [claim()])

    class HierarchyModel(Model):
        async def ainvoke(self, messages, **kwargs):
            payload = json.loads(messages[1].content)
            if "coordinator_catalog" in payload:
                value = {"objective": "Investigate Checkout architecture.", "assignments": [{"coordinator_id": "modularity",
                    "objective": "Investigate Checkout boundaries.", "scope": ["app"], "constraints": [],
                    "rationale": "The request concerns architectural modularity."}], "uncovered_requirements": [], "limitations": []}
            elif "investigator_catalog" in payload:
                value = {"objective": "Investigate Checkout boundaries.", "assignments": [{"investigator_id": "architecture_boundary",
                    "objective": "Investigate the documented Checkout boundary.", "targets": ["app"], "constraints": [],
                    "rationale": "Explicit boundary obligations are available."}], "uncovered_requirements": [], "limitations": []}
            else:
                self.investigator_messages = [*getattr(self, "investigator_messages", []),
                    *(message.content for message in messages)]
                return await super().ainvoke(messages, **kwargs)
            self.contexts.append(payload)
            return AIMessage(content=json.dumps(value), usage_metadata={"input_tokens": 100, "output_tokens": 100, "total_tokens": 200})

    class Tracing:
        async def wrap_stage(self, operation, **metadata):
            return await operation

    model = HierarchyModel(lambda payload: assess_all(payload, "contradicted", status="finding_candidate", candidate=True)
        if provisional else assess_all(payload))
    board, identity = MemoryBlackboard(), AuditIdentity()
    manager = MaintainabilityManager(model, MaintainabilityConfig(max_model_calls=48 if budgets_on else 4,
        max_tool_calls=90 if budgets_on else 0, timeout_seconds=300 if budgets_on else .001,
        max_total_tokens=100_000 if budgets_on else 1000,
        provider_request_interval_seconds=0, invocation_limits=ModularityConfig(max_model_calls=32, max_tool_calls=60,
            provider_request_interval_seconds=0, max_schema_retries=0)), tracing_backend=Tracing(), blackboard=board, audit_identity=identity)
    result = asyncio.run(manager.run(tools, MaintainabilityRequest(objective="Investigate Checkout architecture.", targets=["app"],
        constraints=["Do not modify files."], documented_architecture=documented)))
    assert isinstance(result, AuditResult) and result.status in {"completed", "partial"}
    coordinator = AssessmentResult.model_validate(result.coordinator_results[0].result)
    assert coordinator.node_transitions == ["plan_assessment", "delegate_investigations", "collect_findings", "finalize_assessment"]
    assert len(coordinator.invocations) == 1 and coordinator.invocations[0].assignment.investigator_id == "architecture_boundary"
    investigator = coordinator.invocations[0].result
    assert investigator["investigation_results"] and investigator["evidence"]
    assert all(row["status"] == ("finding_candidate" if provisional else "no_finding") for row in investigator["investigation_results"])
    assert investigator["documentary_synthesis"] is not None
    assert coordinator.invocations[0].assignment.request["documented_architecture"] == documented.model_dump(mode="json")
    native_request = coordinator.invocations[0].assignment.request
    assert not {"objective", "architectural_context", "follow_up", "follow_up_diagnostics"} & native_request.keys()
    assert "Do not modify files." in native_request["constraints"]
    investigator_messages = json.dumps(model.investigator_messages)
    for external in (result.objective, "Investigate Checkout boundaries.", "Investigate the documented Checkout boundary."):
        assert external not in investigator_messages
    assert result.consumption.model_calls == len(model.contexts)
    assert result.consumption.accounted_tokens == 200 * len(model.contexts)
    assert sum("coordinator_catalog" in payload for payload in model.contexts) == 1
    assert sum("investigator_catalog" in payload for payload in model.contexts) == 1
    assert result.node_transitions[-1] == "finalize_audit"
    published = board.query_assessments(identity.run_id)
    assert {item.agent_id for item in published} == {"maintainability_manager", "modularity"}
    root = next(item for item in published if item.agent_id == "maintainability_manager")
    assert root.assessment_ids and root.details["report"] == result.model_dump(mode="json")
    assert bool(board.query_findings(identity.run_id)) == provisional
    from server.reporting import AuditReportAgent, AuditReportRequest
    from server.reporting.docx import render_audit_report_docx

    report = asyncio.run(AuditReportAgent(blackboard=board).run(AuditReportRequest(run_id=identity.run_id)))
    assert render_audit_report_docx(report).startswith(b"PK")
    assert coordinator.coverage.evaluated_investigation_ids
    if provisional:
        assert result.status == coordinator.status == "completed"  # Completed work, not accepted findings.
        assert investigator["candidates"] and all(row["status"] == "finding_candidate" for row in investigator["investigation_results"])
        assert not {"validation_status", "review_rationale"} & investigator["findings"][0].keys()
        assert "validation_status" not in coordinator.consolidated_findings[0].model_dump()
        assert "validation_status" not in next(iter(result.findings.values())).payload
        assert not coordinator.coverage.global_compliance_established


def test_manager_collects_coordinator_findings_from_a_simulated_native_investigator(tmp_path, monkeypatch):
    from test_modularity_v2_execution import (
        finding,
        fixture_registry,
        result,
        simulated_spec,
    )

    from server.agents.maintainability.v2.modularity.coordinator import (
        dispatch,
        registry,
    )

    tools = verified_tools(tmp_path, {"Checkout/api.py": "class Checkout:\n    pass\n"})
    tools.context = RepositoryContext(tools.context.snapshot, tools.context.input.model_copy(update={
        "budget": tools.context.input.budget.model_copy(update={"max_model_calls": 64, "max_tool_calls": 100})}))

    async def produce(instance, tools, request):
        return result(tools, request, [finding(tools)])

    native = fixture_registry()["responsibility"]
    specs = {"responsibility": simulated_spec(native, produce)}
    monkeypatch.setattr(registry, "registered_investigators", lambda: specs)
    monkeypatch.setattr(dispatch, "registered_investigators", lambda: specs)

    class HierarchyModel(Model):
        async def ainvoke(self, messages, **kwargs):
            payload = json.loads(messages[1].content)
            value = ({"objective": "Checkout", "assignments": [{"coordinator_id": "modularity", "objective": "Checkout",
                "scope": ["Checkout"], "constraints": [], "rationale": "Requested modularity."}], "uncovered_requirements": [], "limitations": []}
                if "coordinator_catalog" in payload else {"objective": "Checkout", "assignments": [{"investigator_id": "responsibility",
                    "objective": "Examine Checkout responsibilities.", "targets": ["Checkout"], "constraints": [], "rationale": "Requested cohesion."}],
                    "uncovered_requirements": [], "limitations": []})
            self.contexts.append(payload)
            return AIMessage(content=json.dumps(value), usage_metadata={"input_tokens": 100, "output_tokens": 100, "total_tokens": 200})

    class Tracing:
        async def wrap_stage(self, operation, **metadata):
            return await operation

    model = HierarchyModel(None)
    manager = MaintainabilityManager(model, MaintainabilityConfig(max_model_calls=48, max_tool_calls=90,
        provider_request_interval_seconds=0, invocation_limits=ModularityConfig(max_model_calls=32, max_tool_calls=60,
            provider_request_interval_seconds=0)), tracing_backend=Tracing())
    audit = asyncio.run(manager.run(tools, MaintainabilityRequest(objective="Checkout", targets=["Checkout"])))
    assert audit.status == "completed" and len(audit.findings) == 1
    collected = next(iter(audit.findings.values()))
    assert collected.payload["contributions"][0]["investigator_id"] == "responsibility"
    assert collected.payload["severity"] == "high" and collected.payload["confidence"] == 1.0
    assert not collected.integrity_issues and collected.evidence_refs
    assert audit.consumption.accounted_tokens == 430  # Two actual planning calls plus the child's recorded 30 tokens.
    assert audit.consumption.model_calls == 3 and len(model.contexts) == 2
