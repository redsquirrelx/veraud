"""A single cognitive phase, no direct repository tools or planning loops."""

from typing import ClassVar

from config.agents import CoordinatorConfig, InvestigationConfig


class ModularityConfig(CoordinatorConfig):
    prompt_nodes: ClassVar = ("plan_assessment",)
    defaults: ClassVar = {key: InvestigationConfig.model_fields[key].default for key in CoordinatorConfig.defaults} | {
        "tools": [], "max_schema_retries": 0, "max_rounds": 1}
    bounds: ClassVar = {"max_rounds": {"ge": 1, "le": 1}, "max_invocations": {"ge": 1}}
