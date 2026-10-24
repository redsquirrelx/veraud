"""Adaptability-specific discovery/assessment bounds, independent of target request data."""

from pydantic import Field

from config.agents import SourceExcerptConfig


class ComponentAdaptabilityConfig(SourceExcerptConfig):
    max_components: int = Field(default=6, ge=1, le=20, description="Maximum selected indexed components.")
    max_scan_files: int = Field(default=160, ge=1, le=1000, description="Maximum files scanned for static adaptation hints.")
    max_scan_characters_per_file: int = Field(default=24000, ge=256, le=100000, description="Maximum scanned source characters per file.")
    max_signals_per_component: int = Field(default=12, ge=1, le=40, description="Maximum discovery signals retained per component.")
    max_constraints: int = Field(default=16, ge=1, le=40, description="Maximum root adaptation constraints assessed.")
