"""Operating overrides shared by the direct audit API and quality-audit pipeline."""

from pydantic import BaseModel, ConfigDict, Field

from config.agents.audit import AuditAgentDefaults, AuditCallLimits
from config.agents.budgets import TokenBudgetConfig

from ..agents.security.config import SecurityAuditOverrides
from .audit_configuration import FunctionalAuditOverrides


class AuditExecutionOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attribute_options: dict[str, dict] | None = None
    functional_config: FunctionalAuditOverrides | None = None

    agent_defaults: AuditAgentDefaults | None = Field(default=None,
        description="Common developer overrides for context, per-response output tokens, personal tokens, model calls and tool calls. Applied directly to security and functional adequacy; in maintainability output limits apply throughout the hierarchy while call limits apply to investigators and aggregate hierarchy budgets retain their defaults.",
        json_schema_extra={"x-config-level": "developer"})
    security_config: SecurityAuditOverrides | None = Field(default=None,
        description="Security-specific operating overrides, validated using the security catalog. Explicit fields override agent_defaults; omitted fields retain resolved defaults. Requires security in attributes. Credentials belong to config/agent_configs.",
        json_schema_extra={"x-config-level": "developer"})
    audit_budget: TokenBudgetConfig | None = Field(default=None,
        description="Global shared token cap, independent of each attribute's local token allowance. Omission uses the selected root's server-default budget, independently of operating overrides.")
    call_limits: AuditCallLimits | None = Field(default=None,
        description="Developer call envelopes for maintainability manager, coordinator and investigator. Requires maintainability; security uses security_config or agent_defaults.",
        json_schema_extra={"x-config-level": "developer"})
