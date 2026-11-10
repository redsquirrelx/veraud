"""Local state for incremental, evidence-grounded architectural context."""

from typing import Literal, TypedDict

from server.runtimes.repository.schemas import BudgetUsage
from server.services.document_indexing import (
    DocumentRecord,
    DocumentSection,
    IndexReference,
)

from .schemas import (
    ArchitectureContextResult,
    FinalizationDiagnostic,
    KnowledgeClaim,
    KnowledgeIssue,
    RetrievalCategory,
    RetrievalPlan,
    RetrievalRecord,
    RetrievalTask,
)


class ArchitectureContextState(TypedDict, total=False):
    # Trusted host input: the existing index bound to the audited repository/commit.
    document_index: IndexReference
    documents: list[DocumentRecord]
    document_discovery_status: Literal["ready", "error"]
    document_discovery_error: str | None
    # Bounded planner-facing summary; the full catalog stays in `documents`.
    retrieval_context: str
    retrieval_plan: RetrievalPlan
    retrieval_history: list[RetrievalTask | RetrievalRecord]
    retrieved_sections: list[DocumentSection]
    retrieval_usage: BudgetUsage
    pending_categories: list[RetrievalCategory]
    knowledge: list[KnowledgeClaim]
    knowledge_issues: list[KnowledgeIssue]
    covered_categories: list[RetrievalCategory]
    processed_section_ids: list[str]
    extraction_section_status: dict[str, Literal["completed", "partial", "failed"]]
    coverage_assessment_status: Literal["completed", "failed", "not_run"]
    evaluated_categories: list[RetrievalCategory]
    retrieval_suggestions: RetrievalPlan
    retrieval_round: int
    context_stop_reason: str | None
    consulted_documents: list[DocumentRecord]
    validation_errors: list[FinalizationDiagnostic]
    execution_status: Literal["complete", "partial", "failed"]
    finalization_reason: str
    execution_error: str
    result: ArchitectureContextResult
