"""Manager -> testability coordinator -> TestControllability stub, offline hierarchy wiring."""

import asyncio
import json

from langchain_core.messages import AIMessage
from test_architecture_boundary_doc_driven_investigation import (
    Model,
    verified_tools,
)
from test_architecture_boundary_doc_driven_planning import claim, context

from server.agents.maintainability.v2.manager import (
    AuditResult,
    MaintainabilityManager,
    MaintainabilityRequest,
)
from server.agents.maintainability.v2.manager.config import MaintainabilityConfig
from server.agents.maintainability.v2.modularity.coordinator.config import (
    ModularityConfig,
)
from server.agents.maintainability.v2.testability.test_controllability_doc_driven import (
    TestControllabilityResult,
)
from server.agents.maintainability.v2.testability.test_controllability_doc_driven.schemas import (
    TestControllabilityFinding,
)
from server.contracts.audit import (
    Criterion,
    EvidenceReference,
    InvestigationPlan,
)


class Tracing:
    async def wrap_stage(self, operation, **metadata):
        return await operation


def test_hierarchy_wires_manager_testability_and_test_controllability(tmp_path, monkeypatch):
    from server.agents.maintainability.v2.testability import (
        test_controllability_doc_driven,
    )

    tools = verified_tools(tmp_path, {"App/api.py": "from .store import Store\ndef use(): return Store()\n"})
    documented = context(tools, [claim()])

    class HierarchyModel(Model):
        async def ainvoke(self, messages, **kwargs):
            payload = json.loads(messages[1].content)
            self.contexts.append(payload)
            if "coordinator_catalog" in payload:
                value = {"objective": "Inspect testability.",
                    "assignments": [{"coordinator_id": "testability",
                        "objective": "Inspect testability.",
                        "scope": ["App"],
                        "constraints": [],
                        "rationale": "The user question is about controllability."}],
                    "uncovered_requirements": [], "limitations": []}
            elif "investigator_catalog" in payload:
                value = {"objective": "Inspect test controllability.",
                    "assignments": [{"investigator_id": "test_controllability",
                        "objective": "Inspect controllability of the assigned scope.",
                        "targets": ["App"],
                        "constraints": [],
                        "rationale": "TestControllability is the registered investigator."}],
                    "uncovered_requirements": [], "limitations": []}
            else:
                return await super().ainvoke(messages, **kwargs)
            return AIMessage(content=json.dumps(value),
                usage_metadata={"input_tokens": 100, "output_tokens": 100, "total_tokens": 200})

    async def stub_run(self, tools, request):
        snapshot = tools.accessible_snapshot
        file = next(item for item in snapshot.files if item.path == "App/api.py")
        commit = snapshot.repository.commit if getattr(snapshot, "repository", None) else None
        remote = snapshot.repository
        snapshot_hash = remote.snapshot_hash
        evidence = EvidenceReference(
            id="evidence-1", snapshot_hash=snapshot_hash, commit=commit, path=file.path,
            file_id=file.id, content_hash=file.content_hash, kind="source",
            start_line=1, end_line=2, tool_call_id="stub-run")
        criterion = Criterion(id="test-controllability",
            description="Components can be exercised with controlled conditions.",
            origin="design_principle", provenance="Testability integration test.")
        invocation_finding = TestControllabilityFinding(
            id="finding-stub", title="Concrete construction",
            description="Component constructs its dependency directly.", criterion_id="test-controllability",
            kind="design_observation", components=[file.path], evidence_ids=[evidence.id],
            evidence=[evidence], justification="Direct source inspection.",
            modularity_impact="The failure scenario cannot be driven by an independent test.",
            severity="medium", confidence=1.0, recommendation="Introduce a control seam.",
            criterion=criterion, validation_status="insufficient_evidence",
            review_rationale="Integration test stub.")
        return TestControllabilityResult(
            repository_id=remote.name,
            commit=commit, snapshot_hash=snapshot_hash, objective=request.objective,
            plan=InvestigationPlan(objectives=[request.objective], components=[file.path], hypotheses=[]),
            findings=[invocation_finding], hypotheses=[], missing_information=[],
            limitations=["Integration test stub."], termination_reason="sufficient_evidence",
            model_calls=0, tool_calls=0, iterations=0, accounted_tokens=0, estimated_tokens=0,
            evidence=[evidence], investigation_results=[], candidates=[])

    monkeypatch.setattr(test_controllability_doc_driven.TestControllabilityAgent, "run", stub_run)

    manager = MaintainabilityManager(
        HierarchyModel(None),
        MaintainabilityConfig(max_model_calls=48, max_tool_calls=90,
            provider_request_interval_seconds=0,
            invocation_limits=ModularityConfig(max_model_calls=32, max_tool_calls=60,
                provider_request_interval_seconds=0)),
        tracing_backend=Tracing())
    result = asyncio.run(manager.run(tools, MaintainabilityRequest(
        objective="Inspect controllability blockers in App.", targets=["App"],
        documented_architecture=documented)))

    assert isinstance(result, AuditResult)
    assert result.coordinator_results, "the testability coordinator must have run"
    coordinator = result.coordinator_results[0]
    coordinator_result = coordinator.result
    assert coordinator_result is not None and coordinator_result["termination_reason"] == "assessment_completed"
    assert any(receipt["error"] is None for receipt in coordinator_result["invocations"])


def test_dispatch_forwards_documented_architecture_and_keeps_internal_objective(tmp_path):
    """The web audit transports architecture context only to investigators declaring it."""
    from server.agents.maintainability.v2.testability.coordinator.dispatch import (
        investigator_request,
    )
    from server.agents.maintainability.v2.testability.coordinator.registry import (
        registered_investigators,
    )
    from server.agents.maintainability.v2.testability.coordinator.schemas import (
        InvestigationAssignment,
        TestabilityRequest,
    )

    tools = verified_tools(tmp_path, {"App/api.py": "class Api:\n    pass\n"})
    documented = context(tools, [claim()])
    specification = registered_investigators()["test_controllability"]
    # Production passes the validate_plan(...) assignment (InvestigationAssignment), not the DelegationAssignment envelope.
    assignment = InvestigationAssignment(investigator_id="test_controllability",
        objective="Inspect controllability of the assigned scope.", targets=["App"],
        constraints=[], rationale="Controllers only.")
    request = TestabilityRequest(objective="Delegated testability objective.",
        targets=["App"], documented_architecture=documented)

    child = investigator_request(specification, assignment, request, tools.accessible_snapshot.repository)
    assert child.documented_architecture is not None
    assert child.documented_architecture.document_index == documented.document_index
    # The investigator executes its own internal objective; the delegated one is not instructions.
    assert child.objective == specification.request_class().objective
