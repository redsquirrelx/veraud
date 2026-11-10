"""Regressions for deterministic document retrieval and source provenance."""

import asyncio
import hashlib
import json
import subprocess

import pytest

from server.runtimes.repository.document_tools import create_document_tools
from server.services.document_indexing import DocumentIndexingService
from server.services.document_indexing.splitting import split_sections


def git(root, *args):
    return (
        subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)
        .decode()
        .strip()
    )


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    git(root, "config", "core.autocrlf", "false")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")
    return root


def commit(root):
    git(root, "add", ".")
    git(root, "commit", "-m", "fixture")
    return git(root, "rev-parse", "HEAD")


def test_index_retrieval_retains_exact_original_and_excludes_dependencies(
    repository, tmp_path
):
    raw = b"Preamble\r\n\r\n# Architecture\r\n\r\n## Boundaries\r\n  gateway\tboundary  \r\n```md\r\n# not a heading\r\n```\r\n"
    (repository / "README.md").write_bytes(raw)
    for directory in ("node_modules", "dist", "generated"):
        (repository / directory).mkdir()
        (repository / directory / "hidden.md").write_text("dependency documentation")
    audited_commit = commit(repository)
    service = DocumentIndexingService(tmp_path / "index.sqlite")
    result = service.index_repository(repository, audited_commit)
    assert result.commit == audited_commit
    assert result.documents == result.processed == 1
    assert [doc.path for doc in service.list_documents(result.index_id)] == [
        "README.md"
    ]
    hits = service.search_fragments(result.index_id, "gateway boundary")
    assert len(hits) == 1
    hit = hits[0]
    assert [(h.level, h.title) for h in hit.headings] == [
        (1, "Architecture"),
        (2, "Boundaries"),
    ]
    assert hit.start_line == 5 and hit.end_line == 9
    assert hit.content == b"".join(raw.splitlines(keepends=True)[4:9]).decode()
    assert hit.content_hash == hashlib.sha256(raw).hexdigest()
    assert hit.commit == audited_commit and hit.repository_id == result.repository_id
    assert service.index_repository(repository, audited_commit).reused == 1
    # Reads use retained originals even after local edits/removal.
    (repository / "README.md").unlink()
    section = service.read_section(
        result.index_id, hit.path, hit.start_line, hit.end_line
    )
    assert section.section_id == hit.section_id
    assert section.content == hit.content
    assert service.index_repository(repository).documents == 1
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM documents").fetchone()[0] == 1


def test_incremental_commits_preserve_old_results_and_reuse_unchanged_documents(
    repository, tmp_path
):
    (repository / "a.md").write_text("# Stable\nstabletoken")
    (repository / "b.md").write_text("# Before\noldtoken")
    (repository / "removed.md").write_text("removedtoken")
    first_commit = commit(repository)
    service = DocumentIndexingService(tmp_path / "index.sqlite")
    first = service.index_repository(repository, first_commit)
    (repository / "b.md").write_text("# After\nnewtoken")
    (repository / "removed.md").unlink()
    (repository / "added.md").write_text("addedtoken")
    second_commit = commit(repository)
    second = service.index_repository(repository, second_commit)
    assert second.index_id != first.index_id
    assert second.processed == 2 and second.reused == 1
    assert {d.path for d in service.list_documents(second.index_id)} == {
        "a.md",
        "b.md",
        "added.md",
    }
    assert not service.search_fragments(second.index_id, "oldtoken")
    assert (
        service.search_fragments(first.index_id, "oldtoken")[0].commit == first_commit
    )
    assert not service.search_fragments(first.index_id, "newtoken")
    assert service.index_repository(repository, first_commit).processed == 0


