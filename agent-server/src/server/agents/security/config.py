"""Security pipeline developer settings; common model controls use ModelSettings."""

from pathlib import Path

from pydantic import Field

from config.agents import ConfigContract, ModelSettings


class SecurityConfig(ConfigContract):
    knowledge_database_path: str = Field(default="security_patterns.db", min_length=1)
    remediation_model: ModelSettings = Field(default_factory=lambda: ModelSettings(
        provider="openai", name="gpt-4o-mini", temperature=0.2, max_tokens=40000))
    dast_dispatch_delay_seconds: float = Field(default=0.1, ge=0, allow_inf_nan=False)
    remediation_system_prompt: str = Field(default_factory=lambda:
        (Path(__file__).parent / "prompts" / "remediation.md").read_text(encoding="utf-8"), min_length=1)
