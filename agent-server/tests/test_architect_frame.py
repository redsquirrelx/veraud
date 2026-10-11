"""The frame step keeps what the model proves and drops the rest.

Deviations arrive as free-form JSON: invented paths must not survive, every
entry must name its line intervals, and a deviation without an observation
says nothing. No model or network involved.
"""

from server.agents.architect.agent import _read_deviations

KNOWN = {"app/handler.py", "app/db.py", "app/main.py"}


class TestReadDeviations:
    def test_keeps_observation_with_ranged_evidence(self):
        answer = {
            "deviations": [
                {"observation": "Handlers import the SQL adapter directly.", "evidence": ["app/handler.py:10-20"]},
            ]
        }

        assert _read_deviations(answer, KNOWN) == [
            {"observation": "Handlers import the SQL adapter directly.", "evidence": ["app/handler.py:10-20"]}
        ]

    def test_drops_bare_paths_but_keeps_the_observation(self):
        answer = {
            "deviations": [
                {"observation": "Handlers import the SQL adapter directly.", "evidence": ["app/handler.py"]},
            ]
        }

        assert _read_deviations(answer, KNOWN) == [
            {"observation": "Handlers import the SQL adapter directly.", "evidence": []}
        ]

    def test_drops_invented_paths_but_keeps_the_observation(self):
        answer = {
            "deviations": [
                {"observation": "No ports directory anywhere.", "evidence": ["ports/missing.py"]},
            ]
        }

        assert _read_deviations(answer, KNOWN) == [
            {"observation": "No ports directory anywhere.", "evidence": []}
        ]

    def test_drops_deviations_without_observation(self):
        answer = {"deviations": [{"observation": "  ", "evidence": ["app/main.py"]}, "nope"]}

        assert _read_deviations(answer, KNOWN) == []

    def test_missing_or_malformed_deviations_is_empty(self):
        assert _read_deviations({}, KNOWN) == []
        assert _read_deviations({"deviations": "hexagonal"}, KNOWN) == []
