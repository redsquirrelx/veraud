"""Developer-owned read-only tool response limits, shared by all repository agents."""

from typing import ClassVar

from pydantic import Field

from .budgets import SourceLineConfig, SourceReadConfig


class ToolLimits(SourceReadConfig, SourceLineConfig):
    defaults: ClassVar = {"max_source_lines": 120, "max_source_characters": 12_000}
    max_page_size: int = Field(default=50, ge=1, le=500)
    max_response_characters: int = Field(default=16_000, ge=512)
    max_metadata_items: int = Field(default=20, ge=1)
    compact: bool = False
