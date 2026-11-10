"""Exercise the thin CLI against committed Markdown without models."""

import subprocess
from pathlib import Path

import pytest

from server import run_document_indexing as cli
from server.run_document_indexing import main


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repository with spaces"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "core.autocrlf", "false"],
        check=True,
        capture_output=True,
    )
    (root / "README.md").write_text(
        "# Architecture\ngateway boundary\n", encoding="utf-8"
    )
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
    return root


def test_list_search_and_reuse(repository, tmp_path, capsys):
    arguments = [str(repository), "--database", str(tmp_path / "docs.sqlite")]
    assert main(arguments) == 0
    output = capsys.readouterr().out
    assert "README.md" in output and "processed: 1" in output
    assert "Commit:" in output and "local changes are not indexed" in output
    assert main([*arguments, "--query", "gateway", "--limit", "1"]) == 0
    output = capsys.readouterr().out
    assert "processed: 0; reused: 1" in output
    assert "README.md:1-2" in output and "gateway boundary" in output
    assert main([*arguments, "--query", "absentword"]) == 0
    assert "Search results: 0" in capsys.readouterr().out


def test_default_database_can_be_overridden_by_host(
    repository, tmp_path, monkeypatch, capsys
):
    # Redirect host cache to avoid persistent writes during testing.
    cache = tmp_path / "host-cache"
    monkeypatch.setenv("LOCALAPPDATA", str(cache))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    assert main([str(repository), "--commit", "HEAD"]) == 0
    assert (cache / "veraud" / "document-index.sqlite").is_file()
    assert "Database:" in capsys.readouterr().out


def test_database_inside_repository_is_rejected_before_writing(repository, capsys):
    database = repository / "new-directory" / "docs.sqlite"
    assert main([str(repository), "--database", str(database)]) == 1
    assert "outside the audited repository" in capsys.readouterr().err
    assert not database.parent.exists()


def test_bad_repository_and_invalid_commit_fail(tmp_path, repository, capsys):
    database = str(tmp_path / "docs.sqlite")
    assert main([str(tmp_path / "missing"), "--database", database]) == 1
    assert "Document indexing failed:" in capsys.readouterr().err
    assert (
        main(
            [str(repository), "--database", database, "--commit", "nonexistent-commit"]
        )
        == 1
    )
    assert "Cannot read repository commit" in capsys.readouterr().err


@pytest.mark.parametrize(
    "options", [["--limit", "0"], ["--limit", "101"], ["--query", " "]]
)
def test_invalid_arguments_are_rejected_without_creating_database(
    repository, tmp_path, options
):
    database = tmp_path / "docs.sqlite"
    with pytest.raises(SystemExit) as error:
        main([str(repository), "--database", str(database), *options])
    assert error.value.code == 2
    assert not database.exists()


def test_direct_script_execution(repository, tmp_path):
    import sys

    script = Path(__file__).resolve().parents[1] / "src/server/run_document_indexing.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            str(repository),
            "--database",
            str(tmp_path / "docs.sqlite"),
            "--query",
            "gateway",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "README.md:1-2" in result.stdout


@pytest.mark.parametrize("query", [None, "gateway", "absentword"])
def test_json_export_payload_without_reading_json(
    repository, tmp_path, monkeypatch, capsys, query
):
    reports = []
    original_dump = cli.json.dump

    def capture_report(report, stream, **kwargs):
        reports.append(report)
        return original_dump(report, stream, **kwargs)

    monkeypatch.setattr(cli.json, "dump", capture_report)
    output = tmp_path / "reports" / "result.json"
    arguments = [
        str(repository),
        "--database",
        str(tmp_path / "docs.sqlite"),
        "--output",
        str(output),
    ]
    if query is not None:
        arguments.extend(["--query", query])
    assert main(arguments) == 0
    assert output.is_file()
    assert "JSON report:" in capsys.readouterr().out
    report = reports[0]
    assert report["summary"]["documents"] == 1
    assert report["documents"][0]["path"] == "README.md"
    assert report["query"] == query
    if query == "gateway":
        hit = report["results"][0]
        assert hit["content"] == (repository / "README.md").read_bytes().decode()
        assert hit["start_line"] == 1 and hit["end_line"] == 2
        assert hit["headings"] == [{"level": 1, "title": "Architecture"}]
        assert hit["commit"] == report["summary"]["commit"]
    else:
        assert report["results"] == []


def test_export_includes_all_document_pages_and_untruncated_content(
    repository, tmp_path, monkeypatch
):
    for number in range(101):
        (repository / f"doc-{number:03}.md").write_text("extra", encoding="utf-8")
    (repository / "README.md").write_text(
        "# Architecture\ngateway " + "boundary " * 200, encoding="utf-8"
    )
    subprocess.run(
        ["git", "-C", str(repository), "add", "."], check=True, capture_output=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "more documents",
        ],
        check=True,
        capture_output=True,
    )
    reports = []
    original_dump = cli.json.dump

    def capture_report(report, stream, **kwargs):
        reports.append(report)
        return original_dump(report, stream, **kwargs)

    monkeypatch.setattr(cli.json, "dump", capture_report)
    assert (
        main(
            [
                str(repository),
                "--database",
                str(tmp_path / "docs.sqlite"),
                "--query",
                "gateway",
                "--limit",
                "1",
                "--output",
                str(tmp_path / "result.json"),
            ]
        )
        == 0
    )
    assert len(reports[0]["documents"]) == 102
    assert len(reports[0]["results"]) == 1
    assert len(reports[0]["results"][0]["content"]) > 1000
    assert (
        reports[0]["results"][0]["content"]
        == (repository / "README.md").read_bytes().decode()
    )


def test_export_never_overwrites_existing_files_or_database(
    repository, tmp_path, capsys
):
    existing = tmp_path / "existing.txt"
    existing.write_text("user work", encoding="utf-8")
    database = tmp_path / "docs.sqlite"
    for output in (existing, database):
        assert (
            main(
                [
                    str(repository),
                    "--database",
                    str(database),
                    "--output",
                    str(output),
                ]
            )
            == 1
        )
        assert "Output must be a new file" in capsys.readouterr().err
    assert existing.read_text(encoding="utf-8") == "user work"
    assert not database.exists()


def test_cli_indexes_committed_directory_without_expanding_to_parent(
    repository, tmp_path, monkeypatch, capsys
):
    child = repository / "selected"
    child.mkdir()
    (child / "README.md").write_text("local documentation", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repository), "add", "."], check=True, capture_output=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "child fixture",
        ],
        check=True,
        capture_output=True,
    )

    original_run = subprocess.run

    def scoped_git(command, **kwargs):
        assert "--show-toplevel" not in command and "--full-tree" not in command
        return original_run(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", scoped_git)
    assert main([str(child), "--database", str(tmp_path / "scoped.sqlite")]) == 0
    text = capsys.readouterr().out
    assert f"Repository: {child.resolve()}" in text and "Documents: 1" in text
