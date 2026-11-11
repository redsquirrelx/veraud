"""Deterministic, bounded retrieval from a retained documentary snapshot."""

import subprocess
from copy import deepcopy
from functools import partial

import pytest
from langgraph.graph import END, START, StateGraph

from config.agents.repository_execution import ExecutionBudget
from config.agents.tools import ToolLimits
from server.agents.architecture_context import (
    ArchitectureContextState,
    ReadTask,
    RetrievalPlan,
    RetrievalRecord,
    SearchTask,
    retrieve_documents,
)
from server.runtimes.repository.timing import ActiveDeadline
from server.services.document_indexing import DocumentIndexingService


def commit(root):
    subprocess.run(
        ["git", "-C", str(root), "add", "."], check=True, capture_output=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def indexed(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "core.autocrlf", "false"],
        check=True,
        capture_output=True,
    )
    (root / "docs").mkdir()
    original = b"# Architecture\r\nGateway details\r\n\r\n## Contracts\r\nHTTP schema\r\n\r\n## Interfaces\r\nREST API\r\n"
    (root / "docs/architecture.md").write_bytes(original)
    (root / "empty.md").write_bytes(b"")
    commit(root)
    service = DocumentIndexingService(tmp_path / "index.sqlite")
    index = service.index_repository(root)
    state = {
        "document_index": service.get_index(index.index_id),
        "documents": service.list_documents(index.index_id),
        "retrieval_plan": RetrievalPlan(tasks=[]),
    }
    return root, service, state, original


def read_task(path="docs/architecture.md"):
    return ReadTask(category="components", operation="read", path=path)


def search_task(query="HTTP schema"):
    return SearchTask(
        category="interfaces_and_contracts", operation="search", query=query
    )


def test_graph_reads_all_original_sections_with_provenance_and_no_git(
    indexed, monkeypatch
):
    root, service, state, original = indexed
    state["retrieval_plan"] = RetrievalPlan(tasks=[read_task()])
    previous = deepcopy(state)
    (root / "docs/architecture.md").unlink()
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("Retrieval must use SQLite only"),
    )
    graph = StateGraph(ArchitectureContextState)
    graph.add_node(
        "retrieve_documents",
        partial(
            retrieve_documents,
            indexing_service=service,
            limits=ToolLimits(max_page_size=1),
        ),
    )
    graph.add_edge(START, "retrieve_documents")
    graph.add_edge("retrieve_documents", END)
    result = graph.compile().invoke(state)
    sections = result["retrieved_sections"]
    assert "".join(section.content for section in sections).encode() == original
    assert [(section.start_line, section.end_line) for section in sections] == [
        (1, 3),
        (4, 6),
        (7, 8),
    ]
    assert [heading.title for heading in sections[1].headings] == [
        "Architecture",
        "Contracts",
    ]
    assert all(
        section.commit == state["document_index"].commit
        and section.repository_id == state["document_index"].repository_id
        for section in sections
    )
    assert result["retrieval_history"][0].section_ids == [
        section.section_id for section in sections
    ]
    assert result["retrieval_history"][0].status == "ok"
    assert result["retrieval_usage"].tool_calls == 4
    assert state == previous  # Updates never mutate the input or its lists.


def test_search_and_read_share_fragments_without_duplicate_results(indexed):
    _, service, state, _ = indexed
    state["retrieval_plan"] = RetrievalPlan(tasks=[read_task(), search_task()])
    events = []
    result = retrieve_documents(
        state,
        indexing_service=service,
        trace=lambda event, **values: events.append((event, values)),
    )
    assert len(result["retrieved_sections"]) == 3
    read, search = result["retrieval_history"]
    assert read.status == search.status == "ok"
    assert search.section_ids == [result["retrieved_sections"][1].section_id]
    assert result["retrieval_usage"].tool_calls == 2
    outcomes = [
        values for event, values in events if event == "retrieval_task_finished"
    ]
    assert [outcome["newly_retained"] for outcome in outcomes] == [3, 0]
    assert [outcome["duplicates"] for outcome in outcomes] == [0, 1]
    assert [outcome["status"] for outcome in outcomes] == ["ok", "ok"]
    assert result["retrieval_usage"].retrieved_characters > sum(
        len(item.model_dump_json()) for item in result["retrieved_sections"]
    )
    again = retrieve_documents(
        {
            **state,
            **result,
            "retrieved_sections": [
                *result["retrieved_sections"],
                result["retrieved_sections"][0],
            ],
        },
        indexing_service=service,
    )
    assert again["retrieval_history"] == result["retrieval_history"]
    assert again["retrieved_sections"] == result["retrieved_sections"]
    assert again["retrieval_usage"].tool_calls == 2


