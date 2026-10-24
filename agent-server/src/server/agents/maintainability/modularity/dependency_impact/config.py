"""Dependency-specific exploration bounds on top of shared investigator controls."""

from pydantic import Field

from config.agents import InvestigationConfig


class DependencyImpactConfig(InvestigationConfig):
    max_dependency_depth: int = Field(default=3, ge=1, le=8, description="Maximum dependency hops in an assessed propagation path.")
    max_relationships_per_assessment: int = Field(default=12, ge=1, le=32,
        description="Maximum dependency links examined in each impact assessment.")
