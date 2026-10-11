"""The architect groups files into containers and diagrams them.

Grouping is model judgment over what was read; arrows, interfaces and
membership checks are derived. Invented members are dropped, empty
containers are dropped whole, and the assembler is pure and deterministic.
"""

import asyncio
import json

from server.agents.architect.agent import ArchitectureAgent, _read_externals
from server.agents.architect.diagrams import (
    MAX_DIAGRAM_EDGES,
    MAX_DIAGRAM_NODES,
    build_diagrams,
    sanitize_id,
)
from server.agents.architect.schemas import ArchitectInput
from server.agents.models.base import Model
from server.config.schemas import AgentSettings, ModelCredentials, ModelSettings

FIRST_LINES = {
    "Decide what this repository TRIES to be": "frame",
    "Decide which files to read": "survey",
    "Describe what each key component": "characterize",
    "Group the repository": "group",
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


def _frame():
    return {
        "style": "layered",
        "intended_style": "layered",
        "reasoning": "r",
        "intended_reasoning": "ir",
        "would_confirm": ["main.py"],
        "deviations": [],
    }


def _base_answers(**overrides):
    answers = {
        "frame": [_frame()],
        "survey": [{"paths": ["main.py", "pkg/core.py"]}],
        "characterize": [{"components": [
            {"path": "main.py", "responsibility": "Starts it."},
            {"path": "pkg/core.py", "responsibility": "Runs it."},
        ]}],
        "group": [{"containers": [
            {"name": "cli", "responsibility": "Entry point.", "files": ["main.py", "ghost.py"]},
            {"name": "core", "responsibility": "Logic.", "files": ["pkg/core.py"]},
            {"name": "empty", "responsibility": "Nothing.", "files": ["ghost.py"]},
        ]}],
        "connect": [{"data_flow": "Main reaches core."}],
        "map25010": [{"quality_notes": [], "risks": []}],
    }
    answers.update(overrides)
    return answers


class TestGrouping:
    def test_containers_keep_real_members_only(self, tmp_path):
        _repo(tmp_path)
        agent = _agent(_base_answers())

        description = asyncio.run(agent.run(ArchitectInput(
            root_path=str(tmp_path), analysis=_analysis(),
        )))

        assert [(c.name, c.files) for c in description.containers] == [
            ("cli", ["main.py"]),
            ("core", ["pkg/core.py"]),
        ]
        assert "group" in agent.model.calls

    def test_no_group_call_without_key_components(self):
        # Any model call raises: the guard must return before asking.
        agent = _agent({})
        state = {
            "derived_key_components": [],
            "facts": "",
            "directory_profiles": "",
            "components": [],
            "excerpts": "",
            "known_files": set(),
        }

        assert asyncio.run(agent._group(state))["containers"] == []

    def test_max_containers_is_respected(self, tmp_path):
        _repo(tmp_path)
        many = [
            {"name": f"c{n}", "responsibility": "x", "files": ["main.py"]}
            for n in range(7)
        ]
        agent = _agent(_base_answers(group=[{"containers": many}]))

        description = asyncio.run(agent.run(ArchitectInput(
            root_path=str(tmp_path), analysis=_analysis(),
        )))

        assert len(description.containers) == 5


class TestDiagrams:
    def _payload(self):
        return {
            "system_name": "shop",
            "edges": [{"source": "main.py", "target": "pkg/core.py"}],
            "file_symbols": {"main.py": [], "pkg/core.py": ["run"]},
            "containers": [
                {"name": "cli", "responsibility": "Entry.", "files": ["main.py"]},
                {"name": "core", "responsibility": "Logic.", "files": ["pkg/core.py"]},
            ],
            "externals": [],
            "components": [
                {"path": "main.py", "responsibility": "Starts it."},
                {"path": "pkg/core.py", "responsibility": "Runs it."},
            ],
            "entrypoints": ["main.py"],
            "cycles": [["main.py", "pkg/core.py"]],
            "third_party": ["requests"],
        }

    def test_containers_diagram_aggregates_real_imports(self):
        result = build_diagrams(**self._payload())

        assert "flowchart LR" in result["containers"]
        assert "-->|uses|" in result["containers"]
        assert "requests" in result["containers"]
        assert "stroke-dasharray" in result["containers"]
        assert result["truncated"] is False

    def test_components_diagram_marks_cycles_entries_and_symbols(self):
        result = build_diagrams(**self._payload())

        assert "[/\"main.py\"/]" in result["components"]
        assert "[[\"pkg/core.py" in result["components"]
        assert "+run" in result["components"]
        assert "-->|imports|" in result["components"]
        assert "stroke:#b91c1c" in result["components"]

    def test_sanitize_is_stable_and_unique(self):
        taken: set[str] = set()

        assert sanitize_id("src/app.ts", taken) == "src_app_ts"
        assert sanitize_id("src/app.ts", taken) == "src_app_ts_2"
        assert sanitize_id("!!!", taken) == "node"

    def test_empty_inputs_yield_empty_strings(self):
        result = build_diagrams(
            system_name="shop", edges=[], file_symbols={}, containers=[],
            externals=[], components=[], entrypoints=[], cycles=[], third_party=[],
        )

        assert result == {"containers": "", "components": "", "truncated": False}

    def test_output_is_deterministic(self):
        assert build_diagrams(**self._payload()) == build_diagrams(**self._payload())

    def test_full_run_diagrams(self, tmp_path):
        _repo(tmp_path)
        agent = _agent(_base_answers())

        description = asyncio.run(agent.run(ArchitectInput(
            root_path=str(tmp_path), analysis=_analysis(),
        )))

        assert "flowchart LR" in description.diagram_containers
        assert "flowchart LR" in description.diagram_components
        assert "ghost.py" not in description.diagram_containers
        assert "ghost.py" not in description.diagram_components

    def test_full_run_maps_external_groups(self, tmp_path):
        tmp_path.joinpath("main.py").write_text("import requests\n\nprint(requests.get('http://x'))\n")
        agent = _agent({
            "frame": [{
                "style": "unknown", "intended_style": "unknown", "reasoning": "r",
                "intended_reasoning": "ir", "would_confirm": ["main.py"], "deviations": [],
            }],
            "survey": [{"paths": ["main.py"]}],
            "characterize": [{"components": [{"path": "main.py", "responsibility": "Calls out."}]}],
            "group": [{"containers": [
                {"name": "cli", "responsibility": "Entry.", "files": ["main.py"]},
            ], "externals": [
                {"name": "http", "members": ["requests"]},
                {"name": "bogus", "members": ["nope"]},
            ]}],
            "connect": [{"data_flow": "Main calls out."}],
            "map25010": [{"quality_notes": [], "risks": []}],
        })

        description = asyncio.run(agent.run(ArchitectInput(
            root_path=str(tmp_path), analysis=_analysis(),
        )))

        assert [(group.name, group.members) for group in description.externals] == [
            ("http", ["requests"]),
        ]
        assert "http" in description.diagram_containers
        assert "nope" not in description.diagram_containers
        # The arrow is derived: main.py really imports requests.
        assert "-->|uses|" in description.diagram_containers


class TestReadExternals:
    def test_keeps_real_members_and_drops_the_rest(self):
        answer = {"externals": [
            {"name": "persistence", "members": ["psycopg", "ghost"]},
            {"name": "empty", "members": ["ghost"]},
            {"name": "  ", "members": ["psycopg"]},
            "not-a-group",
        ]}

        assert _read_externals(answer, ["psycopg", "requests"]) == [
            {"name": "persistence", "members": ["psycopg"]},
        ]

    def test_missing_externals_is_empty(self):
        assert _read_externals({}, ["requests"]) == []


class TestExternalEdges:
    def _payload(self):
        return {
            "system_name": "shop",
            "edges": [
                {"source": "main.py", "target": "pkg/core.py", "specifier": "pkg.core", "resolved": True},
                {"source": "main.py", "target": None, "specifier": "requests.get", "resolved": False},
                {"source": "other.py", "target": None, "specifier": "psycopg", "resolved": False},
            ],
            "file_symbols": {},
            "containers": [
                {"name": "cli", "responsibility": "Entry.", "files": ["main.py"]},
            ],
            "externals": [
                {"name": "http", "members": ["requests"]},
            ],
            "components": [],
            "entrypoints": [],
            "cycles": [],
            "third_party": ["requests", "psycopg"],
        }

    def test_group_arrows_follow_real_imports(self):
        result = build_diagrams(**self._payload())

        # cli imports requests (used by a member) but nothing imports psycopg
        # from inside a container: one derived arrow, no invented ones.
        assert result["containers"].count("-->|uses|") == 1
        assert "http" in result["containers"]

    def test_fallback_single_node_without_groups(self):
        payload = self._payload()
        payload["externals"] = []

        result = build_diagrams(**payload)

        assert "third-party" in result["containers"]
        assert result["containers"].count("([") == 1
        assert "ungrouped" in result["containers"]
        assert "container_cli -->|uses| ext_third_party" in result["containers"]

    def test_external_roles_are_outside_system_and_show_members(self):
        chart = build_diagrams(**self._payload())["containers"]

        inside, outside = chart.split("    end\n", 1)
        assert 'subgraph system_boundary["shop"]' in inside
        assert 'container_cli[["cli"]]' in inside
        assert "ext_http" not in inside
        assert 'ext_http(["External dependencies<br/>http<br/>requests"])' in outside
        assert "stroke-dasharray" in outside

    def test_partial_groups_preserve_remaining_dependencies(self):
        payload = self._payload()
        payload["edges"].append({
            "source": "main.py", "target": None,
            "specifier": "psycopg", "resolved": False,
        })
        chart = build_diagrams(**payload)["containers"]

        assert "container_cli -->|uses| ext_http" in chart
        assert "container_cli -->|uses| ext_third_party" in chart
        assert "third-party<br/>psycopg" in chart

    def test_unknown_group_members_never_render(self):
        payload = self._payload()
        payload["externals"].append({"name": "imaginary", "members": ["ghost"]})
        chart = build_diagrams(**payload)["containers"]

        assert "imaginary" not in chart
        assert "ghost" not in chart

    def test_shuffled_and_duplicate_inputs_are_stable(self):
        payload = self._payload()
        payload["externals"].append({"name": "another role", "members": ["requests"]})
        first = build_diagrams(**payload)
        payload["edges"] = list(reversed(payload["edges"])) * 2
        payload["externals"].reverse()

        assert build_diagrams(**payload) == first

    def test_external_labels_bound_members_and_length(self):
        payload = self._payload()
        payload["third_party"] = [f"package_{index:02d}" for index in range(12)]
        payload["externals"] = [{"name": "x" * 200, "members": payload["third_party"]}]
        chart = build_diagrams(**payload)["containers"]

        assert "+4 more" in chart
        assert "<br/>" + "x" * 80 + "<br/>" in chart
        assert "package_08" not in chart


class TestDiagramLimits:
    def _payload(self, count):
        paths = [f"file_{index:02d}.py" for index in range(count)]
        return {
            "system_name": "large",
            "edges": [
                {"source": source, "target": target, "resolved": True}
                for source in paths for target in paths if source != target
            ],
            "file_symbols": {},
            "containers": [{"name": path, "files": [path]} for path in paths],
            "externals": [],
            "components": [{"path": path} for path in paths],
            "entrypoints": [], "cycles": [], "third_party": [],
        }

    def test_nodes_and_edges_are_capped_in_both_diagrams(self):
        result = build_diagrams(**self._payload(MAX_DIAGRAM_NODES + 5))

        assert result["truncated"] is True
        for name in ("containers", "components"):
            chart = result[name]
            assert chart.count('[["') == MAX_DIAGRAM_NODES
            assert chart.count(" -->|") == MAX_DIAGRAM_EDGES
            assert "%% truncated:" in chart

    def test_external_nodes_share_the_node_budget(self):
        payload = self._payload(MAX_DIAGRAM_NODES)
        payload["third_party"] = ["requests"]
        payload["externals"] = [{"name": "http", "members": ["requests"]}]
        payload["edges"] = [{
            "source": "file_00.py", "target": None,
            "specifier": "requests", "resolved": False,
        }]
        chart = build_diagrams(**payload)["containers"]

        assert chart.count('[["') + chart.count('(["') == MAX_DIAGRAM_NODES
        assert "ext_http" in chart
        assert "%% truncated:" in chart
