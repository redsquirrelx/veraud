r"""Three-level E2Es: real manager -> real coordinators -> six real investigators.

    uv run pytest src/test-agents/test_maintainability_manager_e2e.py -v -s

Only model responses are simulated offline; optional paid smoke:
    $env:MAINTAINABILITY_MANAGER_LIVE = "1"
    uv run pytest src/test-agents/test_maintainability_manager_e2e.py -v -s -k live
"""

import asyncio
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from test_architecture_boundary import fingerprints, toolset
from test_maintainability_manager import BASE, Events
from test_modularity_e2e import ProviderScenario
from test_reusability_e2e import SimulatedProvider

from server.agents.maintainability.reusability.abstraction import AbstractionRequest
from server.agents.maintainability.reusability.component_adaptability import (
    ComponentAdaptabilityRequest,
)
from server.agents.maintainability.manager import (
    MaintainabilityConfig,
    MaintainabilityManagerAgent,
    MaintainabilityReport,
    MaintainabilityRequest,
)
from server.agents.maintainability.reusability.reuse_opportunity import ReuseOpportunityRequest
from server.runtimes.investigation.schemas import Criterion, InvestigationConfig
from server.app.tracing_port import LangSmithTracingBackend


@pytest.fixture
def audit_repository(tmp_path):
    root = tmp_path / "checkout"
    shutil.copytree(Path(__file__).parent / "fixtures" / "reusability", root)
    (root / "domain").mkdir()
    (root / "storage").mkdir()
    (root / "domain" / "service.py").write_text("from storage.db import save\n\ndef execute(order):\n    save(order)\n    return f'Report: {order}'\n", encoding="utf-8")
    (root / "storage" / "db.py").write_text("def save(order):\n    return {'stored': order}\n", encoding="utf-8")
    (root / "domain" / "report.py").write_text("REPORT_VERSION = 2\n\ndef render(order):\n    return f'v{REPORT_VERSION}: {order}'\n", encoding="utf-8")
    return root


def request():
    return MaintainabilityRequest(targets=["domain", "storage", "policy.py"], depth="thorough",
        dimension_targets={"modularity": ["domain", "storage"], "reusability": ["policy.py"]},
        target_context="Offline processing with a supplied backend, without changing the component source.",
        criteria=[Criterion(id="domain-rule", description="Domain must not import storage.", origin="explicit", provenance="Declared seed architecture rule"),
            *AbstractionRequest().criteria, *ReuseOpportunityRequest().criteria, *ComponentAdaptabilityRequest().criteria])


def tools(root):
    return toolset(root, max_model_calls=400, max_tool_calls=600, max_total_tokens=1_500_000,
        max_tokens_per_objective=1_500_000, max_retrieved_characters=1_200_000, max_elapsed_seconds=1200)


def limits(**updates):
    return MaintainabilityConfig(**({"max_total_tokens": 1_500_000,
        "provider_rate_limits": {"requests_per_minute": None, "tokens_per_minute": None},
        "invocation_limits": {"max_rounds": 2, "max_total_tokens": 500_000,
            "invocation_limits": InvestigationConfig(max_model_calls=10, max_total_tokens=120_000, max_tool_calls=12, max_iterations=1)}} | updates))


class NestedProvider(SimulatedProvider):
    def __init__(self, root, *, recover=False):
        super().__init__(root, "provider_failure" if recover else "direct")
        self.modularity = ProviderScenario(follow_up=True)
        self.manager_calls = 0

    async def respond(self, messages, schema=None):
        context = json.loads(messages[1].content)
        if "assessments" in context:
            self.manager_calls += 1
            self.scenario = "direct"  # Provider recovers before a targeted retry.
            return AIMessage(content=json.dumps({"summary": "Merge scoped coordinator summaries and retain nested provenance."}),
                usage_metadata={"input_tokens": 100, "output_tokens": 100, "total_tokens": 200})
        reuse = any(k in context for k in ("abstraction_candidates", "candidate_groups", "selected_components"))
        if "invocations" in context:
            reuse = context["invocations"][0]["investigator_id"] in {"abstraction", "reuse_opportunity", "component_adaptability"}
        if reuse:
            return await super().respond(messages, schema)
        return await self.modularity.ainvoke(messages)


