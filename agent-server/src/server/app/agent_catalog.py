"""Backend discovery over the execution, configuration and domain registries.

Discovery never constructs agents, models, scanners or repository toolsets.
Internal participants are described without registering them as HTTP agents.
"""

from importlib import import_module
from itertools import combinations
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel, Field

from config.agents.catalog import describe_agent_config

from .agent_registry import UnknownAgentError


class AgentDescriptor(BaseModel):
    agent_id: str
    name: str
    role: str
    requires_model: bool
    configuration_id: str | None = None
    model_configuration_id: str | None = None
    execution_modes: list[Literal["direct", "pipeline", "audit", "internal", "snapshot"]]
    workflow_ids: list[str] = Field(default_factory=list)
    quality_attributes: list[str] = Field(default_factory=list,
        description="Quality contexts supported by this participant; shared agents may list several. Not execution status.")
    parent_ids: list[str] = Field(default_factory=list)
    child_ids: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    availability: Literal["available", "not_executed"] = "available"
    description: str
    detail_url: str


class AgentDetail(AgentDescriptor):
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    configuration: dict[str, Any] | None = None


class WorkflowSelection(BaseModel):
    attributes: list[str]
    stages: list[str]
    model_configuration_ids: list[str]


class WorkflowDescriptor(BaseModel):
    workflow_id: str
    run_url: str
    stages: list[str] = Field(description="Default callback keys; consult attribute_selections for selected attributes.")
    agent_ids: list[str]
    model_configuration_groups: dict[str, list[str]]
    supported_attributes: list[str] = Field(default_factory=list)
    attribute_selections: list[WorkflowSelection] = Field(default_factory=list)
    input_schema: dict[str, Any]
    description: str


