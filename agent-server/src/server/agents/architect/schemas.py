from typing import Literal

from pydantic import BaseModel, Field

from ..analyzer.schemas import ProjectDescription


class ArchitectInput(BaseModel):
    """What the architect needs: where to look, plus what the analyzer found.

    The analyzer output is the starting point, not the whole evidence: the
    architect collects its own representations and reads code itself from
    phase 2 on.
    """

    root_path: str = Field(description="Repository root to describe")
    analysis: ProjectDescription = Field(description="Analyzer output to build on")
    max_read_rounds: int = Field(
        default=3,
        ge=0,
        description="How many times the agent may read more files before settling",
    )


class ComponentInfo(BaseModel):
    """One key component and what it is responsible for."""

    path: str = Field(description="Repository path of the component")
    responsibility: str = Field(
        default="",
        description="One line on what this component does, citing what was read",
    )


class ContainerInfo(BaseModel):
    """One deployable-ish unit the model grouped files into (C4 level 2).

    Membership is model judgment, validated against the repository listing:
    invented members are dropped, and an empty container is dropped whole.
    """

    name: str = Field(description="Short name for the container, e.g. web frontend")
    responsibility: str = Field(
        default="",
        description="One line on what this container does",
    )
    files: list[str] = Field(
        default_factory=list,
        description="Repository paths grouped into this container",
    )


class ExternalGroup(BaseModel):
    """Third-party dependencies grouped by architectural role.

    The grouping criterion is the model's (persistence, HTTP, AI, ...): a
    single "third-party" group when no roles emerge. Members are validated
    against the collected third-party list, so invented dependencies do not
    survive.
    """

    name: str = Field(description="Short name for the group, e.g. persistence")
    members: list[str] = Field(
        default_factory=list,
        description="Third-party dependency names in this group",
    )


class QualityNote(BaseModel):
    """An ISO/IEC 25010 maintainability observation backed by evidence."""

    characteristic: str = Field(
        description="Maintainability sub-characteristic: modularity, analysability, modifiability or testability"
    )
    observation: str = Field(default="", description="What was observed, no scores")
    evidence: list[str] = Field(
        default_factory=list,
        description="Repository paths backing the observation",
    )


class Deviation(BaseModel):
    """One concrete way the code falls short of the intended architecture."""

    observation: str = Field(description="What falls short, in one sentence")
    evidence: list[str] = Field(
        default_factory=list,
        description="Repository paths proving it",
    )


class ArchitectureDescription(BaseModel):
    """How the project is put together. A description, not a judgement.

    No scores anywhere: scoring belongs to the evaluator agents that run
    after this one.
    """

    style: str = Field(
        default="unknown",
        description="Architectural style, e.g. layered, hexagonal, mvc, modular monolith",
    )
    style_explanation: str = Field(
        default="",
        description="Which observed fact drove the style, in the model's words",
    )
    intended_style: str = Field(
        default="unknown",
        description="Architecture the repository seems to try to be",
    )
    intended_explanation: str = Field(
        default="",
        description="Which fact points at the intended style, in the model's words",
    )
    deviations: list[Deviation] = Field(default_factory=list)
    components: list[ComponentInfo] = Field(default_factory=list)
    containers: list[ContainerInfo] = Field(
        default_factory=list,
        description="C4 level 2: file groups with inferred responsibilities",
    )
    externals: list[ExternalGroup] = Field(
        default_factory=list,
        description="Third-party dependencies grouped by architectural role",
    )
    diagram_containers: str = Field(
        default="",
        description="Mermaid block for the containers diagram",
    )
    diagram_components: str = Field(
        default="",
        description="Mermaid block for the components diagram",
    )
    data_flow: str = Field(
        default="",
        description="How execution flows from the entry points through the components, in prose",
    )
    third_party: list[str] = Field(
        default_factory=list,
        description="External dependencies the architecture relies on",
    )
    cycles: list[list[str]] = Field(
        default_factory=list,
        description="Circular dependency groups the architecture carries",
    )
    quality_notes: list[QualityNote] = Field(default_factory=list)
    risks: list[str] = Field(
        default_factory=list,
        description="Structural risks: cycles, hubs, unconfirmed parts",
    )
    confidence: Literal["low", "medium", "high"] = Field(
        default="low",
        description="How sure the description is",
    )
    confidence_explanation: str = Field(
        default="",
        description="Which evidence backs the confidence level, derived not written",
    )
