"""Developer-only bounds for architectural-boundary planning."""

from typing import ClassVar

from pydantic import Field

from config.agents import InvestigationConfig


class BoundaryConfig(InvestigationConfig):
    prompt_nodes: ClassVar[tuple[str, ...]] = ("plan_investigation", "investigate")
    max_calls_per_investigation: int | None = Field(default=None, ge=1, le=20,
        description="Optional provider-attempt cap per task, including corrections; null disables it.")
    max_tools_per_investigation: int | None = Field(default=None, ge=0, le=40,
        description="Optional new-tool-query cap per task; null disables the cap. Cached results do not consume it.")
    max_tokens_per_investigation: int = Field(default=25_000, ge=1000,
        description="Token admission cap per task, further limited by its share of the remaining global budget.")
    max_seconds_per_investigation: float = Field(default=60, gt=0, allow_inf_nan=False,
        description="Active time per task, further limited by its share of remaining execution time.")
    max_planned_investigations: int = Field(default=12, ge=1, le=15,
        description="Usual planning target (10–12); never a minimum quota, hard maximum 15.")
    max_integration_scan_files: int = Field(default=60, ge=0, le=200,
        description="Maximum retained production files inspected for integration declarations; zero disables scanning.")
    max_integration_scan_characters: int = Field(default=120_000, ge=0, le=1_000_000,
        description="Total retained characters parsed for lightweight integration discovery, separate from LLM context.")
