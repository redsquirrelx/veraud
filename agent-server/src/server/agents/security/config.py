"""Security pipeline developer settings; common model controls use ModelSettings."""

from copy import deepcopy
from pathlib import Path
from typing import ClassVar

from pydantic import ConfigDict, Field, create_model

from config.agents import ConfigContract, ModelSettings
from config.agents.budgets import (
    ExecutionTimingConfig,
    SourceLineConfig,
    SourceReadConfig,
)
from config.agents.catalog import validate_developer_agent_config
from config.agents.execution import AgentExecutionConfig
from config.agents.provider import ProviderRetryConfig
from config.agents.tools import ToolLimits


class SecurityAuditConfig(AgentExecutionConfig, ExecutionTimingConfig, SourceLineConfig, SourceReadConfig):
    defaults: ClassVar = {name: field.default for name, field in ToolLimits.model_fields.items()
        if name in {"max_source_lines", "max_source_characters"}}
    max_scan_files: int = Field(default=24, ge=1, le=500)


# Derive the transport patch from effective owning fields, including their bounds.
# Only values actually supplied are merged; user panels still use the catalog's
# user-level schema rather than this explicitly developer-level audit endpoint.
SECURITY_AUDIT_CONTROLS = {
    "max_context_characters", "max_total_tokens", "max_model_calls", "max_tool_calls", "max_output_tokens",
    "timeout_seconds", "provider_rate_limits", "max_scan_files", "max_source_lines", "max_source_characters",
    *ExecutionTimingConfig.model_fields, *ProviderRetryConfig.model_fields,
}
SecurityAuditOverrides = create_model("SecurityAuditOverrides", __config__=ConfigDict(extra="forbid"),
    **{name: (field.annotation, deepcopy(field)) for name, field in SecurityAuditConfig.model_fields.items()
       if name in SECURITY_AUDIT_CONTROLS})


def resolve_security_audit_config(*, defaults=None, overrides=None, base=None):
    values = (base if base is not None else SecurityAuditConfig()).model_dump()
    if defaults is not None:
        values.update(defaults.model_dump(exclude_unset=True))
    if overrides is not None:
        edits = overrides.model_dump(exclude_unset=True)
        if "provider_rate_limits" in edits:
            edits["provider_rate_limits"] = {**values["provider_rate_limits"], **edits["provider_rate_limits"]}
        values.update(edits)
    return validate_developer_agent_config("security", values)


class SecurityConfig(ConfigContract):
    knowledge_database_path: str = Field(default="security_patterns.db", min_length=1)
    remediation_model: ModelSettings = Field(default_factory=lambda: ModelSettings(
        provider="openai", name="gpt-4o-mini", temperature=0.2, max_tokens=40000))
    dast_dispatch_delay_seconds: float = Field(default=0.1, ge=0, allow_inf_nan=False)
    remediation_system_prompt: str = Field(default_factory=lambda:
        (Path(__file__).parent / "prompts" / "remediation.md").read_text(encoding="utf-8"), min_length=1)