def artifact_report(root, report, events):
    # Progress evidence lives beside the audited checkout, never inside it.
    artifact = root.parent / "artifacts"
    artifact.mkdir(exist_ok=True)
    (artifact / "report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    (artifact / "events.json").write_text(json.dumps(events.records, indent=2), encoding="utf-8")
    (artifact / "nodes.json").write_text(json.dumps(report.node_transitions, indent=2), encoding="utf-8")
    print("\n[NESTED E2E] manager/coordinators/investigators/indexes/tools: REAL; model: SIMULATED")
    print("MANAGER", report.status, report.termination_reason, "covered:", report.coverage.covered)
    for assessment in report.assessments:
        print(" COORDINATOR", assessment.assignment.investigator_id, "attempt", assessment.assignment.attempt, assessment.status)
        if assessment.result:
            for invocation in assessment.result.invocations:
                print("  INVESTIGATOR", invocation.assignment.investigator_id, "round", invocation.assignment.round, invocation.status)
    print("ARTIFACTS", artifact)


def run_nested(root, *, recover=False):
    model, events = NestedProvider(root, recover=recover), Events()
    before = fingerprints(root)
    agent = MaintainabilityManagerAgent(model, limits(), tracing_backend=events)
    assert agent.factory is None
    report = asyncio.run(agent.run(tools(root), request()))
    artifact_report(root, report, events)
    assert fingerprints(root) == before
    assert MaintainabilityReport.model_validate_json(report.model_dump_json()) == report
    assert all(e.snapshot_hash == report.snapshot_hash for e in report.evidence.values())
    # Correlation survives both delegation levels.
    children = [(name, m) for name, m in events.records if name != "maintainability-coordinator"]
    assert children and all(m["audit_id"] == report.assessment_id and m["coordinator_attempt_id"] for _, m in children)
    return report


def test_broader_nested_first_pass_and_internal_coordinator_followup(audit_repository):
    report = run_nested(audit_repository)
    assert report.status == "complete", report.model_dump_json(indent=2)
    assert report.node_transitions == [*BASE, "finalize_audit"] and len(report.assessments) == 2
    modularity, reusability = [r.result for r in report.assessments]
    assert modularity.rounds_completed == 2 and len(modularity.invocations) == 4
    assert modularity.invocations[-1].assignment.investigator_id == "responsibility"
    assert reusability.rounds_completed == 1 and len(reusability.invocations) == 3
    assert all(r.evidence_sufficient for r in report.assessments)
    assert len(report.findings) >= 4 and all(r.result.consolidated_findings for r in report.assessments)


def test_nested_refinement_recovers_only_incomplete_coordinator(audit_repository):
    report = run_nested(audit_repository, recover=True)
    assert report.status == "complete", report.model_dump_json(indent=2)
    assert [a.assignment.investigator_id for a in report.assessments] == ["modularity", "reusability", "reusability"]
    assert report.assessments[1].status == "partial" and report.assessments[2].evidence_sufficient
    assert [r.decision.route for r in report.synthesis_history] == ["no", "yes"]
    assert report.node_transitions == [*BASE, "refine_audit_plan", "delegate_auditors", "collect_assessments", "synthesize_assessments", "finalize_audit"]


@pytest.mark.skipif(os.getenv("MAINTAINABILITY_MANAGER_LIVE") != "1", reason="Explicit opt-in required for paid provider calls")
def test_live_nested_coordinators(audit_repository):
    from run_architecture_boundary import load_test_model

    from server.runtimes.repository.model_runtime import close_model_clients

    async def execute():
        model, settings = load_test_model(os.getenv("MAINTAINABILITY_MANAGER_AGENT_CONFIG", "dummy"))
        config = MaintainabilityConfig(max_rounds=1, max_output_tokens=min(4000, settings.max_tokens), timeout_seconds=900,
            investigation_start_interval_seconds=1)
        before = fingerprints(audit_repository)
        try:
            report = await MaintainabilityManagerAgent(model, config, tracing_backend=LangSmithTracingBackend()).run(tools(audit_repository), request())
            artifact = audit_repository.parent / "live-report.json"
            artifact.write_text(report.model_dump_json(indent=2), encoding="utf-8")
            print("LIVE", settings.provider, settings.name, report.status, report.coverage.covered, artifact)
            assert len(report.assessments) == 2 and any(r.evidence_sufficient for r in report.assessments)
            assert not any(g.kind == "synthesis_failure" for g in report.unresolved_gaps)
            assert fingerprints(audit_repository) == before
        finally:
            await close_model_clients(SimpleNamespace(llm=model))
    asyncio.run(execute())
