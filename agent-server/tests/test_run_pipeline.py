"""The pipeline printer shows every section of the audit."""

from server.run_pipeline import _print_audit, build_parser


def _result():
    return {
        "analysis": {
            "kind": "library",
            "primary_language": "python",
            "confidence": "high",
            "summary": "A widget library.",
            "key_components": ["a.py"],
            "files_read": 2,
            "read_rounds": 1,
        },
        "description": {
            "style": "layered",
            "intended_style": "hexagonal",
            "deviations": [],
            "components": [{"path": "a.py", "responsibility": "Does things."}],
            "data_flow": "Execution starts at main and reaches a.",
            "third_party": ["requests"],
            "cycles": [["a.py", "b.py"]],
            "quality_notes": [
                {"characteristic": "modularity", "observation": "One job.", "evidence": ["a.py"]}
            ],
            "risks": ["Circular imports: a.py ↔ b.py"],
            "confidence": "low",
        },
    }


def _grades():
    return {
        "grades": [
            {"kind": "component", "subject": "a.py", "verdict": "supported", "reason": "Does things.", "evidence": ["a.py:1-8"]},
            {"kind": "note", "subject": "note[0]: modularity", "verdict": "unverifiable", "reason": "", "evidence": []},
        ],
        "supported": 1,
        "contradicted": 0,
        "unverifiable": 1,
        "contradiction_rate": 0.0,
    }


class TestPrintAudit:
    def test_renders_connect_and_map25010_sections(self, capsys):
        _print_audit(_result())

        out = capsys.readouterr().out
        assert "Execution starts at main" in out
        assert "[modularity] One job." in out
        assert "evidence: a.py" in out
        assert "Circular imports: a.py ↔ b.py" in out
        assert "third_party       : requests" in out
        assert "a.py ↔ b.py" in out

    def test_renders_confidence_and_evidence(self, capsys):
        _print_audit(_result())

        out = capsys.readouterr().out
        assert "2 file(s) read in 1 round(s)" in out
        # The architect confidence now prints alongside the style.
        assert "confidence        : low" in out
        assert "why style:" in out
        assert "why intended:" in out
        assert "why confidence:" in out

    def test_renders_empty_sections(self, capsys):
        _print_audit({"analysis": {}, "description": {}})

        out = capsys.readouterr().out
        assert "(not traced)" in out
        assert "(none reported)" in out

    def test_renders_grades_when_present(self, capsys):
        _print_audit({**_result(), "grades": _grades()})

        out = capsys.readouterr().out
        assert "contradiction_rate: 0.00" in out
        assert "[+] [component] a.py: supported" in out
        assert "evidence: a.py:1-8" in out
        assert "[?] [note] note[0]: modularity: unverifiable" in out

    def test_omits_grades_when_absent(self, capsys):
        _print_audit(_result())

        out = capsys.readouterr().out
        assert "contradiction_rate" not in out


class TestParser:
    def test_judge_flags(self):
        args = build_parser().parse_args(["root"])

        assert args.judge is False
        assert args.judge_timeout == 300

        args = build_parser().parse_args(["root", "--judge", "--judge-timeout", "60"])

        assert args.judge is True
        assert args.judge_timeout == 60
