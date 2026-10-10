"""Phase 3 runs without a model: every model failure has a deterministic floor.

A model that raises stands in for unreachable or unusable answers. The run
still returns a valid description with a stable component list.
"""

import asyncio

from server.agents.analyzer import facts
from server.agents.architect.agent import (
    ArchitectureAgent,
    _ordered_components,
    _survey_floor,
)
from server.agents.architect.schemas import ArchitectInput
from server.agents.models.base import Model
from server.config.schemas import AgentSettings, ModelCredentials, ModelSettings


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


def _file(path, language="python", lines=10, symbols=None):
    return {"path": path, "language": language, "lines": lines, "symbols": symbols or []}


def _symbol(name, kind="function"):
    return {"name": name, "kind": kind, "line": 1}


class TestDirectoryProfiles:
    def test_groups_by_top_level_directory(self):
        files = [
            _file("api/main.py", lines=50, symbols=[_symbol("handle", "function")]),
            _file("api/util.py", lines=30),
            _file("domain/models.py", lines=100, symbols=[_symbol("Order", "class")]),
        ]
        edges = [
            {"source": "api/main.py", "target": "api/util.py", "resolved": True},
            {"source": "api/main.py", "target": "domain/models.py", "resolved": True},
        ]

        profiles = facts.directory_profiles(files, edges)
        by_dir = {profile["directory"]: profile for profile in profiles}

        assert set(by_dir) == {"api", "domain"}
        assert by_dir["api"]["files"] == 2
        assert by_dir["api"]["lines"] == 80
        assert by_dir["api"]["languages"] == {"python": 2}
        assert by_dir["api"]["imports"] == 2
        assert by_dir["api"]["imported_by"] == 1
        assert by_dir["domain"]["imported_by"] == 1
        assert by_dir["domain"]["symbols"] == ["Order"]
        # Sorted by lines, domain first.
        assert [profile["directory"] for profile in profiles] == ["domain", "api"]

    def test_empty_repo_has_no_profiles(self):
        assert facts.directory_profiles([], []) == []


class TestSurveyFloor:
    def test_fallback_orders_evidence_entrypoints_components(self):
        state = {
            "frame": {"deviations": [{"observation": "Skipped port.", "evidence": ["api/handler.py"]}]},
            "entrypoints": ["api/main.py"],
            "derived_key_components": ["app/core.py", "api/handler.py"],
            "read_paths": [],
            "known_files": {"api/handler.py", "api/main.py", "app/core.py"},
        }

        assert _survey_floor(state) == ["api/handler.py", "api/main.py", "app/core.py"]

    def test_already_read_paths_are_skipped(self):
        state = {
            "frame": {},
            "entrypoints": ["api/main.py"],
            "derived_key_components": ["app/core.py"],
            "read_paths": ["api/main.py"],
            "known_files": {"api/main.py", "app/core.py"},
        }

        assert _survey_floor(state) == ["app/core.py"]


class TestOrderedComponents:
    def test_follows_derived_order_and_fills_gaps(self):
        described = [
            {"path": "b.py", "responsibility": "Second thing."},
            {"path": "ghost.py", "responsibility": "Invented."},
        ]

        assert _ordered_components(described, ["a.py", "b.py"]) == [
            {"path": "a.py", "responsibility": ""},
            {"path": "b.py", "responsibility": "Second thing."},
        ]


class TestOfflineRun:
    def test_full_run_without_a_model(self, tmp_path):
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "__init__.py").write_text("x = 1\n")
        (tmp_path / "pkg" / "core.py").write_text("def run():\n    return 1\n")
        (tmp_path / "main.py").write_text("from pkg.core import run\n\nrun()\n")

        agent = ArchitectureAgent(*_settings())
        description = asyncio.run(_run(agent, str(tmp_path)))

        assert description.style == "unknown"
        assert description.confidence == "low"
        # main.py -> pkg/core.py is the only edge: both degree 1, alphabetical.
        assert [component.path for component in description.components] == [
            "main.py",
            "pkg/core.py",
        ]
        assert all(component.responsibility == "" for component in description.components)

    def test_characterize_keeps_only_known_paths(self):
        agent = ArchitectureAgent(*_settings())
        state = {
            "derived_key_components": ["a.py", "b.py"],
            "excerpts": "--- a.py\nprint(1)\n",
            "known_files": {"a.py", "b.py"},
        }

        components = asyncio.run(agent._characterize(state))

        assert components == {"components": [
            {"path": "a.py", "responsibility": ""},
            {"path": "b.py", "responsibility": ""},
        ]}


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