def test_empty_search_and_empty_document_are_valid_distinct_outcomes(indexed):
    _, service, state, _ = indexed
    state["retrieval_plan"] = RetrievalPlan(
        tasks=[search_task("absentword"), read_task("empty.md")]
    )
    result = retrieve_documents(state, indexing_service=service)
    assert result["retrieved_sections"] == []
    assert [item.status for item in result["retrieval_history"]] == ["no_results", "ok"]
    assert all(
        item.executed and item.error is None for item in result["retrieval_history"]
    )


def test_error_does_not_become_no_results_and_later_tasks_continue(
    indexed, monkeypatch
):
    _, service, state, _ = indexed
    state["retrieval_plan"] = RetrievalPlan(tasks=[search_task(), read_task()])
    monkeypatch.setattr(
        service,
        "search_fragments",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("access denied")),
    )
    result = retrieve_documents(state, indexing_service=service)
    failed, successful = result["retrieval_history"]
    assert (
        failed.status == "error" and failed.executed and failed.error == "access denied"
    )
    assert successful.status == "ok" and len(result["retrieved_sections"]) == 3
    assert result["retrieval_usage"].tool_calls == 2


def test_unknown_index_and_invalid_path_are_explicit_errors(indexed):
    _, service, state, _ = indexed
    state["retrieval_plan"] = RetrievalPlan(tasks=[read_task("../private.md")])
    result = retrieve_documents(state, indexing_service=service)
    assert result["retrieval_history"][0].status == "error"
    assert not result["retrieval_history"][0].executed
    assert result["retrieval_usage"].tool_calls == 0
    state.update(
        document_index=state["document_index"].model_copy(
            update={"index_id": "missing"}
        ),
        documents=[],
        retrieval_plan=RetrievalPlan(tasks=[search_task()]),
    )
    result = retrieve_documents(state, indexing_service=service)
    assert result["retrieval_history"][0].error == "Unknown document index"
    assert result["retrieved_sections"] == []


@pytest.mark.parametrize(
    "limits,budget",
    [
        (ToolLimits(max_source_lines=1), ExecutionBudget()),
        (ToolLimits(max_source_characters=1), ExecutionBudget()),
        (ToolLimits(max_response_characters=512), ExecutionBudget()),
        (ToolLimits(), ExecutionBudget(max_retrieved_characters=1)),
    ],
)
def test_retrieval_limits_are_not_misreported_as_empty_searches(
    indexed, limits, budget
):
    _, service, state, _ = indexed
    state["retrieval_plan"] = RetrievalPlan(tasks=[read_task()])
    result = retrieve_documents(
        state, indexing_service=service, limits=limits, budget=budget
    )
    assert result["retrieval_history"][0].status == "limited"
    assert result["retrieval_history"][0].error
    assert (
        result["retrieval_usage"].retrieved_characters
        <= budget.max_retrieved_characters
    )
    for section in result["retrieved_sections"]:
        assert section.end_line - section.start_line + 1 <= limits.max_source_lines
        assert len(section.content) <= limits.max_source_characters
    assert (
        sum(len(section.model_dump_json()) for section in result["retrieved_sections"])
        <= limits.max_response_characters
    )


def test_call_budget_persists_and_unexecuted_tasks_are_identified(indexed):
    _, service, state, _ = indexed
    state["retrieval_plan"] = RetrievalPlan(tasks=[search_task(), read_task()])
    budget = ExecutionBudget(max_tool_calls=1)
    result = retrieve_documents(state, indexing_service=service, budget=budget)
    assert result["retrieval_history"][0].executed
    assert result["retrieval_history"][1].status == "limited"
    assert not result["retrieval_history"][1].executed
    assert result["retrieval_usage"].tool_calls == 1
    again = retrieve_documents(
        {
            **state,
            **result,
            "retrieval_plan": RetrievalPlan(tasks=[search_task("Gateway")]),
        },
        indexing_service=service,
        budget=budget,
    )
    assert again["retrieval_usage"].tool_calls == 1
    assert not again["retrieval_history"][-1].executed


def test_expired_deadline_prevents_source_calls(indexed):
    _, service, state, _ = indexed
    state["retrieval_plan"] = RetrievalPlan(tasks=[read_task()])
    result = retrieve_documents(
        state, indexing_service=service, timing=ActiveDeadline(0)
    )
    assert result["retrieval_usage"].tool_calls == 0
    assert result["retrieval_history"][0].status == "limited"
    assert not result["retrieval_history"][0].executed


