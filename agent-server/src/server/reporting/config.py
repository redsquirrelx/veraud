"""Developer-owned editorial bounds for the human-readable Word projection."""

from pydantic import Field

from config.agents import ConfigContract


class ReportPresentationConfig(ConfigContract):
    max_detailed_findings: int = Field(default=12, ge=1)
    max_evidence_excerpts: int = Field(default=8, ge=1)
    max_table_rows: int = Field(default=20, ge=1)
    max_list_items: int = Field(default=6, ge=1)
    max_text_characters: int = Field(default=1400, ge=200)
    max_excerpt_characters: int = Field(default=1200, ge=100)
    max_structure_depth: int = Field(default=3, ge=1)
