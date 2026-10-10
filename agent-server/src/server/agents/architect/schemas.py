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


class ComponentInfo(BaseModel):
    """One key component and what it is responsible for."""

    path: str = Field(description="Repository path of the component")
    responsibility: str = Field(
        default="",
        description="One line on what this component does, citing what was read",
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


class ArchitectureDescription(BaseModel):
    """How the project is put together. A description, not a judgement.

    No scores anywhere: scoring belongs to the evaluator agents that run
    after this one.
    """

    style: str = Field(
        default="unknown",
        description="Architectural style, e.g. layered, hexagonal, mvc, modular monolith",
    )
    components: list[ComponentInfo] = Field(default_factory=list)
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
