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
    max_read_rounds: int = Field(
        default=2,
        ge=0,
        description="How many times the agent may read more files before settling",
    )
    max_files_per_round: int = Field(
        default=8,
        ge=1,
        description="Files the model may pick per round",
    )


class ProjectDescription(BaseModel):
    """What the repository appears to be. A description, not a judgement.

    `files_read` and `hypothesis_confirmed` are there so a reader can tell a
    description backed by code from one guessed from a file listing.
    """

    kind: Literal[
        "cli", "library", "web_service", "desktop_app",
        "data_pipeline", "script", "unknown",
    ] = Field(description="Coarse category of the project")

    summary: str = Field(description="Two or three sentences, plain prose")

    primary_language: str = Field(description="Dominant language, e.g. python")

    entrypoints: list[str] = Field(
        default_factory=list,
        description="Paths where execution starts",
    )

    key_components: list[str] = Field(
        default_factory=list,
        description="Project paths that carry most of the code",
    )

    confidence: Literal["low", "medium", "high"] = Field(
        default="low",
        description="How sure the description is",
    )

    files_read: int = Field(
        default=0,
        ge=0,
        description="How many files were actually read. 0 means nothing was seen.",
    )

    read_rounds: int = Field(
        default=0,
        ge=0,
        description="How many read rounds were needed",
    )

    hypothesis_confirmed: bool = Field(
        default=False,
        description="Whether reading the source confirmed the initial hypothesis",
    )