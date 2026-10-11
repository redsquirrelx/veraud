from typing import Literal

from pydantic import BaseModel, Field

from ..architect.schemas import ArchitectureDescription

GradeVerdict = Literal["supported", "contradicted", "unverifiable"]


class JudgeInput(BaseModel):
    """What to grade: where the code is, plus a past architecture description.

    The description comes from an already finished run. The judge never sees
    that run's confidence: it grades blind, and the correlation with
    confidence happens afterwards, outside this agent.
    """

    root_path: str = Field(description="Repository root the description was written from")
    description: ArchitectureDescription = Field(description="Architect output to grade")


class ItemGrade(BaseModel):
    """One claim, whether the cited source backs it, and what decided it."""

    kind: Literal["component", "note"] = Field(description="What was graded")
    subject: str = Field(description="Component path or note characteristic")
    verdict: GradeVerdict = Field(description="What the source says about the claim")
    reason: str = Field(default="", description="One sentence on why")
    evidence: list[str] = Field(
        default_factory=list,
        description="Excerpt headers backing the verdict, as path[:lines]",
    )


class JudgeReport(BaseModel):
    """The whole grading, with counts for calibration.

    The headline metric is the contradiction rate: with the same model doing
    the describing and the grading, a `supported` may be self-agreement, but
    a `contradicted` is strong evidence something is wrong.
    """

    grades: list[ItemGrade] = Field(default_factory=list)
    supported: int = Field(default=0)
    contradicted: int = Field(default=0)
    unverifiable: int = Field(default=0)
    contradiction_rate: float = Field(default=0.0, ge=0.0, le=1.0)
