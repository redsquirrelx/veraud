"""Canonical schemas retain legacy identities and import without execution cycles."""

import importlib
import subprocess
import sys

import pytest
from pydantic import ValidationError

from server.contracts.legacy_schemes import base, coordinator, investigator, manager


@pytest.mark.parametrize(("module", "old_name", "canonical"), [
    ("server.runtimes.investigation.schemas", "AuditResult", base.AuditResult),
    ("server.runtimes.coordination.schemas", "Consumption", base.Consumption),
    ("modularity.architecture_boundary", "AuditRequest", investigator.ArchitectureBoundaryRequest),
    ("modularity.responsibility", "ResponsibilityResult", investigator.ResponsibilityResult),
    ("modularity.dependency_impact", "ComponentReference", investigator.DependencyComponentReference),
    ("reusability.abstraction", "ComponentReference", investigator.AbstractionComponentReference),
    ("reusability.reuse_opportunity", "InspectRoute", investigator.ReuseInspectRoute),
    ("reusability.component_adaptability", "InspectRoute", investigator.AdaptabilityInspectRoute),
    ("modularity.coordinator", "ModularityAssessment", coordinator.ModularityAssessment),
    ("reusability.coordinator", "Assignment", coordinator.ReusabilityAssignment),
    ("reusability.coordinator", "ReusabilityAssessment", coordinator.ReusabilityAssessment),
    ("manager", "MaintainabilityReport", manager.MaintainabilityReport),
])
def test_legacy_exports_are_the_canonical_classes(module, old_name, canonical):
    path = module if module.startswith("server.") else f"server.agents.maintainability.{module}.schemas"
    assert getattr(importlib.import_module(path), old_name) is canonical


def test_all_registered_outputs_use_the_category_envelopes():
    from server.agents.maintainability.manager.registry import COORDINATORS
    from server.agents.maintainability.modularity.coordinator.registry import (
        INVESTIGATORS as modularity,
    )
    from server.agents.maintainability.reusability.coordinator.registry import (
        INVESTIGATORS as reusability,
    )

    for spec in (modularity | reusability).values():
        assert issubclass(spec.result_class, investigator.InvestigatorResult)
        assert spec.agent_class.execution_type.result_schema is spec.result_class
    for spec in COORDINATORS.values():
        assert issubclass(spec.result_class, coordinator.CoordinatorResult)
    assert issubclass(manager.MaintainabilityReport, manager.ManagerResult)
    assert not issubclass(coordinator.ReusabilityAssessment, coordinator.ModularityAssessment)
    assert manager._MODULARITY_RESULTS == {key: spec.result_class for key, spec in modularity.items()}


def test_coordinator_envelopes_retain_concrete_nested_contracts():
    from typing import get_args

    assert get_args(coordinator.ModularityAssessment.model_fields["invocations"].annotation) == (
        coordinator.InvocationRecord,
    )
    assert get_args(coordinator.ReusabilityAssessment.model_fields["invocations"].annotation) == (
        coordinator.ReusabilityInvocationRecord,
    )
    assert get_args(manager.MaintainabilityReport.model_fields["assessments"].annotation) == (
        manager.CoordinatorAssessment,
    )


def test_relocated_response_schemas_keep_provider_visible_titles():
    assert coordinator.ReusabilitySynthesisDraft.model_json_schema()["title"] == "SynthesisDraft"
    assert investigator.ArchitectureBoundaryRequest.model_json_schema()["title"] == "AuditRequest"
    assert investigator.DependencyComponentReference.model_json_schema()["title"] == "ComponentReference"
    assert investigator.AbstractionComponentReference.model_json_schema()["title"] == "ComponentReference"


