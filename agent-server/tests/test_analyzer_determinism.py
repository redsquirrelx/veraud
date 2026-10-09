"""The structural description fields are derived, never model-chosen.

These tests pin the determinism contract: same collection in, same
key_components / entrypoints / primary_language out, whatever the model
sent back. They run without any model or network.
"""

from server.agents.analyzer import facts, parsing


def _file(path, language="python", lines=10, symbols=None):
    return {
        "path": path,
        "language": language,
        "lines": lines,
        "symbols": symbols or [],
    }


def _edge(source, target):
    return {"source": source, "target": target, "resolved": True}


class TestPrimaryLanguage:
    def test_dominant_language_by_lines(self):
        files = [
            _file("a.py", "python", 100),
            _file("b.ts", "typescript", 900),
            _file("c.ts", "typescript", 50),
        ]

        assert facts.derived_primary_language(files) == "typescript"

    def test_ties_break_alphabetically(self):
        files = [_file("a.py", "python", 100), _file("b.ts", "typescript", 100)]

        assert facts.derived_primary_language(files) == "python"

    def test_empty_or_unmeasured_is_unknown(self):
        assert facts.derived_primary_language([]) == "unknown"
        assert facts.derived_primary_language([_file("a.py", "python", 0)]) == "unknown"


class TestKeyComponents:
    def test_top_hubs_by_degree(self):
        edges = [
            _edge("app/main.py", "app/core.py"),
            _edge("app/cli.py", "app/core.py"),
            _edge("app/core.py", "app/util.py"),
        ]
        files = [_file("app/main.py"), _file("app/cli.py"), _file("app/core.py"), _file("app/util.py")]

        assert facts.derived_key_components(edges, files) == [
            "app/core.py",
            "app/cli.py",
            "app/main.py",
            "app/util.py",
        ]

    def test_ties_break_alphabetically(self):
        edges = [_edge("b.py", "a.py"), _edge("c.py", "a.py")]

        assert facts.derived_key_components(edges, [_file("a.py"), _file("b.py"), _file("c.py")])[1:] == [
            "b.py",
            "c.py",
        ]

    def test_limit_is_honoured(self):
        edges = [_edge(f"m{i}.py", "hub.py") for i in range(20)]

        assert len(facts.derived_key_components(edges, [], limit=8)) == 8

    def test_empty_graph_falls_back_to_largest_files(self):
        files = [_file("small.py", lines=10), _file("big.py", lines=500), _file("mid.py", lines=100)]

        assert facts.derived_key_components([], files) == ["big.py", "mid.py", "small.py"]

    def test_fallback_ties_break_alphabetically(self):
        files = [_file("b.py", lines=50), _file("a.py", lines=50)]

        assert facts.derived_key_components([], files) == ["a.py", "b.py"]


class TestDerivedEntrypoints:
    def test_union_of_candidates_and_packages_sorted(self):
        files = [
            _file("src/app/cli.py", lines=5),
            _file("src/mypkg/__init__.py", lines=200, symbols=[{"name": "x"}]),
            _file("src/other.py", lines=5),
        ]

        assert facts.derived_entrypoints(files) == [
            "src/app/cli.py",
            "src/mypkg",
            "src/mypkg/__init__.py",
        ]


class TestBuildDescription:
    def test_structural_fields_come_from_derivation_not_the_model(self):
        parsed = {
            "kind": "library",
            "summary": "A widget library.",
            "confidence": "high",
            "primary_language": "cobol",
            "entrypoints": ["src/other.py", "nope/missing.py"],
            "key_components": ["src/other.py"],
        }
        known = {"src/other.py", "app/core.py", "src/mypkg"}

        description = parsing.build_description(
            parsed,
            files_read=4,
            read_rounds=1,
            hypothesis_confirmed=True,
            known_files=known,
            key_components=["app/core.py", "stale/gone.py"],
            entrypoints=["src/mypkg", "stale/gone.py"],
            primary_language="python",
        )

        assert description.kind == "library"
        assert description.summary == "A widget library."
        assert description.confidence == "high"
        assert description.primary_language == "python"
        assert description.entrypoints == ["src/mypkg"]
        assert description.key_components == ["app/core.py"]
        assert description.files_read == 4
        assert description.read_rounds == 1
        assert description.hypothesis_confirmed is True