def test_commit_isolation_and_stale_catalog_rejection(indexed):
    root, service, old_state, _ = indexed
    (root / "docs/architecture.md").write_bytes(b"# Changed\nsnapshotnewtoken\n")
    commit(root)
    index = service.index_repository(root)
    new_state = {
        "document_index": service.get_index(index.index_id),
        "documents": service.list_documents(index.index_id),
        "retrieval_plan": RetrievalPlan(tasks=[search_task("snapshotnewtoken")]),
    }
    old_result = retrieve_documents(
        {**old_state, "retrieval_plan": new_state["retrieval_plan"]},
        indexing_service=service,
    )
    new_result = retrieve_documents(new_state, indexing_service=service)
    assert old_result["retrieval_history"][0].status == "no_results"
    assert new_result["retrieval_history"][0].status == "ok"
    assert new_result["retrieved_sections"][0].commit == index.commit
    with pytest.raises(ValueError, match="catalog does not match"):
        retrieve_documents(
            {**new_state, "documents": old_state["documents"]}, indexing_service=service
        )


def test_foreign_repository_results_and_stale_sections_are_rejected(
    indexed, tmp_path, monkeypatch
):
    root, service, state, _ = indexed
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", "--local", str(root), str(other)],
        check=True,
        capture_output=True,
    )
    foreign_index = service.index_repository(other)
    foreign = service.search_fragments(foreign_index.index_id, "HTTP schema")[0]
    state["retrieval_plan"] = RetrievalPlan(tasks=[search_task()])
    monkeypatch.setattr(service, "search_fragments", lambda *args, **kwargs: [foreign])
    result = retrieve_documents(state, indexing_service=service)
    assert result["retrieved_sections"] == []
    assert result["retrieval_history"][0].status == "error"
    with pytest.raises(ValueError, match="section does not match"):
        retrieve_documents(
            {**state, "retrieved_sections": [foreign]}, indexing_service=service
        )
    with pytest.raises(ValueError, match="history does not match"):
        retrieve_documents(
            {
                **state,
                "retrieval_history": [
                    RetrievalRecord(
                        task=search_task(),
                        index_id=foreign_index.index_id,
                        status="no_results",
                    )
                ],
            },
            indexing_service=service,
        )


def test_document_service_pages_and_rejects_unknown_exact_paths(indexed):
    _, service, state, original = indexed
    index_id = state["document_index"].index_id
    pages = [
        service.read_document_sections(
            index_id, "docs/architecture.md", limit=1, offset=offset
        )
        for offset in range(3)
    ]
    assert "".join(page[0].content for page in pages).encode() == original
    assert service.read_document_sections(index_id, "empty.md") == []
    with pytest.raises(ValueError, match="Unknown indexed document"):
        service.read_document_sections(index_id, "../private.md")


def test_failed_later_read_page_preserves_only_valid_partial_results(
    indexed, monkeypatch
):
    _, service, state, _ = indexed
    state["retrieval_plan"] = RetrievalPlan(tasks=[read_task()])
    original_read = service.read_document_sections

    def fail_later(index_id, path, *, limit, offset):
        if offset:
            raise OSError("second page inaccessible")
        return original_read(index_id, path, limit=limit, offset=offset)

    monkeypatch.setattr(service, "read_document_sections", fail_later)
    result = retrieve_documents(
        state, indexing_service=service, limits=ToolLimits(max_page_size=1)
    )
    assert len(result["retrieved_sections"]) == 1
    outcome = result["retrieval_history"][0]
    assert outcome.status == "error" and outcome.executed
    assert outcome.section_ids == [result["retrieved_sections"][0].section_id]
    assert result["retrieval_usage"].tool_calls == 2


def test_identical_text_at_different_paths_preserves_both_origins(indexed):
    root, service, _, original = indexed
    (root / "copy.md").write_bytes(original)
    commit(root)
    index = service.index_repository(root)
    state = {
        "document_index": service.get_index(index.index_id),
        "documents": service.list_documents(index.index_id),
        "retrieval_plan": RetrievalPlan(tasks=[search_task()]),
    }
    result = retrieve_documents(state, indexing_service=service)
    assert {section.path for section in result["retrieved_sections"]} == {
        "copy.md",
        "docs/architecture.md",
    }
    assert len({section.section_id for section in result["retrieved_sections"]}) == 2
