"""Evidence cites line intervals, not just files.

Ranges ride along as `path:L1-L2,...` strings: parsing keeps the raw entry,
ranged reading narrows to the cited lines, and malformed entries are dropped
like invented paths.
"""

import asyncio
import json
from pathlib import Path

from server.agents.analyzer import parsing as analyzer_parsing
from server.agents.analyzer.evidence import read_ranged_excerpts, render_excerpts
from server.agents.architect.agent import _read_deviations, _read_quality_notes
from server.agents.judge.agent import JudgeAgent
from server.agents.judge.schemas import JudgeInput
from server.agents.models.base import Model
from server.config.schemas import AgentSettings, ModelCredentials, ModelSettings

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


class TestRangedDeviationsAndNotes:
    def test_deviations_keep_raw_ranged_entries(self):
        answer = {"deviations": [
            {"observation": "Skipped port.", "evidence": ["a.py:12-34", "ghost.py:1-2", "a.py:9-3"]},
        ]}

        assert _read_deviations(answer, KNOWN) == [
            {"observation": "Skipped port.", "evidence": ["a.py:12-34"]},
        ]

    def test_notes_keep_raw_ranged_entries(self):
        answer = {"quality_notes": [
            {"characteristic": "modularity", "observation": "One job.", "evidence": ["b.py:3"]},
        ]}

        assert _read_quality_notes(answer, KNOWN) == [
            {"characteristic": "modularity", "observation": "One job.", "evidence": ["b.py:3"]},
        ]


class ScriptedModel(Model):
    def __init__(self, settings, credentials, answers):
        super().__init__(settings, credentials)
        self._answers = list(answers)
        self.calls = []

    async def generate(self, message):
        self.calls.append(message)
        return json.dumps(self._answers.pop(0))


class TestRangedJudge:
    def _agent(self, answers):
        return JudgeAgent(
            AgentSettings(agent_id="judge", timeout_seconds=120),
            ScriptedModel(
                ModelSettings(provider="test", name="test", temperature=0.0, max_tokens=10),
                ModelCredentials(api_key="test"),
                answers,
            ),
        )

    def _description(self, notes):
        return {
            "style": "layered",
            "components": [],
            "quality_notes": notes,
            "confidence": "low",
        }

    def test_grades_against_cited_lines_only(self, tmp_path):
        tmp_path.joinpath("a.py").write_text("keep = 1\n" + "\n".join(f"filler {n}" for n in range(30)) + "\ndrop = 2\n")
        agent = self._agent([{"verdict": "supported", "reason": "keep is there.", "evidence": ["a.py:1"]}])

        report = asyncio.run(agent.run(JudgeInput(
            root_path=str(tmp_path),
            description=self._description([
                {"characteristic": "modularity", "observation": "Keeps one.", "evidence": ["a.py:1"]},
            ]),
        )))

        assert [(g.subject, g.verdict) for g in report.grades] == [
            ("note[0]: modularity", "supported"),
        ]
        # The prompt carries the cited line, not the far end of the file.
        assert "keep = 1" in agent.model.calls[0]
        assert "drop = 2" not in agent.model.calls[0]

    def test_range_outside_file_is_unverifiable_without_a_call(self, tmp_path):
        tmp_path.joinpath("a.py").write_text("x = 1\n")
        agent = self._agent([])

        report = asyncio.run(agent.run(JudgeInput(
            root_path=str(tmp_path),
            description=self._description([
                {"characteristic": "modularity", "observation": "Keeps one.", "evidence": ["a.py:99-120"]},
            ]),
        )))

        assert [(g.subject, g.verdict) for g in report.grades] == [
            ("note[0]: modularity", "unverifiable"),
        ]
        assert agent.model.calls == []

    def test_rendered_header_names_the_range(self, tmp_path):
        tmp_path.joinpath("a.py").write_text("x = 1\ny = 2\n")

        excerpts = read_ranged_excerpts(tmp_path, ["a.py:1-2"])

        assert render_excerpts(excerpts).startswith("--- a.py:1-2\n")
