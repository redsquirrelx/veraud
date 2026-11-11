"""Typed contracts for directory-scoped, verified-commit Markdown retrieval."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class IndexReference(Contract):
    index_id: str
    repository_id: str
    commit: str


class IndexResult(IndexReference):
    documents: int
    processed: int
    reused: int


class DocumentRecord(IndexReference):
    path: str
    content_hash: str
    line_count: int = Field(ge=0)


class Heading(Contract):
    level: int = Field(ge=1, le=6)
    title: str


class DocumentSection(DocumentRecord):
    section_id: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    headings: tuple[Heading, ...]
    content: str

    @model_validator(mode="after")
    def valid_range(self) -> Self:
        if not self.start_line <= self.end_line <= self.line_count:
            raise ValueError("Section range must be within the original document")
        return self


class SearchHit(DocumentSection):
    score: float
