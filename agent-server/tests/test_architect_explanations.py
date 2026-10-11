"""The architect explains its style, its intended style and its confidence.

Style explanations come from the frame model; the confidence explanation is
derived from the same evidence that sets the level, never written by the
model.
"""

import asyncio
import json

from server.agents.architect.agent import ArchitectureAgent, _explain_confidence
from server.agents.architect.schemas import ArchitectInput, ArchitectureDescription
from server.agents.models.base import Model
from server.config.schemas import AgentSettings, ModelCredentials, ModelSettings

FIRST_LINES = {
    "Decide what this repository TRIES to be": "frame",
    "Decide which files to read": "survey",
    "Describe what each key component": "characterize",
    "Trace how execution flows": "connect",
    "Report maintainability observations": "map25010",
}


class ScriptedModel(Model):
    def __init__(self, settings, credentials, answers):
        super().__init__(settings, credentials)
        self._answers = {step: list(queue) for step, queue in answers.items()}

    async def generate(self, message):
        for first_line, step in FIRST_LINES.items():
            if first_line in message:
                return json.dumps(self._answers[step].pop(0))
        raise RuntimeError("unrecognized prompt")


def _agent(answers):
    return ArchitectureAgent(
        AgentSettings(agent_id="architect", timeout_seconds=180),
        ScriptedModel(
            ModelSettings(provider="test", name="test", temperature=0.0, max_tokens=10),
            ModelCredentials(api_key="test"),
            answers,
        ),
    )


def _analysis():
    return {
        "kind": "script",
        "summary": "t",
        "primary_language": "python",
        "entrypoints": [],
        "key_components": [],
        "confidence": "low",
        "files_read": 0,
        "read_rounds": 0,
        "hypothesis_confirmed": False,
    }


def _repo(root):
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("x = 1\n")
    (root / "pkg" / "core.py").write_text("def run():\n    return 1\n")
    (root / "main.py").write_text("from pkg.core import run\n\nrun()\n")


class TestExplainConfidence:
    def test_names_everything_when_high(self):
        components = [
            {"path": "a.py", "responsibility": "Does A."},
            {"path": "b.py", "responsibility": "Does B."},
        ]
        notes = [{"characteristic": "modularity", "observation": "x", "evidence": ["a.py"]}]

        assert _explain_confidence(components, notes, "hexagonal") == (
            "2/2 components described; "
            "1 quality note(s) with evidence; "
            "intended style known (hexagonal)."
        )

    def test_names_gaps_and_truncates(self):
        components = [{"path": f"{n}.py", "responsibility": ""} for n in range(7)]

        assert _explain_confidence(components, [], "unknown") == (
            "0/7 components described; "
            "undescribed: 0.py, 1.py, 2.py, 3.py, 4.py and 2 more; "
            "no quality notes with evidence; "
            "intended style unknown."
        )

    def test_empty_components(self):
        assert _explain_confidence([], [], "unknown") == (
            "no key components found; "
            "no quality notes with evidence; "
            "intended style unknown."
        )


class TestExplanationsFlow:
    def test_frame_reasonings_reach_the_output(self, tmp_path):
        _repo(tmp_path)
        agent = _agent({
            "frame": [{
                "style": "layered",
                "intended_style": "hexagonal",
                "reasoning": "main.py calls pkg/core.py directly.",
                "intended_reasoning": "pkg/ mirrors a port layout.",
                "would_confirm": ["main.py"],
                "deviations": [],
            }],
            "survey": [{"paths": ["main.py", "pkg/core.py"]}],
            "characterize": [{"components": [
                {"path": "main.py", "responsibility": "Starts it."},
                {"path": "pkg/core.py", "responsibility": "Runs it."},
            ]}],
            "connect": [{"data_flow": "Main reaches core."}],
            "map25010": [{"quality_notes": [], "risks": []}],
        })

        description = asyncio.run(agent.run(ArchitectInput(
            root_path=str(tmp_path), analysis=_analysis(),
        )))

        assert description.style_explanation == "main.py calls pkg/core.py directly."
        assert description.intended_explanation == "pkg/ mirrors a port layout."
        assert description.confidence_explanation == (
            "2/2 components described; "
            "no quality notes with evidence; "
            "intended style known (hexagonal)."
        )

    def test_missing_reasonings_default_to_empty(self):
        description = ArchitectureDescription()

        assert description.style_explanation == ""
        assert description.intended_explanation == ""
        assert description.confidence_explanation == ""
