from typing import Literal

from pydantic import BaseModel, Field


class ProjectInput(BaseModel):
    """A repository to describe.

    Only the path. The agent collects the representations it needs itself, so
    the caller does not have to know which ones exist.
    """

    root_path: str = Field(description="Repository root to describe")
    max_files: int = Field(
        default=500,
        ge=1,
        description="Cap per representation when collecting",
    )
    max_depth: int = Field(
        default=8,
        ge=1,
        description="Maximum directory depth to walk",
    )


class ProjectDescription(BaseModel):
    """What the repository appears to be. A description, not a judgement."""

    kind: Literal[
        "cli", "library", "web_service", "desktop_app",
        "data_pipeline", "script", "unknown",
    ] = Field(description="Coarse category of the project")
    summary: str = Field(description="Two or three sentences, plain prose")
    primary_language: str = Field(description="Dominant language, e.g. python")
    entrypoints: list[str] = Field(
        default_factory=list,
        description="Files that look like entry points",
    )
    key_components: list[str] = Field(
        default_factory=list,
        description="Modules that carry most of the code",
    )
    confidence: Literal["low", "medium", "high"] = Field(
        default="low",
        description="How sure the description is",
    )