from typing import Any

from pydantic import BaseModel, Field


class CollectionInput(BaseModel):
    """A repository to describe, and how much of it to read."""

    root_path: str = Field(
        description="Directory to map, e.g. appdata/workspace/{id}-{owner}-{repo}",
    )
    max_files: int = Field(
        default=500,
        ge=1,
        description="Cap per representation, to bound cost on large repos",
    )
    max_depth: int = Field(
        default=8,
        ge=1,
        description="Maximum directory depth to walk",
    )
    include_external: bool = Field(
        default=True,
        description="Collect third-party imports; useful for telling projects apart",
    )


class Collection(BaseModel):
    """Facts gathered about a repository. No interpretation.

    Every field here is something observable on disk. Nothing in this model
    says what kind of project it is: that judgement belongs to the agent that
    reads it.
    """

    root: str = Field(description="Absolute root that was collected")
    repo_map: dict[str, Any] = Field(description="RepoMapOutput")
    dependency_graph: dict[str, Any] = Field(description="DependencyGraphOutput")
    stats: dict[str, Any] = Field(
        default_factory=dict,
        description="Combined totals across the collected representations",
    )