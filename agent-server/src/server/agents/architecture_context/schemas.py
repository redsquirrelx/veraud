"""Documentary retrieval and architectural knowledge contracts; no audit findings."""

import re
from typing import Annotated, Literal, Self, get_args

from pydantic import ConfigDict, Field, ValidationInfo, field_validator, model_validator

from config.agents.base import RepositoryContract
from server.services.document_indexing import DocumentRecord, IndexReference

RetrievalCategory = Literal[
    "architectural_style",
    "components",
    "responsibilities",
    "relationships",
    "constraints",
    "interfaces_and_contracts",
    "architectural_decisions",
]


class ArchitectureContextInput(RepositoryContract):
    """Read committed documentation, never the mutable working tree."""

    root_path: str = Field(min_length=1)
    commit_hash: str = Field(default="HEAD", min_length=1)


class SearchTask(RepositoryContract):
    category: RetrievalCategory
    operation: Literal["search"]
    query: str = Field(min_length=1, max_length=120)

    @field_validator("query")
    @classmethod
    def lexical_terms(cls, value: str) -> str:
        if not re.findall(r"\w+", value):
            raise ValueError("A lexical search requires words")
        return value


class ReadTask(RepositoryContract):
    category: RetrievalCategory
    operation: Literal["read"]
    path: str = Field(min_length=1)


RetrievalTask = Annotated[SearchTask | ReadTask, Field(discriminator="operation")]


def task_key(task: SearchTask | ReadTask) -> tuple[str, ...]:
    """FTS uses AND terms: order, casing and repeated terms are immaterial."""
    if task.operation == "read":
        return ("read", task.path)
    return ("search", *sorted(set(re.findall(r"\w+", task.query.casefold()))))


class RetrievalPlan(RepositoryContract):
    tasks: list[RetrievalTask] = Field(max_length=4)

    @model_validator(mode="after")
    def grounded_and_unique(self, info: ValidationInfo) -> Self:
        context = info.context or {}
        previous = {task_key(task) for task in context.get("previous_tasks", [])}
        paths = context.get("paths")
        categories = context.get("pending_categories")
        for task in self.tasks:
            key = task_key(task)
            if key in previous:
                raise ValueError("Repeated retrieval operation")
            previous.add(key)
            if (
                paths is not None
                and task.operation == "read"
                and task.path not in paths
            ):
                raise ValueError("Read path must exist in the document catalog")
            if categories is not None and task.category not in categories:
                raise ValueError("Task category must address a pending need")
        return self


class RetrievalRecord(RepositoryContract):
    """An operation's outcome; result content remains in retrieved_sections."""

    task: RetrievalTask
    index_id: str
    status: Literal["ok", "no_results", "error", "limited"]
    executed: bool = True
    section_ids: list[str] = Field(default_factory=list)
    error: str | None = None


class KnowledgeEvidence(RepositoryContract):
    """Line locator whose quote is reconstructed from original section text."""

    model_config = ConfigDict(str_strip_whitespace=False)

    section_id: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    quote: str = ""

    @model_validator(mode="after")
    def contiguous_range(self) -> Self:
        if self.end_line < self.start_line:
            raise ValueError("Evidence line range must be contiguous and ordered")
        return self


class KnowledgeClaim(RepositoryContract):
    """A documentary assertion, never a code assessment or audit finding."""

    category: RetrievalCategory
    subject: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    related_subjects: list[str] = Field(default_factory=list)
    certainty: Literal["explicit", "derived", "unknown"]
    section_ids: list[str] = Field(min_length=1)
    reasoning: str = Field(min_length=1)
    constraint: Literal[
        "allowed", "prohibited", "required", "exception", "unspecified"
    ] = "unspecified"
    evidence: list[KnowledgeEvidence] = Field(min_length=1)


class CategoryAssessment(RepositoryContract):
    category: RetrievalCategory
    sufficient: bool
    rationale: str = Field(min_length=1)


class KnowledgeCoverage(RepositoryContract):
    categories: list[CategoryAssessment] = Field(min_length=7, max_length=7)

    @model_validator(mode="after")
    def each_category_once(self) -> Self:
        if {item.category for item in self.categories} != set(get_args(RetrievalCategory)):
            raise ValueError("Coverage must assess every retrieval category exactly once")
        if len({item.category for item in self.categories}) != len(self.categories):
            raise ValueError("Coverage categories must be unique")
        return self


class KnowledgeIssue(RepositoryContract):
    category: RetrievalCategory
    kind: Literal["unknown", "ambiguity", "discrepancy"]
    question: str = Field(min_length=1)
    section_ids: list[str] = Field(min_length=1)
    document_references: list[str] = Field(default_factory=list)


class SectionKnowledge(RepositoryContract):
    section_id: str = Field(min_length=1)
    claims: list[KnowledgeClaim] = Field(default_factory=list)
    issues: list[KnowledgeIssue] = Field(default_factory=list)


class KnowledgeExtraction(RepositoryContract):
    sections: list[SectionKnowledge]


class FinalizationDiagnostic(RepositoryContract):
    """Technical validation failure, not a documentary uncertainty or audit finding."""

    target: Literal["index", "document", "section", "claim", "issue", "execution"]
    position: int | None = None
    section_ids: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)


class ArchitectureContextResult(RepositoryContract):
    """Canonical final output for consumers; excludes graph state and usage metrics."""

    schema_version: Literal["1"] = "1"
    document_index: IndexReference | None
    knowledge: list[KnowledgeClaim]
    knowledge_issues: list[KnowledgeIssue]
    covered_categories: list[RetrievalCategory]
    pending_categories: list[RetrievalCategory]
    evaluated_categories: list[RetrievalCategory]
    coverage_assessment_status: Literal["completed", "failed", "not_run"]
    consulted_documents: list[DocumentRecord]
    # Resolve evidence section IDs to document provenance without exporting source text.
    section_paths: dict[str, str]
    validation_errors: list[FinalizationDiagnostic]
    execution_status: Literal["complete", "partial", "failed"]
    finalization_reason: str
    execution_error: str | None = None

    @model_validator(mode="after")
    def complete_requires_confirmed_coverage(self) -> Self:
        if self.execution_status == "complete" and (
            set(self.covered_categories) != set(get_args(RetrievalCategory))
            or self.pending_categories
            or self.coverage_assessment_status != "completed"
            or self.validation_errors
            or self.execution_error
        ):
            raise ValueError("Complete execution requires seven confirmed categories without errors")
        return self
