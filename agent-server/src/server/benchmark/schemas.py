from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..agents.judge.schemas import GradeVerdict


class ReferenceClaim(BaseModel):
    id: str
    observation: str
    evidence: list[str] = Field(min_length=1)
    verdict: GradeVerdict
    rationale: str


class ExpectedFact(BaseModel):
    id: str
    description: str
    evidence: list[str] = Field(min_length=1)


class BenchmarkCase(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    repository: str
    commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    kinds: list[str] = Field(default_factory=list)
    primary_language: str
    entrypoints: list[str]
    key_components: list[str]
    entrypoints_exhaustive: bool = False
    components_exhaustive: bool = False
    notes: str = ""
    expected_facts: list[ExpectedFact]
    judge_claims: list[ReferenceClaim]

    @model_validator(mode="after")
    def unique_ids(self):
        for items in (self.expected_facts, self.judge_claims):
            ids = [item.id for item in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f"Duplicate reference ids in {self.id}")
        return self


class BenchmarkSuite(BaseModel):
    version: int = 1
    description: str
    cases: list[BenchmarkCase] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_cases(self):
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate case ids")
        return self


class ReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    section: str
    claim: str
    evidence: list[str]
    verdict: GradeVerdict | None = None
    comment: str = ""


class FactReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    description: str
    evidence: list[str]
    found: bool | None = None
    comment: str = ""


class HumanReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    artifact_sha256: str
    reviewer: str = ""
    claims: list[ReviewItem]
    expected_facts: list[FactReview]


StageStatus = Literal["completed", "degraded", "failed", "timed_out", "skipped"]
