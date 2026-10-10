"""Phase 4 without a model: notes are validated, risks have a floor.

A failing model stands in for unreachable answers. Cycles and deviations
still surface as risks because they are derived, not generated.
"""

import asyncio

from server.agents.architect.agent import (
    ArchitectureAgent,
    _read_quality_notes,
    _read_risks,
    _risks_floor,
)
from server.agents.architect.schemas import ArchitectInput
from server.agents.models.base import Model
from server.config.schemas import AgentSettings, ModelCredentials, ModelSettings

KNOWN = {"a.py", "b.py"}


class FailingModel(Model):
    async def generate(self, message):
        raise RuntimeError("no model in tests")


def _settings():
    return (
        AgentSettings(agent_id="architect", timeout_seconds=180),
        FailingModel(
            ModelSettings(provider="test", name="test", temperature=0.0, max_tokens=10),
            ModelCredentials(api_key="test"),
        ),
    )


class TestRisksFloor:
    def test_deviations_and_cycles_become_risks(self):
        state = {
            "frame": {"deviations": [
                {"observation": "Handlers skip the port.", "evidence": ["a.py"]},
                {"observation": "", "evidence": ["a.py"]},
            ]},
            "cycles": [["b.py", "a.py"]],
        }

        assert _risks_floor(state) == [
            "Handlers skip the port. (a.py)",
            "Circular imports: a.py ↔ b.py",
        ]

    def test_single_file_groups_are_not_cycles(self):
        assert _risks_floor({"frame": {}, "cycles": [["a.py"]]}) == []

    def test_empty_without_signal(self):
        assert _risks_floor({"frame": {}, "cycles": []}) == []


class TestReadQualityNotes:
    def test_keeps_valid_notes_with_existing_evidence(self):
        answer = {"quality_notes": [
            {"characteristic": "Modularity", "observation": "One job per module.", "evidence": ["a.py"]},
        ]}

        assert _read_quality_notes(answer, KNOWN) == [
            {"characteristic": "modularity", "observation": "One job per module.", "evidence": ["a.py"]}
        ]

    def test_drops_off_vocab_empty_and_unevidenced_notes(self):
        answer = {"quality_notes": [
            {"characteristic": "security", "observation": "Useseval.", "evidence": ["a.py"]},
            {"characteristic": "modularity", "observation": "  ", "evidence": ["a.py"]},
            {"characteristic": "modularity", "observation": "No proof.", "evidence": ["ghost.py"]},
            "not-a-note",
        ]}

        assert _read_quality_notes(answer, KNOWN) == []

    def test_missing_notes_is_empty(self):
        assert _read_quality_notes({}, KNOWN) == []


class TestReadRisks:
    def test_keeps_non_empty_strings_capped(self):
        answer = {"risks": ["  Real risk.  ", "", 42, None]}

        assert _read_risks(answer) == ["Real risk."]

    def test_missing_risks_is_empty(self):
        assert _read_risks({}) == []


class TestOfflinePhase4:
    def test_cycle_surfaces_as_risk_without_a_model(self, tmp_path):
        (tmp_path / "a.py").write_text("from b import y\n\nx = y\n")
        (tmp_path / "b.py").write_text("from a import x\n\ny = x\n")

        agent = ArchitectureAgent(*_settings())
        description = asyncio.run(_run(agent, str(tmp_path)))

        assert description.cycles == [["a.py", "b.py"]]
        assert description.risks == ["Circular imports: a.py ↔ b.py"]
        assert description.data_flow == ""
        assert description.quality_notes == []
        assert description.confidence == "low"


async def _run(agent, root_path):
    return await agent.run(ArchitectInput(
        root_path=root_path,
        analysis={
            "kind": "script",
            "summary": "t",
            "primary_language": "python",
            "entrypoints": [],
            "key_components": [],
            "confidence": "low",
            "files_read": 0,
            "read_rounds": 0,
            "hypothesis_confirmed": False,
        },
    ))