@pytest.mark.parametrize("category", ["base", "investigator", "coordinator", "manager"])
def test_canonical_import_first_does_not_load_concrete_execution(category):
    # A fresh interpreter detects cycles hidden by pytest's module import cache.
    script = f"""
import importlib
import sys
importlib.import_module('server.contracts.legacy_schemes.{category}')
assert not any(name.startswith('server.agents.maintainability.') and name.endswith('.agent')
               for name in sys.modules), sorted(sys.modules)
from server.agents.maintainability.manager import MaintainabilityManagerAgent
from server.agents.maintainability.modularity.coordinator import ModularityAgent
from server.agents.maintainability.reusability.coordinator import ReusabilityAgent
"""
    result = subprocess.run([sys.executable, "-c", script], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(("left", "right"), [
    (coordinator.ReusabilityRequest, coordinator.ModularityRequest),
    (manager.MaintainabilityRequest, coordinator.ReusabilityRequest),
    (manager.MaintainabilityRequest, coordinator.ModularityRequest),
    (coordinator.ReusabilityInvestigatorCapability, coordinator.InvestigatorCapability),
    (coordinator.ReusabilityAssignment, coordinator.Assignment),
    (coordinator.ReusabilityInvocationRecord, coordinator.InvocationRecord),
    (coordinator.ReusabilityRawInvocation, coordinator.RawInvocation),
    (coordinator.ReusabilityEvidenceGap, coordinator.EvidenceGap),
    (coordinator.ReusabilityProposedGap, coordinator.ProposedGap),
    (coordinator.ReusabilityFindingContribution, coordinator.FindingContribution),
    (coordinator.ReusabilityConsolidatedFinding, coordinator.ConsolidatedFinding),
    (coordinator.ReusabilitySynthesisDraft, coordinator.SynthesisDraft),
    (manager.AuditAssignment, coordinator.Assignment),
    (manager.CoordinatorAssessment, coordinator.InvocationRecord),
    (manager.RawAssessment, coordinator.RawInvocation),
])
def test_different_domains_and_hierarchy_levels_are_not_subtypes(left, right):
    assert not issubclass(left, right)
    assert not issubclass(right, left)


@pytest.mark.parametrize("request_type", [
    coordinator.ReusabilityRequest,
    manager.MaintainabilityRequest,
    investigator.ComponentAdaptabilityRequest,
])
def test_destination_context_has_one_owner_and_preserves_validation(request_type):
    assert issubclass(request_type, base.TargetContext)
    assert "target_context" not in request_type.__annotations__
    assert "meaningful_context" not in request_type.__dict__
    assert request_type().target_context is None
    assert request_type(target_context="Offline backend").target_context == "Offline backend"
    for invalid in ("", " \t\n", "x" * 6001):
        with pytest.raises(ValidationError):
            request_type(target_context=invalid)


def test_investigator_and_supervisor_scope_limits_remain_distinct():
    targets = [f"module-{index}" for index in range(13)]
    assert investigator.ComponentAdaptabilityRequest(targets=targets).targets == targets
    assert len(investigator.ComponentAdaptabilityRequest(architectural_context="x" * 6001).architectural_context) == 6001
    for request_type in (coordinator.ModularityRequest, coordinator.ReusabilityRequest, manager.MaintainabilityRequest):
        assert issubclass(request_type, base.ScopedAuditRequest)
        with pytest.raises(ValidationError):
            request_type(targets=targets)
        with pytest.raises(ValidationError):
            request_type(architectural_context="x" * 6001)


def test_neutral_delegation_contracts_accept_new_domains_without_modularity_types():
    from typing import Literal

    capability_type = coordinator.AgentCapability[Literal["security"]]
    assignment_type = coordinator.DelegationAssignment[Literal["security"]]
    capability = capability_type(id="security", agent_name="SecurityAgent", capability="Inspect security")
    assignment = assignment_type(invocation_id="security-1", investigator_id=capability.id,
        round=1, question="Inspect security", targets=["app.py"])
    invocation_type = coordinator.AgentInvocation[assignment_type, base.Consumption]
    invocation = invocation_type(assignment=assignment, status="completed", result=base.Consumption(model_calls=2))
    assert invocation_type.model_validate_json(invocation.model_dump_json()) == invocation
    with pytest.raises(ValidationError):
        coordinator.Assignment.model_validate(assignment.model_dump())
    with pytest.raises(ValidationError):
        coordinator.ReusabilityAssignment.model_validate(assignment.model_dump())
