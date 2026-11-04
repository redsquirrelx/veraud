"""Reuse-opportunity discovery bounds; excerpt controls are shared configuration."""

from pydantic import Field

from config.agents import SourceExcerptConfig


class ReuseOpportunityConfig(SourceExcerptConfig):
    max_planned_groups: int = Field(default=2, ge=1, le=20, description="Maximum distinct groups committed by the initial plan; hypotheses are admitted whole.")
    max_discovery_symbols: int = Field(default=160, ge=2, le=500, description="Maximum indexed functions/methods used in bounded pair discovery.")
    max_groups: int = Field(default=8, ge=1, le=20, description="Maximum candidate implementation pairs shortlisted; the plan commits a bounded subset for assessment.")
    max_feature_characters: int = Field(default=6000, ge=256, le=16000,
        description="Maximum source characters used to derive discovery features per symbol.")
