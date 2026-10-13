"""Independent exported-report review and optional integrated roundtrip smoke."""

import json

from server.run_project_architecture import main as architecture_main
from server.run_project_semantic_validation import main


def test_standalone_and_integrated_smoke_preserve_original(tmp_path, capsys):
    root = tmp_path / "workspace" / "selected"
    root.mkdir(parents=True)
    (root / "main.py").write_text(
        "from service import run\ndef main():\n    return run()\n", encoding="utf-8"
    )
    (root / "service.py").write_text("def run():\n    return 42\n", encoding="utf-8")
    args = [
        str(root),
        "--workspace-root",
        str(root.parent),
        "--smoke",
        "--quiet",
        "--json",
        "--max-total-tokens",
        "160000",
    ]
    assert architecture_main(args) == 0
    original = json.loads(capsys.readouterr().out)
    report = tmp_path / "report.json"
    original["usage"]["investigations_started"] = 0
    report.write_text(json.dumps(original), encoding="utf-16")
    assert main([*args, "--report", str(report)]) == 0
    review = json.loads(capsys.readouterr().out)
    assert review["verdict"] == "needs_evidence"
    assert review["original_result"]["architecture"] == original["architecture"]
    assert architecture_main([*args, "--validate-semantics"]) == 0
    result = json.loads(capsys.readouterr().out)
    pipeline = result["semantic_validation"]
    assert pipeline["return_count"] == 1 and len(pipeline["validations"]) == 2
    assert result["architecture"] == pipeline["original_architecture"]["architecture"]
    assert result["pipeline_usage"]["model_calls"] == (
        result["usage"]["model_calls"]
        + result["orientation_result"]["usage"]["model_calls"]
        + sum(review["usage"]["model_calls"] for review in pipeline["validations"])
        + pipeline["revised_architecture"]["usage"]["model_calls"]
    )
    assert (
        architecture_main([*args, "--validate-semantics", "--no-semantic-return"]) == 0
    )
    assert (
        json.loads(capsys.readouterr().out)["semantic_validation"]["return_count"] == 0
    )


def test_architecture_runner_initial_review_continues_after_token_target(
    tmp_path, capsys
):
    root = tmp_path / "workspace" / "selected"
    root.mkdir(parents=True)
    (root / "main.py").write_text("def main():\n    return 42\n", encoding="utf-8")
    assert (
        architecture_main(
            [
                str(root),
                "--workspace-root",
                str(root.parent),
                "--smoke",
                "--quiet",
                "--json",
                "--skip-orientation",
                "--validate-semantics",
                "--no-semantic-return",
                "--max-total-tokens",
                "1000",
                "--max-objective-tokens",
                "1000",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    first = result["semantic_validation"]["validations"][0]
    assert first["completion_status"] == "complete"
    assert first["usage"]["accounted_tokens"] > 1000
    assert not first["usage"]["token_budget_exhausted"]
    assert result["run_metadata"]["initial_review_soft_token_budgets"] is True
