"""Readable/raw console output uses synthetic typed results, never saved reports."""

import json

import pytest
import run_code_comprehension as runner
from code_comprehension_output import format_result
from test_code_comprehension import evaluate, review, run_agent

pytest_plugins = ("test_code_comprehension",)


def test_raw_output_preserves_every_result_field(repo):
    result, _, _ = run_agent(repo)
    assert json.loads(format_result(result, "raw")) == result.model_dump(mode="json")


def test_readable_explains_accepted_conclusion_impact_action_and_evidence(repo):
    result, _, _ = run_agent(repo)
    output = format_result(result)
    assert "Se confirmaron 1 hallazgo(s)" in output
    assert "HALLAZGOS ACEPTADOS (1)" in output
    finding = result.findings[0]
    for text in (finding.title, finding.description, finding.justification, finding.modularity_impact,
            finding.recommendation, finding.review_rationale):
        assert text in output
    assert "[E1] component.py:1–11" in output
    assert "Severidad: baja | Confianza: 70%" in output
    assert "Confirmada:" in output and "CONSUMO" in output
    assert "no certifican la claridad de todo el repositorio" in output


def test_readable_does_not_confuse_inconclusive_or_rejected_proposals_with_success(repo):
    result, _, _ = run_agent(repo, reviewer=lambda messages: review(messages, status="rejected", scope=False))
    output = format_result(result)
    assert "HALLAZGOS ACEPTADOS (0)" in output
    assert "no permite concluir que el código sea claro" in output
    assert "PROPUESTAS NO ACEPTADAS (NO SON HALLAZGOS)" in output
    assert "Rechazada" in output and "Inconclusa:" in output
    assert "INFORMACIÓN FALTANTE" in output and result.missing_information[0] in output


def test_readable_clear_case_is_scoped_and_budget_stop_is_not_a_clean_bill(repo):
    result, _, _ = run_agent(repo, evaluator=lambda messages: evaluate(messages, clear=True, candidate=False),
        reviewer=lambda messages: review(messages, candidate=False))
    output = format_result(result)
    assert "No se confirmaron problemas de comprensión en las hipótesis examinadas" in output
    assert "Descartada:" in output
    stopped = result.model_copy(update={"termination_reason": "token_limit"})
    assert "investigación quedó incompleta" in format_result(stopped)
    assert "no permite concluir que el código sea claro" in format_result(stopped)


def test_rejected_findings_do_not_erase_independently_confirmed_hypotheses(repo):
    result, _, _ = run_agent(repo, reviewer=lambda messages: review(messages, status="rejected"))
    output = format_result(result)
    assert "Confirmada:" in output
    assert "no superaron la revisión como hallazgos" in output
    assert "No se confirmaron problemas" not in output


def test_formatting_reads_no_source_and_invokes_no_model(repo, monkeypatch):
    result, model, tools = run_agent(repo)

    def forbidden(*args, **kwargs):
        pytest.fail("Console formatting must not read files or invoke models/tools")

    from pathlib import Path

    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(model, "ainvoke", forbidden)
    monkeypatch.setattr(tools, "execute", forbidden)
    assert format_result(result) and format_result(result, "raw")
    with pytest.raises(ValueError, match="Unknown output format"):
        format_result(result, "html")


@pytest.mark.parametrize("arguments, expected", [([], "readable"), (["--output", "readable"], "readable"),
    (["--output", "raw"], "raw")])
def test_cli_selects_readable_by_default_or_explicit_output(monkeypatch, arguments, expected):
    captured = []

    async def run(args):
        captured.append(args.output)

    monkeypatch.setattr(runner, "run", run)
    monkeypatch.setattr("sys.argv", ["run_code_comprehension.py", "synthetic-repository", *arguments])
    runner.main()
    assert captured == [expected]


def test_cli_rejects_unknown_output_before_running_an_audit(monkeypatch):
    monkeypatch.setattr("sys.argv", ["run_code_comprehension.py", "synthetic-repository", "--output", "html"])
    with pytest.raises(SystemExit) as failure:
        runner.main()
    assert failure.value.code == 2