class AgentCatalog(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    agents: list[AgentDescriptor]
    workflows: list[WorkflowDescriptor]


def _symbol(package, name):
    return getattr(import_module("server.agents." + package), name)


def _definitions(service):
    """Return descriptors and optional typed input/output contracts, lazily."""
    from ..agents.maintainability.manager.registry import COORDINATORS
    from ..agents.maintainability.modularity.coordinator.registry import (
        INVESTIGATORS as MODULARITY,
    )
    from ..agents.maintainability.reusability.coordinator.registry import (
        INVESTIGATORS as REUSABILITY,
    )
    from .audit_models import MAINTAINABILITY_AGENT_TYPES
    from .pipeline_service import default_pipeline_registry
    from .project_architecture_definition import ProjectArchitectureInput
    from .quality_audit_definition import QualityAuditInput

    entries = {}
    contracts = {}

    def add(identifier, name, role, modes, description, *, config=None, model=True, model_config=None,
            workflows=(), attributes=(), parents=(), children=(), aliases=(), availability="available", request=None, result=None):
        entries[identifier] = AgentDescriptor(agent_id=identifier, name=name, role=role, requires_model=model,
            configuration_id=config, model_configuration_id=(model_config or identifier) if model else None,
            execution_modes=modes, description=description, workflow_ids=list(workflows), parent_ids=list(parents),
            quality_attributes=list(attributes), child_ids=list(children), aliases=list(aliases), availability=availability,
            detail_url=f"/api/agents/catalog/{identifier}")
        contracts[identifier] = (request, result)

    # Direct execution remains authoritative, including additional registered agents.
    for identifier in service.list_agents():
        add(identifier, identifier, "direct_agent", ["direct", "audit", "pipeline"] if identifier == "functional_adequacy" else ["direct"],
            "Registered for direct execution and repository-backed quality audits." if identifier == "functional_adequacy" else "Registered for POST /api/agents/run.",
            config="functional_adequacy" if identifier == "functional_adequacy" else None,
            workflows=["quality-audit", "functional-adequacy"] if identifier == "functional_adequacy" else [],
            attributes=["functional_adequacy"] if identifier == "functional_adequacy" else [])

    project_agents = (
        ("orientation", "project_orientation", "ProjectOrientationAgent", "OrientationResult"),
        ("architecture", "project_architecture", "ProjectArchitectureAgent", "ArchitectureResult"),
        ("semantic_validation", "project_semantic_validation", "ProjectSemanticValidationAgent", "SemanticValidationResult"),
    )
    for identifier, package, name, result in project_agents:
        add(identifier, name, "repository_agent", ["pipeline"], "Repository-backed project analysis stage.",
            config=package, workflows=["project-architecture"], aliases=[package],
            result=_symbol(f"project_analysis.{package}.schemas", result))

    add("maintainability_manager", "MaintainabilityManagerAgent", "manager", ["audit", "pipeline"],
        "Coordinates the implemented maintainability dimensions over one audit snapshot.",
        config="maintainability_manager", workflows=["quality-audit"], attributes=["maintainability"], children=COORDINATORS,
        request=_symbol("maintainability.manager.schemas", "MaintainabilityRequest"),
        result=_symbol("maintainability.manager.schemas", "MaintainabilityReport"))
    for identifier, spec in COORDINATORS.items():
        investigators = MODULARITY if identifier == "modularity" else REUSABILITY
        add(identifier, spec.agent_class.__name__, "coordinator", ["internal"],
            "Coordinates its registered investigators; invoked by the maintainability manager.",
            config=identifier, workflows=["quality-audit"], attributes=["maintainability"], parents=["maintainability_manager"],
            children=investigators, request=spec.request_class, result=spec.result_class)
        for child, investigator in investigators.items():
            add(child, investigator.agent_class.__name__, "investigator", ["internal"],
                investigator.capability.capability, config=child, workflows=["quality-audit"], attributes=["maintainability"], parents=[identifier],
                request=investigator.request_class, result=investigator.result_class)

    # Existing supervisor components are discoverable, not new standalone routes.
    security_components = (
        ("sast_scanner", "SASTScannerAgent", False, "Static source pattern scanner."),
        ("secret_scanner", "SecretScannerAgent", False, "Heuristic credential scanner."),
        ("sca_dependency", "SCADependencyAgent", False, "Dependency manifest scanner."),
        ("knowledge_enrichment", "KnowledgeEnrichmentAgent", False, "Security knowledge enrichment."),
        ("remediation_synthesizer", "RemediationSynthesizerAgent", True, "Proposes remediations; does not apply patches."),
        ("patch_validator", "PatchValidatorAgent", False, "Proposal validation does not establish technical verification."),
        ("security_verifier", "SecurityVerifierAgent", False, "Legacy filtering does not confirm vulnerability exploitability."),
        ("dast_sandbox", "DASTSandboxAgent", False, "Placeholder; real DAST is not executed by the audit."),
    )
    add("security", "SecuritySupervisorAgent", "security_pipeline", ["audit", "pipeline"],
        "Read-only security audit wrapping existing scanners and bounded remediation proposals.", config="security",
        workflows=["quality-audit"], attributes=["security"], children=[item[0] for item in security_components], aliases=["security_manager"],
        request=_symbol("security.audit", "SecurityAuditRequest"), result=_symbol("security.audit", "SecurityAuditResult"))
    for identifier, name, model, description in security_components:
        add(identifier, name, "security_component", ["internal"], description, model=model, model_config="security",
            workflows=["quality-audit"], attributes=["security"], parents=["security"],
            availability="not_executed" if identifier == "dast_sandbox" else "available")

    add("audit_report", "AuditReportAgent", "report_generator", ["internal", "snapshot"],
        "Deterministic ten-section report from Blackboard; no model or repository reads.", model=False,
        workflows=["quality-audit"], attributes=["maintainability", "security", "functional_adequacy"], request=_symbol("audit_report.schemas", "AuditReportRequest"),
        result=_symbol("audit_report.schemas", "SoftwareAuditReport"))

    pipelines = default_pipeline_registry()
    groups = {"maintainability": list(MAINTAINABILITY_AGENT_TYPES), "security": ["security"], "functional_adequacy": ["functional_adequacy"]}
    selections = [
        WorkflowSelection(attributes=attributes,
            stages=pipelines["quality-audit"].resolve_stages(SimpleNamespace(attributes=attributes)),
            model_configuration_ids=[agent for attribute in attributes for agent in groups[attribute]])
        for size in range(1, len(groups) + 1) for selection in combinations(groups, size)
        for attributes in [list(selection)]
    ]
    workflows = [
        WorkflowDescriptor(workflow_id="project-architecture", run_url="/api/pipelines/project-architecture/run",
            stages=pipelines["project-architecture"].stages, agent_ids=[item[0] for item in project_agents],
            model_configuration_groups={item[0]: [item[0]] for item in project_agents},
            input_schema=ProjectArchitectureInput.model_json_schema(),
            description="Project orientation, architecture and semantic validation with retained repository evidence."),
        WorkflowDescriptor(workflow_id="quality-audit", run_url="/api/pipelines/quality-audit/run",
            stages=pipelines["quality-audit"].stages,
            agent_ids=sorted(key for key, item in entries.items() if "quality-audit" in item.workflow_ids),
            model_configuration_groups=groups, attribute_selections=selections,
            supported_attributes=list(groups), input_schema=QualityAuditInput.model_json_schema(),
            description="Independent or joint attributes with one snapshot, Blackboard and JSON/Word report. "
                "Select groups by attribute; stage_configs keys are the listed model participants."),
    ]
    return entries, contracts, workflows


def list_agent_catalog(service) -> AgentCatalog:
    entries, _, workflows = _definitions(service)
    return AgentCatalog(agents=[entries[key] for key in sorted(entries)], workflows=workflows)


def describe_catalog_agent(service, agent_id: str) -> AgentDetail:
    entries, contracts, _ = _definitions(service)
    if agent_id not in entries:
        agent_id = next((key for key, item in entries.items() if agent_id in item.aliases), agent_id)
    if agent_id not in entries:
        raise UnknownAgentError(f"Unknown catalog agent: {agent_id!r}")
    descriptor = entries[agent_id]
    request, result = contracts[agent_id]
    schemas = service.describe_agent(agent_id) if "direct" in descriptor.execution_modes else {}
    return AgentDetail(**descriptor.model_dump(),
        input_schema=request.model_json_schema() if request else schemas.get("input_schema"),
        output_schema=result.model_json_schema() if result else schemas.get("output_schema"),
        configuration=describe_agent_config(descriptor.configuration_id) if descriptor.configuration_id else None)