def test_repository_isolation_and_bound_langchain_tools(repository, tmp_path):
    (repository / "README.md").write_text("# Shared\nsharedtoken")
    commit(repository)
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", "--local", str(repository), str(other)],
        check=True,
        capture_output=True,
    )
    (other / "README.md").write_text("# Private\nprivatetoken")
    git(
        other,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-am",
        "change",
    )
    service = DocumentIndexingService(tmp_path / "index.sqlite")
    first = service.index_repository(repository)
    second = service.index_repository(other)
    same_commit = service.index_repository(other, first.commit)
    assert same_commit.commit == first.commit and same_commit.index_id != first.index_id
    assert (
        service.search_fragments(same_commit.index_id, "sharedtoken")[0].repository_id
        == second.repository_id
    )
    assert first.repository_id != second.repository_id
    assert not service.search_fragments(first.index_id, "privatetoken")
    assert not service.search_fragments(second.index_id, "sharedtoken")
    tools = {tool.name: tool for tool in create_document_tools(service, first.index_id)}
    assert tools["list_documents"].invoke({})[0]["commit"] == first.commit
    hit = tools["search_documents"].invoke({"query": "sharedtoken"})[0]
    assert (
        tools["read_document_section"].invoke(
            {key: hit[key] for key in ("path", "start_line", "end_line")}
        )["content"]
        == hit["content"]
    )
    with pytest.raises(ValueError):
        tools["search_documents"].invoke(
            {"query": "privatetoken", "index_id": second.index_id}
        )
    with pytest.raises(ValueError, match="Unknown document section"):
        service.read_section(first.index_id, "../other/README.md", 1, 2)
    assert (
        asyncio.run(tools["search_documents"].ainvoke({"query": "sharedtoken"}))[0][
            "commit"
        ]
        == first.commit
    )


def test_langgraph_tool_node_can_consume_the_opt_in_tools(repository, tmp_path):
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode

    (repository / "README.md").write_text("# Architecture\ngateway")
    commit(repository)
    service = DocumentIndexingService(tmp_path / "index.sqlite")
    index = service.index_repository(repository)
    node = ToolNode(create_document_tools(service, index.index_id))
    graph = StateGraph(MessagesState)
    graph.add_node("tools", node)
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    output = graph.compile().invoke(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "search_documents",
                            "args": {"query": "gateway"},
                            "id": "call-1",
                            "type": "tool_call",
                        }
                    ],
                )
            ]
        }
    )
    assert json.loads(output["messages"][-1].content)[0]["commit"] == index.commit


def test_deduplicated_sources_keep_path_provenance_and_survive_reopening(
    repository, tmp_path
):
    (repository / "docs").mkdir()
    (repository / "docs" / "decision.MD").write_text("# Shared\nsametoken")
    (repository / "copy.md").write_text("# Shared\nsametoken")
    original = (repository / "copy.md").read_bytes().decode()
    (repository / "empty.md").write_text("")
    commit(repository)
    database = tmp_path / "index.sqlite"
    service = DocumentIndexingService(database)
    first = service.index_repository(repository)
    assert first.processed == 2 and first.reused == 1
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM blobs").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM section_fts").fetchone()[0] == 1
    hits = service.search_fragments(first.index_id, "sametoken")
    assert {hit.path for hit in hits} == {"copy.md", "docs/decision.MD"}
    assert len({hit.section_id for hit in hits}) == 2
    assert len(service.list_documents(first.index_id, limit=1, offset=1)) == 1
    (repository / "copy.md").rename(repository / "renamed.md")
    commit(repository)
    second = service.index_repository(repository)
    assert second.processed == 0 and second.reused == 3
    reopened = DocumentIndexingService(database)
    assert {
        hit.path for hit in reopened.search_fragments(second.index_id, "sametoken")
    } == {"renamed.md", "docs/decision.MD"}
    assert reopened.read_section(first.index_id, "copy.md", 1, 2).content == original


@pytest.mark.parametrize(
    "text",
    [
        "# Same\nfirst\n\n# Same\nsecond\n",
        "\n# Top\n\n## Child\n\n### Deep\ntext\n",
        "# Top\n~~~md\n## Fake\n\ncontent\n~~~\n## Real\nbody",
        "# Top\n```\n## Fake\nunterminated\n",
        "no headings\r\n  text\t  \r\n\r\nnext paragraph",
        "\n\n",
        "",
        "# Header only",
    ],
)
def test_splitter_covers_every_original_line_without_normalizing(text):
    sections = split_sections(text)
    lines = text.splitlines(keepends=True)
    assert (
        "".join("".join(lines[start - 1 : end]) for start, end, _ in sections) == text
    )
    if "Fake" in text:
        assert not any(
            h.title == "Fake" for _, _, headings in sections for h in headings
        )


def test_paragraphs_share_sections_but_repeated_headings_do_not():
    sections = split_sections("# Same\none\n\ntwo\n# Same\nthree\n")
    assert [(start, end) for start, end, _ in sections] == [(1, 4), (5, 6)]


