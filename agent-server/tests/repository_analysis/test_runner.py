import json

from server.run_repository_analysis import main


def test_runner_outputs_machine_readable_queries_without_retained_source(
    tmp_path, capsys
):
    (tmp_path / "main.py").write_text("def main():\n    return 42\n", encoding="utf-8")
    assert main([str(tmp_path), "--query", "files"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["total"] == 1
    assert "content" not in result["items"][0]
    assert (
        main(
            [
                str(tmp_path),
                "--query",
                "source",
                "--path",
                "main.py",
                "--start-line",
                "2",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["content"] == "    return 42"


def test_runner_has_readable_summary_and_controlled_errors(tmp_path, capsys):
    (tmp_path / "main.py").write_text("VALUE = 42\n", encoding="utf-8")
    assert main([str(tmp_path)]) == 0
    summary = capsys.readouterr().out
    assert "deterministic, in memory, no LLM calls" in summary
    assert "Coverage:" in summary
    assert main([str(tmp_path), "--query", "search"]) == 2
    assert "requires --text" in capsys.readouterr().err
    assert main([str(tmp_path / "missing")]) == 1
