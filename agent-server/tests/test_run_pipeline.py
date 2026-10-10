"""The pipeline printer shows every section of the audit."""

from server.run_pipeline import _print_audit


def _result():
    return {
        "analysis": {
            "kind": "library",
            "primary_language": "python",
            "confidence": "high",
            "summary": "A widget library.",
            "key_components": ["a.py"],
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

    def test_renders_empty_sections(self, capsys):
        _print_audit({"analysis": {}, "description": {}})

        out = capsys.readouterr().out
        assert "(not traced)" in out
        assert "(none reported)" in out