def test_bm25_ranking_and_literal_query(repository, tmp_path):
    (repository / "precise.md").write_text("# Routing\ngateway boundary")
    (repository / "verbose.md").write_text(
        "# Notes\ngateway boundary " + "other " * 1000
    )
    commit(repository)
    service = DocumentIndexingService(tmp_path / "index.sqlite")
    ref = service.index_repository(repository)
    hits = service.search_fragments(ref.index_id, "gateway boundary")
    assert [hit.path for hit in hits] == ["precise.md", "verbose.md"]
    assert hits[0].score < hits[1].score
    assert service.search_fragments(ref.index_id, 'gateway " OR secret') == []
    assert service.search_fragments(ref.index_id, "***") == []
    with pytest.raises(ValueError):
        service.list_documents(ref.index_id, limit=0)
    with pytest.raises(ValueError, match="Unknown document index"):
        service.list_documents("missing")


def test_failed_index_is_atomic_and_uncommitted_files_are_ignored(repository, tmp_path):
    (repository / "a.md").write_text("small")
    (repository / "z.md").write_bytes(b"\xff")
    commit(repository)
    service = DocumentIndexingService(tmp_path / "index.sqlite")
    with pytest.raises(UnicodeDecodeError):
        service.index_repository(repository)
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM indices").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM section_fts").fetchone()[0] == 0
    (repository / "z.md").write_text("valid")
    commit(repository)
    (repository / "untracked.md").write_text("not audited")
    (repository / "a.md").write_text("local edits")
    ref = service.index_repository(repository)
    assert ref.documents == 2
    assert service.search_fragments(ref.index_id, "small")
    assert not service.search_fragments(ref.index_id, "local")
    limited = DocumentIndexingService(tmp_path / "limited.sqlite", max_file_bytes=2)
    with pytest.raises(ValueError, match="file limit"):
        limited.index_repository(repository)
    # Limits apply to reused blobs too, not only new indexing work.
    stricter = DocumentIndexingService(tmp_path / "index.sqlite", max_total_bytes=5)
    with pytest.raises(ValueError, match="total byte limit"):
        stricter.index_repository(repository)
    with pytest.raises(ValueError, match="document limit"):
        DocumentIndexingService(
            tmp_path / "index.sqlite", max_documents=1
        ).index_repository(repository)


def test_symlink_files_are_not_read(repository, tmp_path):
    (repository / "real.md").write_text("safe documentation")
    commit(repository)
    # A committed symlink entry, portable even without Windows symlink privileges.
    oid = (
        subprocess.check_output(
            ["git", "-C", str(repository), "hash-object", "-w", "--stdin"],
            input=b"../../private.md",
        )
        .decode()
        .strip()
    )
    git(repository, "update-index", "--add", "--cacheinfo", f"120000,{oid},escape.md")
    git(repository, "commit", "-m", "symlink")
    service = DocumentIndexingService(tmp_path / "index.sqlite")
    result = service.index_repository(repository)
    assert [doc.path for doc in service.list_documents(result.index_id)] == ["real.md"]


def test_nested_directory_scope_verifies_commit_without_expanding_to_parent(
    repository, tmp_path, monkeypatch
):
    (repository / "parent.md").write_text("parentonly")
    child = repository / "examples" / "shoplab" / "repository"
    child.mkdir(parents=True)
    (child / "README.md").write_text("childonly")
    audited_commit = commit(repository)

    original_run = subprocess.run

    def scoped_git(command, **kwargs):
        assert "--show-toplevel" not in command and "--full-tree" not in command
        return original_run(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", scoped_git)
    service = DocumentIndexingService(tmp_path / "scoped.sqlite")
    index = service.index_repository(child)
    assert index.commit == audited_commit
    assert [doc.path for doc in service.list_documents(index.index_id)] == ["README.md"]
    assert not service.search_fragments(index.index_id, "parentonly")
    parent = service.index_repository(repository)
    assert parent.repository_id != index.repository_id
    assert service.index_repository(child, audited_commit).index_id == index.index_id
    with pytest.raises(ValueError, match="Cannot read repository commit"):
        service.index_repository(child, "nonexistent-commit")
    (child / "README.md").write_text("updated child")
    updated = service.index_repository(child)
    assert (
        updated.index_id == index.index_id
    )  # Local edits cannot change committed evidence.
    assert not service.search_fragments(updated.index_id, "updated")
    commit(repository)
    updated = service.index_repository(child)
    assert updated.index_id != index.index_id
    assert service.search_fragments(index.index_id, "childonly")
    assert service.index_repository(child, audited_commit).index_id == index.index_id
