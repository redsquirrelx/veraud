"""The judge grades support blind, fail-safe toward distrust.

A scripted model stands in for provider answers, told apart by the grade
task's first line. Nothing here touches the network or a model.
"""

import asyncio
import json

import pytest

from server.agents.judge.agent import JudgeAgent
from server.agents.judge.schemas import JudgeInput
from server.agents.models.base import Model
from server.config.schemas import AgentSettings, ModelCredentials, ModelSettings

GRADE_TASK = "Grade whether the claim is supported"


class ScriptedModel(Model):
    def __init__(self, settings, credentials, answers):
        super().__init__(settings, credentials)
        self._answers = list(answers)
        self.calls = []

    async def generate(self, message):
        if GRADE_TASK not in message:
            raise RuntimeError("unrecognized prompt")
        self.calls.append(message)
        if not self._answers:
            raise RuntimeError("no scripted grade answer left")
        return json.dumps(self._answers.pop(0))


def _settings(model):
    return (
        AgentSettings(agent_id="judge", timeout_seconds=120),
        model,
    )


def _model(answers):
    return ScriptedModel(
        ModelSettings(provider="test", name="test", temperature=0.0, max_tokens=10),
        ModelCredentials(api_key="test"),
        answers,
    )


def _repo(root):
    (root / "a.py").write_text("def run():\n    return 1\n")
    (root / "b.py").write_text("X = 2\n")


def _description(**overrides):
    values = {
        "style": "layered",
        "intended_style": "layered",
        "components": [
            {"path": "a.py", "responsibility": "Runs things."},
            {"path": "b.py", "responsibility": ""},
        ],
        "quality_notes": [
            {"characteristic": "modularity", "observation": "One job.", "evidence": ["a.py"]},
        ],
        "confidence": "medium",
    }
    values.update(overrides)
    return values


def _grade(verdict, reason="Because.", evidence=None):
    return {"verdict": verdict, "reason": reason, "evidence": evidence if evidence is not None else []}


class TestGrading:
    def test_supported_and_contradicted(self, tmp_path):
        _repo(tmp_path)
        model = _model([
            _grade("supported", "run() is right there.", ["a.py:1-2"]),
            _grade("contradicted", "a.py holds no such thing.", ["b.py:1"]),
        ])
        agent = JudgeAgent(*_settings(model))

        report = asyncio.run(agent.run(JudgeInput(
            root_path=str(tmp_path),
            description={
                **_description(),
                "components": [
                    {"path": "a.py", "responsibility": "Runs things."},
                    {"path": "b.py", "responsibility": "Holds X."},
                ],
                "quality_notes": [],
            },
        )))

        assert [(g.subject, g.verdict, g.evidence) for g in report.grades] == [
            ("a.py", "supported", ["a.py:1-2"]), ("b.py", "contradicted", ["b.py:1"]),
        ]
        assert (report.supported, report.contradicted, report.unverifiable) == (1, 1, 0)
        assert report.contradiction_rate == 0.5

    def test_verdict_without_checkable_evidence_is_demoted(self, tmp_path):
        _repo(tmp_path)
        model = _model([
            _grade("supported", "Trust me."),
            _grade("contradicted", "No proof.", ["ghost.py:1-2"]),
        ])
        agent = JudgeAgent(*_settings(model))

        report = asyncio.run(agent.run(JudgeInput(
            root_path=str(tmp_path),
            description={
                **_description(),
                "components": [
                    {"path": "a.py", "responsibility": "Runs things."},
                    {"path": "b.py", "responsibility": "Holds X."},
                ],
                "quality_notes": [],
            },
        )))

        assert [(g.subject, g.verdict, g.reason) for g in report.grades] == [
            ("a.py", "unverifiable", "No checkable evidence cited."),
            ("b.py", "unverifiable", "No checkable evidence cited."),
        ]
        assert (report.supported, report.contradicted, report.unverifiable) == (0, 0, 2)
        assert report.contradiction_rate == 0.0

    def test_unparseable_is_unverifiable(self, tmp_path):
        _repo(tmp_path)

        class BrokenModel(ScriptedModel):
            async def generate(self, message):
                self.calls.append(message)
                return "not json at all"

        agent = JudgeAgent(*_settings(BrokenModel(
            ModelSettings(provider="test", name="test", temperature=0.0, max_tokens=10),
            ModelCredentials(api_key="test"),
            [],
        )))

        report = asyncio.run(agent.run(JudgeInput(
            root_path=str(tmp_path),
            description={**_description(), "quality_notes": []},
        )))

        assert [g.verdict for g in report.grades if g.kind == "component"] == [
            "unverifiable", "unverifiable",
        ]
        assert report.contradicted == 0

    def test_empty_claims_cost_no_calls(self, tmp_path):
        _repo(tmp_path)
        model = _model([_grade("supported", "run() is there.", ["a.py:1-2"])])
        agent = JudgeAgent(*_settings(model))

        report = asyncio.run(agent.run(JudgeInput(
            root_path=str(tmp_path),
            description=_description(
                quality_notes=[
                    {"characteristic": "modularity", "observation": "", "evidence": []},
                ],
            ),
        )))

        # One call for a.py; the undescribed component and the evidenceless
        # note are unverifiable without asking.
        assert len(model.calls) == 1
        assert [(g.subject, g.verdict) for g in report.grades] == [
            ("a.py", "supported"),
            ("b.py", "unverifiable"),
            ("note[0]: modularity", "unverifiable"),
        ]

    def test_unreadable_evidence_is_unverifiable(self, tmp_path):
        _repo(tmp_path)
        model = _model([])
        agent = JudgeAgent(*_settings(model))

        report = asyncio.run(agent.run(JudgeInput(
            root_path=str(tmp_path),
            description={
                **_description(),
                "components": [
                    {"path": "ghost.py", "responsibility": "Does things."},
                ],
                "quality_notes": [],
            },
        )))

        assert len(model.calls) == 0
        assert [(g.subject, g.verdict) for g in report.grades] == [
            ("ghost.py", "unverifiable"),
        ]

    def test_missing_root_is_a_bad_request(self, tmp_path):
        model = _model([])
        agent = JudgeAgent(*_settings(model))

        with pytest.raises(FileNotFoundError):
            asyncio.run(agent.run(JudgeInput(
                root_path=str(tmp_path / "ghost"),
                description=_description(),
            )))


class TestSameModel:
    def test_judge_reuses_the_architect_model_instance(self):
        model = _model([])
        agent = JudgeAgent(*_settings(model))

        assert agent.model is model

    def test_judge_borrows_architect_model_from_service(self):
        from server.api.schemas import ExecutionConfig
        from server.app.execution_service import (
            AgentExecutionService,
            build_default_registry,
        )

        service = AgentExecutionService(registry=build_default_registry())
        architect, _ = service.build_agent("architect", ExecutionConfig())
        judge = JudgeAgent(
            AgentSettings(agent_id="judge", timeout_seconds=120),
            architect.model,
        )

        assert judge.model is architect.model
