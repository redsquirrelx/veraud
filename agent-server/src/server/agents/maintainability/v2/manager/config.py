"""Only the planning prompt is enabled; repository tools are prohibited."""

from typing import ClassVar

from config.agents import CoordinatorConfig, InvestigationConfig

from ..modularity.coordinator.config import ModularityConfig


class MaintainabilityConfig(CoordinatorConfig[ModularityConfig]):
    prompt_nodes: ClassVar = ("plan_audit",)
    # Adopt existing delegation controls without raising the planner's old limits.
    defaults: ClassVar = {key: InvestigationConfig.model_fields[key].default for key in CoordinatorConfig.defaults} | {
        "tools": [], "max_schema_retries": 0, "invocation_limits": ModularityConfig()}
