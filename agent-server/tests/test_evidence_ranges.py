"""Evidence cites line intervals, not just files.

Ranges ride along as `path:L1-L2,...` strings: parsing keeps the raw entry,
ranged reading narrows to the cited lines, and malformed entries are dropped
like invented paths.
"""

from pathlib import Path

from server.agents.analyzer import parsing as analyzer_parsing
from server.agents.analyzer.evidence import read_ranged_excerpts, render_excerpts

KNOWN = {"a.py", "b.py"}


class TestSplitEvidence:
    def test_bare_path_has_no_ranges(self):
        assert analyzer_parsing.split_evidence("a.py") == ("a.py", None)

    def test_single_line_and_range(self):
        assert analyzer_parsing.split_evidence("a.py:7") == ("a.py", [(7, 7)])
        assert analyzer_parsing.split_evidence("a.py:12-34") == ("a.py", [(12, 34)])

    def test_multiple_ranges(self):
        assert analyzer_parsing.split_evidence("a.py:12-34,40-52") == (
            "a.py", [(12, 34), (40, 52)],
        )

    def test_malformed_is_none(self):
        assert analyzer_parsing.split_evidence("") is None
        assert analyzer_parsing.split_evidence("a.py:") is None
        assert analyzer_parsing.split_evidence("a.py:0-3") is None
        assert analyzer_parsing.split_evidence("a.py:9-3") is None
        assert analyzer_parsing.split_evidence("a.py:x") is None
        assert analyzer_parsing.split_evidence(":12-34") is None


class TestReadEvidence:
    def test_keeps_bare_and_ranged_known_paths(self):
        parsed = {"evidence": ["a.py", "b.py:12-34,40", "ghost.py", "ghost.py:1-2", "a.py:9-3", "  "]}

        assert analyzer_parsing.read_evidence(parsed, "evidence", KNOWN) == [
            "a.py", "b.py:12-34,40",
        ]

    def test_missing_key_is_empty(self):
        assert analyzer_parsing.read_evidence({}, "evidence", KNOWN) == []


class TestReadRangedExcerpts:
    def _repo(self, root: Path):
        root.joinpath("a.py").write_text("\n".join(f"line {n}" for n in range(1, 51)) + "\n")

    def test_reads_only_cited_lines_plus_context(self, tmp_path):
        self._repo(tmp_path)

        excerpts = read_ranged_excerpts(tmp_path, ["a.py:20-21"], context=2)

        assert len(excerpts) == 1
        assert excerpts[0].label == "a.py:20-21"
        assert "line 20" in excerpts[0].text
        assert "line 18" in excerpts[0].text
        assert "line 23" in excerpts[0].text
        assert "line 17" not in excerpts[0].text
        assert "line 24" not in excerpts[0].text

    def test_bare_path_reads_the_whole_file(self, tmp_path):
        self._repo(tmp_path)

        excerpts = read_ranged_excerpts(tmp_path, ["a.py"])

        assert len(excerpts) == 1
        assert "line 1" in excerpts[0].text
        assert "line 50" in excerpts[0].text

    def test_out_of_range_and_missing_are_skipped(self, tmp_path):
        self._repo(tmp_path)

        assert read_ranged_excerpts(tmp_path, ["a.py:99-120"]) == []
        assert read_ranged_excerpts(tmp_path, ["ghost.py:1-2"]) == []

