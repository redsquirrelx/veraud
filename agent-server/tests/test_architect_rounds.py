"""The architect re-reads until every key component is described.

A scripted model stands in for provider answers. Each prompt step is told
apart by its task's first line, so survey answers and characterize answers
never get mixed up without coupling to anything else in the templates.
"""

import asyncio
import json

from server.agents.architect.agent import ArchitectureAgent, _survey_floor
from server.agents.architect.schemas import ArchitectInput
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
        self.calls = []

    async def generate(self, message):
        for first_line, step in FIRST_LINES.items():
            if first_line in message:
                self.calls.append(step)
                queue = self._answers.get(step, [])
                if not queue:
                    raise RuntimeError(f"no scripted {step} answer left")
                return json.dumps(queue.pop(0))
        raise RuntimeError("unrecognized prompt")


def _settings(model):
    return (
        AgentSettings(agent_id="architect", timeout_seconds=180),
        model,
    )


def _model(answers):
    return ScriptedModel(
        ModelSettings(provider="test", name="test", temperature=0.0, max_tokens=10),
        ModelCredentials(api_key="test"),
        answers,
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


def _frame():
    return {
        "style": "layered",
        "intended_style": "hexagonal",
        "reasoning": "r",
        "would_confirm": ["main.py"],
        "deviations": [],
    }


def _describe(path, responsibility):
    return {"components": [{"path": path, "responsibility": responsibility}]}


class TestCoverageLoop:
    def test_reads_until_everything_is_described(self, tmp_path):
        _repo(tmp_path)
        model = _model({
            "frame": [_frame()],
            "survey": [{"paths": ["main.py"]}, {"paths": ["pkg/core.py"]}],
            "characterize": [
                _describe("main.py", "Starts the shop."),
                _describe("pkg/core.py", "Holds the core logic."),
            ],
            "connect": [{"data_flow": "Main reaches core."}],
            "map25010": [{"quality_notes": [], "risks": []}],
        })

        agent = ArchitectureAgent(*_settings(model))
        description = asyncio.run(agent.run(ArchitectInput(
            root_path=str(tmp_path), analysis=_analysis(),
        )))

        assert [component.path for component in description.components] == [
            "main.py", "pkg/core.py",
        ]
        assert [component.responsibility for component in description.components] == [
            "Starts the shop.", "Holds the core logic.",
        ]
        # Covered in two rounds: medium from evidence, not from the model.
        assert description.confidence == "medium"
        assert model.calls == [
            "frame",
            "survey", "characterize",
            "survey", "characterize",
            "connect", "map25010",
        ]

    def test_stops_when_coverage_stalls(self, tmp_path):
        _repo(tmp_path)
        model = _model({
            "frame": [_frame()],
            "survey": [{"paths": ["main.py"]}, {"paths": ["pkg/core.py"]}],
            "characterize": [
                _describe("main.py", "Starts the shop."),
                _describe("main.py", "Starts the shop."),
            ],
            "connect": [{"data_flow": "Main reaches core."}],
            "map25010": [{"quality_notes": [], "risks": []}],
        })

        agent = ArchitectureAgent(*_settings(model))
        description = asyncio.run(agent.run(ArchitectInput(
            root_path=str(tmp_path), analysis=_analysis(),
        )))

        # The second round described nothing new, so the loop stops instead
        # of spending the third round. Half covered with a known intent is
        # medium, straight from the calibration.
        assert model.calls.count("characterize") == 2
        assert description.confidence == "medium"

    def test_max_read_rounds_is_respected(self, tmp_path):
        _repo(tmp_path)
        model = _model({
            "frame": [_frame()],
            "survey": [{"paths": ["main.py"]}],
            "characterize": [_describe("main.py", "Starts the shop.")],
            "connect": [{"data_flow": "Main reaches core."}],
            "map25010": [{"quality_notes": [], "risks": []}],
        })

        agent = ArchitectureAgent(*_settings(model))
        description = asyncio.run(agent.run(ArchitectInput(
            root_path=str(tmp_path), analysis=_analysis(), max_read_rounds=1,
        )))

        assert model.calls.count("characterize") == 1
        assert description.confidence == "medium"


class TestCharacterizeMerge:
    def test_keeps_earlier_descriptions(self):
        model = _model({"characterize": [_describe("b.py", "Does B.")]})
        agent = ArchitectureAgent(*_settings(model))
        state = {
            "derived_key_components": ["a.py", "b.py"],
            "excerpts": "--- b.py\nprint(1)\n",
            "known_files": {"a.py", "b.py"},
            "components": [{"path": "a.py", "responsibility": "Does A."}],
        }

        components = asyncio.run(agent._characterize(state))

        assert components == {"components": [
            {"path": "a.py", "responsibility": "Does A."},
            {"path": "b.py", "responsibility": "Does B."},
        ]}


class TestSurveyFloorRounds:
    def test_later_rounds_prioritize_undescribed(self):
        state = {
            "frame": {},
            "entrypoints": ["main.py"],
            "derived_key_components": ["a.py", "b.py"],
            "components": [{"path": "a.py", "responsibility": "Does A."}],
            "read_paths": ["main.py"],
            "known_files": {"main.py", "a.py", "b.py"},
            "rounds": 1,
        }

        assert _survey_floor(state) == ["b.py", "a.py"]
