"""Abstraction-specific candidate and participant limits."""

from pydantic import Field

from config.agents import InvestigationConfig


class AbstractionConfig(InvestigationConfig):
    max_candidates: int = Field(default=12, ge=1, le=40, description="Maximum discovered abstraction candidates selected for investigation.")
    max_participants_per_assessment: int = Field(default=12, ge=1, le=24,
        description="Maximum implementations, consumers or other participants per abstraction assessment.")
