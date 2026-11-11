"""Deterministic LangGraph node: discover metadata, never document content."""

import sqlite3

from server.services.document_indexing import DocumentIndexingService, DocumentRecord

from .state import ArchitectureContextState


def discover_documents(
    state: ArchitectureContextState, *, indexing_service: DocumentIndexingService
) -> ArchitectureContextState:
    """Bind the service with functools.partial when adding this node to a graph.

    The caller supplies the audit's trusted IndexReference in document_index.
    Discovery never builds an index, reads source text, or invokes a model.
    A failed page invalidates the whole catalog rather than exposing partial data.
    """
    expected = state["document_index"]
    try:
        actual = indexing_service.get_index(expected.index_id)
        if (
            actual.index_id != expected.index_id
            or actual.repository_id != expected.repository_id
            or actual.commit != expected.commit
        ):
            raise ValueError(
                "Document index does not match the audited repository and commit"
            )
        documents: list[DocumentRecord] = []
        offset = 0
        while True:
            page = indexing_service.list_documents(
                expected.index_id, limit=100, offset=offset
            )
            for document in page:
                if (
                    document.index_id != expected.index_id
                    or document.repository_id != expected.repository_id
                    or document.commit != expected.commit
                ):
                    raise ValueError(
                        "Document metadata does not match the audited repository and commit"
                    )
            documents.extend(page)
            if len(page) < 100:
                break
            offset += len(page)
        documents.sort(key=lambda document: document.path)
    except (ValueError, OSError, sqlite3.Error) as error:
        return {
            "documents": [],
            "document_discovery_status": "error",
            "document_discovery_error": str(error),
            "retrieval_context": "Document catalog unavailable: index access failed. Do not treat this as an empty repository.",
        }
    return {
        "documents": documents,
        "document_discovery_status": "ready",
        "document_discovery_error": None,
        "retrieval_context": (
            f"{len(documents)} documents available in state['documents'] "
            "(paths, line counts and provenance). Consult the catalog from state; no document content has been read."
        ),
    }
