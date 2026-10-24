"""Developer-selected common overrides for a hierarchical audit."""

from copy import deepcopy

from pydantic import ConfigDict, create_model

from .base import ConfigContract
from .budgets import CallBudgetConfig
from .catalog import validate_developer_agent_config
from .execution import AgentExecutionConfig, CoordinatorConfig, InvestigationConfig

# Reuse the owning fields' defaults, constraints and descriptions. Only explicitly
# supplied values are applied; omitted fields retain each agent's own defaults.
AuditAgentDefaults = create_model(
    "AuditAgentDefaults",
    __config__=ConfigDict(extra="forbid"),
    **{name: (AgentExecutionConfig.model_fields[name].annotation,
              deepcopy(AgentExecutionConfig.model_fields[name]))
       for name in ("max_context_characters", "max_output_tokens", "max_total_tokens", "max_model_calls", "max_tool_calls")},
)

AuditCallLimit = create_model("AuditCallLimit", __config__=ConfigDict(extra="forbid"),
    **{name: (CallBudgetConfig.model_fields[name].annotation, deepcopy(CallBudgetConfig.model_fields[name]))
       for name in ("max_model_calls", "max_tool_calls")})


class AuditCallLimits(ConfigContract):
    manager: AuditCallLimit | None = None
    coordinator: AuditCallLimit | None = None
    investigator: AuditCallLimit | None = None


def audit_output_envelope(limits, overrides=None):
    """Repository transport headroom, not an additional agent output setting."""
    values = list((overrides or {}).values())
    while limits is not None:
        values.append(limits.max_output_tokens)
        limits = getattr(limits, "invocation_limits", None)
    return max(values)


def validate_audit_output_capacity(limits):
    """Reject impossible output reservations before accepting an audit."""
    while limits is not None:
        quota = limits.provider_rate_limits.tokens_per_minute
        if quota is not None and limits.max_output_tokens >= quota:
            raise ValueError(f"max_output_tokens ({limits.max_output_tokens}) must be lower than "
                f"provider_rate_limits.tokens_per_minute ({quota}); each request also reserves input tokens.")
        limits = getattr(limits, "invocation_limits", None)


def apply_audit_defaults[T: InvestigationConfig](limits: T, defaults: AuditAgentDefaults) -> T:
    """Revalidate common developer edits at every level of the child envelope."""
    values = limits.model_dump()
    edits = defaults.model_dump(exclude_unset=True)
    if isinstance(limits, CoordinatorConfig):
        # A common leaf limit is not an aggregate parent budget. Flattening it
        # across levels reserves the whole coordinator budget for its first child.
        edits.pop("max_model_calls", None)
        edits.pop("max_tool_calls", None)
    values.update(edits)
    if isinstance(limits, CoordinatorConfig):
        values["invocation_limits"] = apply_audit_defaults(limits.invocation_limits, defaults).model_dump()
    return type(limits).model_validate(values)


def apply_audit_call_limits(limits: CoordinatorConfig, overrides: AuditCallLimits):
    values = limits.model_dump()
    if overrides.manager is not None:
        values.update(overrides.manager.model_dump(exclude_unset=True))
    coordinator = limits.invocation_limits.model_dump()
    if overrides.coordinator is not None:
        coordinator.update(overrides.coordinator.model_dump(exclude_unset=True))
    investigator = limits.invocation_limits.invocation_limits.model_dump()
    if overrides.investigator is not None:
        investigator.update(overrides.investigator.model_dump(exclude_unset=True))
    coordinator["invocation_limits"] = investigator
    values["invocation_limits"] = coordinator
    return type(limits).model_validate(values)


def validate_audit_agents(limits: CoordinatorConfig) -> None:
    """Check specialized child contracts before scheduling the audit."""
    for agent_id in ("modularity", "reusability"):
        validate_developer_agent_config(agent_id, limits.invocation_limits.model_dump())
    for agent_id in ("architecture_boundary", "responsibility", "dependency_impact",
                     "abstraction", "reuse_opportunity", "component_adaptability"):
        validate_developer_agent_config(agent_id, limits.invocation_limits.invocation_limits.model_dump())
