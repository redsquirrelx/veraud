"""Lazy configuration descriptions for a single-agent settings panel.

This catalog describes existing execution contracts; it neither registers HTTP
agents nor creates providers, toolsets, repositories or credentials.
"""

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

from pydantic import BaseModel

from .execution import (
    AgentExecutionConfig,
    CoordinatorConfig,
    InvestigationConfig,
    SourceExcerptConfig,
)
from .levels import ConfigLevel, apply_settings, fields_for_level, settings_type
from .model import ModelSettings


@dataclass(frozen=True)
class AgentConfigSpec:
    package: str
    config_name: str
    request_name: str | None
    role: str
    shared_config: type[BaseModel] | None = None


AGENT_CONFIGS = {
    "code_comprehension": AgentConfigSpec("maintainability.analysability.code_comprehension", "CodeComprehensionConfig", "CodeComprehensionRequest", "investigator"),
    "architecture_boundary": AgentConfigSpec("maintainability.modularity.architecture_boundary", "BoundaryConfig", "AuditRequest", "investigator", InvestigationConfig),
    "responsibility": AgentConfigSpec("maintainability.modularity.responsibility", "ResponsibilityConfig", "ResponsibilityRequest", "investigator", InvestigationConfig),
    "dependency_impact": AgentConfigSpec("maintainability.modularity.dependency_impact", "DependencyImpactConfig", "DependencyImpactRequest", "investigator"),
    "abstraction": AgentConfigSpec("maintainability.reusability.abstraction", "AbstractionConfig", "AbstractionRequest", "investigator"),
    "reuse_opportunity": AgentConfigSpec("maintainability.reusability.reuse_opportunity", "ReuseOpportunityConfig", "ReuseOpportunityRequest", "investigator"),
    "component_adaptability": AgentConfigSpec("maintainability.reusability.component_adaptability", "ComponentAdaptabilityConfig", "ComponentAdaptabilityRequest", "investigator"),
    "modularity": AgentConfigSpec("maintainability.modularity.coordinator", "ModularityConfig", "ModularityRequest", "coordinator", CoordinatorConfig),
    "reusability": AgentConfigSpec("maintainability.reusability.coordinator", "ReusabilityConfig", "ReusabilityRequest", "coordinator", CoordinatorConfig),
    "maintainability_manager": AgentConfigSpec("maintainability.manager", "MaintainabilityConfig", "MaintainabilityRequest", "manager"),
    "project_orientation": AgentConfigSpec("server.project_analysis.project_orientation", "OrientationLimits", None, "repository_agent"),
    "project_architecture": AgentConfigSpec("server.project_analysis.project_architecture", "ArchitectureLimits", None, "repository_agent"),
    "project_semantic_validation": AgentConfigSpec("server.project_analysis.project_semantic_validation", "ValidationLimits", None, "repository_agent"),
    "functional_adequacy": AgentConfigSpec("functional_adequacy", "FunctionalAdequacyConfig", None, "service_agent"),
    "security": AgentConfigSpec("security", "SecurityAuditConfig", None, "security_pipeline"),
}


def list_agent_configs():
    return sorted(AGENT_CONFIGS)


def configuration_type(agent_id):
    spec = AGENT_CONFIGS[agent_id]
    if spec.shared_config is not None:
        return spec.shared_config
    return getattr(import_module(_module_name(spec.package, ".config")), spec.config_name)


def _module_name(package, suffix=""):
    root = package if package.startswith("server.") else "server.agents." + package
    return root + suffix


def validate_developer_agent_config(agent_id, values):
    """Validate the full runtime contract for trusted developer configuration."""
    return configuration_type(agent_id).model_validate(values)


def validate_agent_config(agent_id, values, *, base=None):
    """Apply user-only edits over trusted defaults/config, returning the real runtime type."""
    return apply_settings(configuration_type(agent_id), values, "user", base=base)


def describe_agent_config(agent_id, *, level: ConfigLevel = "user"):
    """User panel by default; developer view requires explicit selection."""
    if level == "developer":
        return describe_developer_agent_config(agent_id)
    if level != "user":
        raise ValueError(f"Unknown configuration level: {level}")
    spec = AGENT_CONFIGS[agent_id]
    config_type = configuration_type(agent_id)
    user_type = settings_type(config_type, "user")
    fields = fields_for_level(config_type, "user")
    groups = {
        "budget_and_duration": sorted(fields & {"max_total_tokens", "timeout_seconds"}),
        "provider_quotas": sorted(fields & {"provider_rate_limits"}),
        "specific": sorted(fields - {"max_total_tokens", "timeout_seconds", "provider_rate_limits"}),
    }
    return {
        "agent_id": agent_id,
        "role": spec.role,
        "level": "user",
        "config_schema": user_type.model_json_schema(),
        "defaults": user_type().model_dump(mode="json"),
        "groups": {name: names for name, names in groups.items() if names},
    }


def describe_developer_agent_config(agent_id):
    """Full resolved configuration and implementation details for developer tooling."""
    spec = AGENT_CONFIGS[agent_id]
    config_type = configuration_type(agent_id)
    config = config_type()
    schema = config_type.model_json_schema()
    prompt_nodes = getattr(config_type, "prompt_nodes", ())
    if "prompts" in schema["properties"]:
        schema["properties"]["prompts"]["propertyNames"] = {"enum": list(prompt_nodes)}
    fields = set(config_type.model_fields)
    hidden = {"max_iterations", "tools"} if issubclass(config_type, CoordinatorConfig) else set()
    common = set(AgentExecutionConfig.model_fields)
    family = set(InvestigationConfig.model_fields) - common
    excerpts = set(SourceExcerptConfig.model_fields) - common - family
    delegation = set(CoordinatorConfig.model_fields) - common - family
    specific = fields - common - family - excerpts - delegation
    provider = {f for f in common if f.startswith("provider_") or f in {"max_provider_retries", "max_schema_retries"}}
    groups = {
        "execution": common - provider - {"tools", "prompts"},
        "provider": provider,
        "tools_and_prompts": {"tools", "prompts"},
        "investigation": family,
        "excerpts": excerpts,
        "delegation": delegation,
        "specific": specific,
    }
    groups = {name: sorted(names & fields - hidden) for name, names in groups.items() if names & fields - hidden}
    if spec.role == "repository_agent":
        from .repository import RepositoryAgentLimits
        common = set(RepositoryAgentLimits.model_fields)
        specific = fields - common
        groups = {"repository_execution": sorted(fields & common), "specific": sorted(specific)}
    module = import_module(_module_name(spec.package))
    prompt_dir = Path(module.__file__).parent / "prompts"
    request_type = getattr(import_module(_module_name(spec.package, ".schemas")), spec.request_name) if spec.request_name else None
    return {
        "agent_id": agent_id,
        "role": spec.role,
        "level": "developer",
        "field_levels": {name: "user" if name in fields_for_level(config_type, "user") else "developer"
            for name in config_type.model_fields},
        "config_class": config_type.__module__ + "." + config_type.__name__,
        "config_schema": schema,
        "defaults": config.model_dump(mode="json"),
        "groups": groups,
        "specific_fields": sorted(specific),
        "hidden_fields": sorted(hidden),
        "prompt_nodes": list(prompt_nodes),
        "prompt_defaults": {node: (prompt_dir / f"{node}.md").read_text(encoding="utf-8") for node in prompt_nodes},
        "model_schema": ModelSettings.model_json_schema(),
        "request_schema": request_type.model_json_schema() if request_type else None,
        "request_defaults": request_type().model_dump(mode="json") if request_type else None,
    }
