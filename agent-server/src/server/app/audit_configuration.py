"""Audit drawer contracts derived from the runtime-owned configuration fields."""

from copy import deepcopy

from pydantic import ConfigDict, create_model

from config.agents.audit import (
    AuditAgentDefaults,
    AuditCallLimits,
    apply_audit_call_limits,
    apply_audit_defaults,
    validate_audit_agents,
    validate_audit_output_capacity,
)
from config.agents.budgets import ExecutionTimingConfig, TokenBudgetConfig
from config.agents.catalog import (
    configuration_type,
    validate_agent_config,
    validate_developer_agent_config,
)
from config.agents.execution import AgentExecutionConfig
from config.agents.provider import ProviderRetryConfig

from ..agents.functional_adequacy.config import FunctionalAdequacyConfig
from ..agents.security.config import (
    SecurityAuditOverrides,
    resolve_security_audit_config,
)

# Model/context/call budgets already have canonical controls in agent_defaults.
# Only expose additional controls consumed by the functional audit runtime:
# tools and structured-output repair policy do not apply to this agent's graph.
FUNCTIONAL_RUNTIME_CONTROLS = {
    "timeout_seconds", "provider_rate_limits",
    *ExecutionTimingConfig.model_fields, *ProviderRetryConfig.model_fields,
}
FunctionalAuditOverrides = create_model("FunctionalAuditOverrides", __config__=ConfigDict(extra="forbid"),
    **{name: (field.annotation, deepcopy(field)) for name, field in FunctionalAdequacyConfig.model_fields.items()
        if name not in AgentExecutionConfig.model_fields or name in FUNCTIONAL_RUNTIME_CONTROLS})

# The drawer has one canonical output setting in agent_defaults. The execution
# API retains SecurityAuditOverrides for older standalone clients.
SecurityCategoryOverrides = create_model("SecurityCategoryOverrides", __config__=ConfigDict(extra="forbid"),
    **{name: (field.annotation, deepcopy(field)) for name, field in SecurityAuditOverrides.model_fields.items()
        if name != "max_output_tokens"})


def category_type(attribute):
    fields = {"audit_budget": (TokenBudgetConfig | None, None),
        "agent_defaults": (AuditAgentDefaults | None, None)}
    if attribute == "maintainability":
        fields["call_limits"] = (AuditCallLimits | None, None)
    elif attribute == "security":
        fields["security_config"] = (SecurityCategoryOverrides | None, None)
    elif attribute == "functional_adequacy":
        fields["functional_config"] = (FunctionalAuditOverrides | None, None)
    else:
        raise ValueError("Unknown quality attribute.")
    return create_model(attribute + "AuditSettings", __config__=ConfigDict(extra="forbid"), **fields)


def resolve_attribute_limits(attribute, values, *, base=None):
    parsed = category_type(attribute).model_validate(values)
    identifier = "maintainability_manager" if attribute == "maintainability" else attribute
    limits = base if base is not None else configuration_type(identifier)()
    if attribute == "security":
        overrides = SecurityAuditOverrides.model_validate(parsed.security_config.model_dump(exclude_unset=True)) \
            if parsed.security_config is not None else None
        return resolve_security_audit_config(defaults=parsed.agent_defaults, overrides=overrides, base=limits)
    if parsed.agent_defaults is not None:
        limits = apply_audit_defaults(limits, parsed.agent_defaults)
    if attribute == "maintainability":
        if parsed.call_limits is not None:
            limits = apply_audit_call_limits(limits, parsed.call_limits)
        validate_audit_agents(limits)
    elif parsed.functional_config is not None:
        edits = parsed.functional_config.model_dump(exclude_unset=True)
        # The shared user-level merger preserves omitted RPM/TPM values and
        # treats explicit null as disabling only the selected quota.
        user_edits = {name: edits.pop(name) for name in tuple(edits) if name in limits.user_fields}
        limits = validate_agent_config(identifier, user_edits, base=limits)
        limits = validate_developer_agent_config(identifier, {**limits.model_dump(), **edits})
    return limits


def validate_category(attribute, values):
    parsed = category_type(attribute).model_validate(values)
    validate_audit_output_capacity(resolve_attribute_limits(attribute, values))
    # An explicit null quota disables that bound; dropping it would silently
    # restore the saved/default quota when the backend persists these values.
    return parsed.model_dump(mode="json", exclude_unset=True)
