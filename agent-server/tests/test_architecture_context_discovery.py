"""Metadata-only discovery scoped to an existing audited document index."""

import sqlite3
import subprocess
from contextlib import contextmanager
from functools import partial

import pytest
from langgraph.graph import END, START, StateGraph

from server.agents.architecture_context import (
    ArchitectureContextState,
    discover_documents,
)
from server.services.document_indexing import DocumentIndexingService, DocumentRecord


def git(root, *args):
    return (
        subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)
        .decode()
        .strip()
    )


def commit(root):
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "fixture",
    )


@pytest.fixture
def indexed_repository(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init")
    (root / "z.md").write_text("# Last\nPrivate source content", encoding="utf-8")
    (root / "a.md").write_text("# First\nMore source content", encoding="utf-8")
    commit(root)
    service = DocumentIndexingService(tmp_path / "index.sqlite")
    index = service.index_repository(root)
    return root, service, index


def test_langgraph_discovery_reads_only_metadata_and_returns_sorted_catalog(
    indexed_repository, monkeypatch
):
    _, service, index = indexed_repository

    def unexpected(*args, **kwargs):
        pytest.fail("Discovery must not index, search, or read source sections")

    for name in ("index_repository", "search_fragments", "read_section"):
        monkeypatch.setattr(service, name, unexpected)
    original_connect = service.store.connect

    def authorize(action, table, column, *args):
        if action == sqlite3.SQLITE_READ and (
            (table == "blobs" and column == "content")
            or table in {"sections", "section_fts"}
        ):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    @contextmanager
    def metadata_only_connection():
        with original_connect() as connection:
            connection.set_authorizer(authorize)
            yield connection

    monkeypatch.setattr(service.store, "connect", metadata_only_connection)
    original_list = service.list_documents
    # Explicit sorting must not depend on a service page's order.
    monkeypatch.setattr(
        service,
        "list_documents",
        lambda *args, **kwargs: list(reversed(original_list(*args, **kwargs))),
    )
    graph = StateGraph(ArchitectureContextState)
    graph.add_node(
        "discover_documents", partial(discover_documents, indexing_service=service)
    )
    graph.add_edge(START, "discover_documents")
    graph.add_edge("discover_documents", END)
    result = graph.compile().invoke({"document_index": index})
    assert result["document_discovery_status"] == "ready"
    assert result["document_discovery_error"] is None
    assert [document.path for document in result["documents"]] == ["a.md", "z.md"]
    assert all(isinstance(document, DocumentRecord) for document in result["documents"])
    assert all(
        document.line_count == 2 and document.content_hash
        for document in result["documents"]
    )
    assert "state['documents']" in result["retrieval_context"]
    assert "a.md" not in result["retrieval_context"]
    assert "Private source content" not in result["retrieval_context"]


def test_discovery_fetches_all_pages_without_expanding_planner_context(
    indexed_repository,
):
    root, service, _ = indexed_repository
    for number in range(103):
        (root / f"document-{number:03}.md").write_text("text", encoding="utf-8")
    commit(root)
    index = service.index_repository(root)
    state = {"document_index": index}
    first = discover_documents(state, indexing_service=service)
    assert len(first["documents"]) == 105
    assert [doc.path for doc in first["documents"]] == sorted(
        doc.path for doc in first["documents"]
    )
    assert len(first["retrieval_context"]) < 250
    assert discover_documents(state, indexing_service=service) == first


def test_discovery_isolates_repositories_and_commits(indexed_repository, tmp_path):
    root, service, first = indexed_repository
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", "--local", str(root), str(other)],
        check=True,
        capture_output=True,
    )
    clone = service.index_repository(other)
    (root / "a.md").unlink()
    (root / "new.md").write_text("new source", encoding="utf-8")
    commit(root)
    second = service.index_repository(root)
    for index, paths in (
        (first, ["a.md", "z.md"]),
        (clone, ["a.md", "z.md"]),
        (second, ["new.md", "z.md"]),
    ):
        result = discover_documents({"document_index": index}, indexing_service=service)
        assert result["document_discovery_status"] == "ready"
        assert [doc.path for doc in result["documents"]] == paths
        assert all(
            doc.repository_id == index.repository_id and doc.commit == index.commit
            for doc in result["documents"]
        )
    for changes in ({"repository_id": clone.repository_id}, {"commit": second.commit}):
        mismatched = first.model_copy(update=changes)
        result = discover_documents(
            {"document_index": mismatched}, indexing_service=service
        )
        assert result["document_discovery_status"] == "error"
        assert result["documents"] == []


def test_empty_index_is_valid_but_still_checks_identity(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    git(root, "init")
    commit(root)
    service = DocumentIndexingService(tmp_path / "index.sqlite")
    index = service.index_repository(root)
    result = discover_documents({"document_index": index}, indexing_service=service)
    assert result["documents"] == []
    assert result["document_discovery_status"] == "ready"
    assert result["document_discovery_error"] is None
    assert result["retrieval_context"].startswith("0 documents")
    wrong = index.model_copy(update={"repository_id": "wrong-repository"})
    assert (
        discover_documents({"document_index": wrong}, indexing_service=service)[
            "document_discovery_status"
        ]
        == "error"
    )


def test_unknown_index_is_not_an_empty_success(indexed_repository):
    _, service, index = indexed_repository
    unknown = index.model_copy(update={"index_id": "missing"})
    result = discover_documents({"document_index": unknown}, indexing_service=service)
    assert result["document_discovery_status"] == "error"
    assert result["document_discovery_error"] == "Unknown document index"
    assert "unavailable" in result["retrieval_context"]


@pytest.mark.parametrize(
    "error", [sqlite3.OperationalError("index unavailable"), OSError("access denied")]
)
def test_failed_page_clears_stale_and_partial_catalog(
    indexed_repository, monkeypatch, error
):
    _, service, index = indexed_repository
    old = service.list_documents(index.index_id)

    def fail_after_first_page(index_id, *, limit, offset):
        if offset:
            raise error
        return [old[0]] * limit

    monkeypatch.setattr(service, "list_documents", fail_after_first_page)
    result = discover_documents(
        {"document_index": index, "documents": old}, indexing_service=service
    )
    assert result["documents"] == []
    assert result["document_discovery_status"] == "error"
    assert result["document_discovery_error"] == str(error)


def test_inconsistent_page_identity_is_rejected(indexed_repository, monkeypatch):
    _, service, index = indexed_repository
    document = service.list_documents(index.index_id)[0].model_copy(
        update={"commit": "wrong-commit"}
    )
    monkeypatch.setattr(service, "list_documents", lambda *args, **kwargs: [document])
    result = discover_documents({"document_index": index}, indexing_service=service)
    assert result["document_discovery_status"] == "error"
    assert result["documents"] == []
