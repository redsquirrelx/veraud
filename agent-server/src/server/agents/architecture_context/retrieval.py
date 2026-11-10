"""Execute a retrieval plan against one retained index, without interpretation."""

import sqlite3
from collections.abc import Callable
from time import monotonic

from config.agents.repository_execution import ExecutionBudget
from config.agents.tools import ToolLimits
from server.agent_services.budgeting.policy import budgets_enabled
from server.agent_services.budgeting.timing import ActiveDeadline
from server.runtimes.repository.schemas import BudgetUsage
from server.services.document_indexing import (
    DocumentIndexingService,
    DocumentRecord,
    DocumentSection,
)

from .schemas import RetrievalRecord, task_key
from .state import ArchitectureContextState


def retrieve_documents(
    state: ArchitectureContextState,
    *,
    indexing_service: DocumentIndexingService,
    limits: ToolLimits | None = None,
    budget: ExecutionBudget | None = None,
    timing: ActiveDeadline | None = None,
    trace: Callable[..., None] | None = None,
) -> ArchitectureContextState:
    """Retain whole original sections only; never shorten source or invent ranges.

    Usage persists across iterations. Each search/read page consumes a tool call;
    admitted section payloads (including duplicates) consume serialized characters.
    Oversized sections are omitted with a limited outcome, not silently truncated.
    """
    limits, budget = limits or ToolLimits(), budget or ExecutionBudget()
    usage = state.get("retrieval_usage", BudgetUsage())
    timing = timing or ActiveDeadline(
        max(0, budget.max_elapsed_seconds - usage.elapsed_seconds)
    )
    started = monotonic()
    calls, characters = usage.tool_calls, usage.retrieved_characters
    expected = state["document_index"]
    catalog = {document.path: document for document in state["documents"]}
    sections = list(state.get("retrieved_sections", []))
    history = list(state.get("retrieval_history", []))
    if any(
        isinstance(item, RetrievalRecord) and item.index_id != expected.index_id
        for item in history
    ):
        raise ValueError("Retrieval history does not match the audited index")

    def verify(section: DocumentRecord) -> None:
        document = catalog.get(section.path)
        if document is None or any(
            getattr(section, field) != getattr(document, field)
            for field in (
                "index_id",
                "repository_id",
                "commit",
                "content_hash",
                "line_count",
            )
        ):
            raise ValueError(
                "Retrieved section does not match the audited index and catalog"
            )

    # Stale inputs must not carry content from another snapshot into the output.
    for document in catalog.values():
        if (document.index_id, document.repository_id, document.commit) != (
            expected.index_id,
            expected.repository_id,
            expected.commit,
        ):
            raise ValueError("Document catalog does not match the audited index")
    for section in sections:
        verify(section)
    sections = list({section.section_id: section for section in sections}.values())
    seen = {section.section_id for section in sections}
    executed = {
        task_key(item.task if isinstance(item, RetrievalRecord) else item)
        for item in history
        if not isinstance(item, RetrievalRecord) or item.executed
    }
    tasks = [
        task for task in state["retrieval_plan"].tasks if task_key(task) not in executed
    ]
    index_error = None
    if tasks:
        try:
            actual = indexing_service.get_index(expected.index_id)
            if (actual.index_id, actual.repository_id, actual.commit) != (
                expected.index_id,
                expected.repository_id,
                expected.commit,
            ):
                raise ValueError(
                    "Document index does not match the audited repository and commit"
                )
        except (ValueError, OSError, sqlite3.Error) as error:
            index_error = str(error)
            if trace:
                trace("retrieval_index_error", exception=error)

    page_size = min(limits.max_page_size, 100)
    for task in tasks:
        if trace:
            trace(
                "retrieval_task_started",
                node="retrieve_documents",
                round=state.get("retrieval_round", 0),
                task=task.model_dump(mode="json"),
            )
        if index_error is not None:
            if trace:
                trace(
                    "retrieval_task_finished",
                    status="error",
                    executed=False,
                    reason="index_unavailable",
                )
            history.append(
                RetrievalRecord(
                    task=task,
                    index_id=expected.index_id,
                    status="error",
                    executed=False,
                    error=index_error,
                )
            )
            continue
        section_ids = []
        status, problem = "ok", None
        offset = response_characters = 0
        attempted = False
        duplicates = omitted = 0
        retained_before = len(sections)
        try:
            if task.operation == "read" and task.path not in catalog:
                raise ValueError("Read path must exist in the document catalog")
            while True:
                if budgets_enabled() and (
                    calls >= budget.max_tool_calls
                    or timing.remaining <= 0
                    or characters >= budget.max_retrieved_characters
                ):
                    status, problem = "limited", "retrieval_execution_budget_exhausted"
                    break
                calls += 1
                attempted = True
                if trace:
                    trace(
                        "retrieval_page_started",
                        offset=offset,
                        limit=page_size,
                        tool_call=calls,
                    )
                if task.operation == "read":
                    page = indexing_service.read_document_sections(
                        expected.index_id, task.path, limit=page_size, offset=offset
                    )
                else:
                    page = indexing_service.search_fragments(
                        expected.index_id, task.query, limit=page_size
                    )
                # Validate the whole page before retaining any of its content.
                if trace:
                    trace("retrieval_page_received", offset=offset, sections=len(page))
                for item in page:
                    verify(item)
                    if task.operation == "read" and item.path != task.path:
                        raise ValueError(
                            "Read results do not match the requested document path"
                        )
                stop = False
                for position, item in enumerate(page):
                    section = DocumentSection(**item.model_dump(exclude={"score"}))
                    if budgets_enabled() and (
                        section.end_line - section.start_line + 1
                        > limits.max_source_lines
                        or len(section.content) > limits.max_source_characters
                    ):
                        status, problem = "limited", "source_limit_exceeded"
                        omitted += 1
                        continue
                    size = len(section.model_dump_json())
                    if budgets_enabled() and (
                        response_characters + size > limits.max_response_characters
                        or characters + size > budget.max_retrieved_characters
                    ):
                        status, problem = (
                            "limited",
                            "retrieval_character_limit_exceeded",
                        )
                        stop = True
                        omitted += len(page) - position
                        break
                    response_characters += size
                    characters += size
                    if section.section_id not in section_ids:
                        section_ids.append(section.section_id)
                    if section.section_id not in seen:
                        sections.append(section)
                        seen.add(section.section_id)
                    else:
                        duplicates += 1
                if stop:
                    break
                if task.operation == "search":
                    if not page:
                        status = "no_results"
                    elif len(page) == page_size:
                        status, problem = "limited", "search_result_limit_reached"
                    break
                if len(page) < page_size:
                    break
                offset += len(page)
        except (ValueError, OSError, sqlite3.Error) as error:
            status, problem = "error", str(error)
            if trace:
                trace("retrieval_error", exception=error)
        if trace:
            trace(
                "retrieval_task_finished",
                status=status,
                executed=attempted,
                section_ids=section_ids,
                newly_retained=len(sections) - retained_before,
                duplicates=duplicates,
                omitted=omitted,
                response_characters=response_characters,
                reason=problem if status == "limited" else None,
            )
        history.append(
            RetrievalRecord(
                task=task,
                index_id=expected.index_id,
                status=status,
                executed=attempted,
                section_ids=section_ids,
                error=problem,
            )
        )

    return {
        "retrieved_sections": sections,
        "retrieval_history": history,
        "retrieval_usage": usage.model_copy(
            update={
                "tool_calls": calls,
                "retrieved_characters": characters,
                "elapsed_seconds": usage.elapsed_seconds + monotonic() - started,
            }
        ),
    }
