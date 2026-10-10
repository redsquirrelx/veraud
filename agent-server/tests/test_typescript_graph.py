"""TypeScript/JavaScript imports resolve like the code would.

Extractor cases mirror real syntax; the resolver cases mirror the bundler:
relative paths with extensions and index files, bare names to third-party.
"""


from server.services.dependency_graph.extractors import TypeScriptImportExtractor
from server.services.dependency_graph.resolver import TypeScriptResolver
from server.services.dependency_graph.schemas import DependencyGraphInput
from server.services.dependency_graph.service import DependencyGraphService


def _records(source):
    return [
        (record.kind, record.specifier, record.line)
        for record in TypeScriptImportExtractor().extract(source)
    ]


class TestTypeScriptImports:
    def test_static_forms(self):
        source = (
            "import def1, {a, b} from './mod';\n"
            "import * as ns from '../up';\n"
            "import 'side-effect';\n"
            "import type { T } from './types';\n"
            "export { x } from './x';\n"
            "export const y = 1;\n"
            "const r = require('./req');\n"
            "const m = await import('./dyn');\n"
            "import 'node:fs';\n"
        )

        assert _records(source) == [
            ("from_import", "./mod", 1),
            ("from_import", "../up", 2),
            ("import", "side-effect", 3),
            ("type_only", "./types", 4),
            ("reexport", "./x", 5),
            ("import", "./req", 7),
            ("import", "./dyn", 8),
            ("import", "node:fs", 9),
        ]

    def test_dynamic_calls_are_dynamic(self):
        source = "const d = require(name);\nconst t = await import(`./${name}`);\n"

        assert _records(source) == [
            ("dynamic", "<dynamic>", 1),
            ("dynamic", "<dynamic>", 2),
        ]

    def test_body_strings_are_not_modules(self):
        source = "export function taskOutput(result: TaskResult): string {\n  return result.output ?? '';\n}\n"

        assert _records(source) == []

    def test_garbage_and_empty_yield_nothing(self):
        assert TypeScriptImportExtractor().extract("not valid ((((") == []
        assert TypeScriptImportExtractor().extract("") == []


def _resolver(tmp_path, manifest=True):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.ts").write_text("x\n")
    (tmp_path / "app" / "util.ts").write_text("y\n")
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "index.ts").write_text("z\n")
    if manifest:
        (tmp_path / "package.json").write_text('{"dependencies": {"react": "^19.0.0"}}')

    files = {
        "app/main.ts",
        "app/util.ts",
        "lib/index.ts",
        "app/other.jsx",
        "plain.js",
    }
    return TypeScriptResolver(tmp_path, files)


def _record(specifier, kind="from_import", reason=None):
    from server.services.dependency_graph.extractors import ImportRecord

    return ImportRecord(specifier=specifier, level=0, kind=kind, is_from=True, line=1, reason=reason)


class TestTypeScriptResolver:
    def test_relative_file_and_index(self, tmp_path):
        resolver = _resolver(tmp_path)

        assert resolver.resolve(_record("./util"), "app/main.ts").target == "app/util.ts"
        assert resolver.resolve(_record("../lib"), "app/main.ts").target == "lib/index.ts"
        assert resolver.resolve(_record("./missing"), "app/main.ts").reason == "not_found"

    def test_escaping_the_root(self, tmp_path):
        resolver = _resolver(tmp_path)

        assert resolver.resolve(_record("../../evil"), "app/main.ts").reason == "too_many_dots"

    def test_bare_names(self, tmp_path):
        resolver = _resolver(tmp_path)

        assert resolver.resolve(_record("react"), "app/main.ts").reason == "external"
        assert resolver.resolve(_record("fs"), "app/main.ts").reason == "external"
        assert resolver.resolve(_record("node:path"), "app/main.ts").reason == "external"
        assert resolver.resolve(_record("left-pad"), "app/main.ts").reason == "not_found"

    def test_no_manifest_means_everything_bare_is_external(self, tmp_path):
        resolver = _resolver(tmp_path, manifest=False)

        assert resolver.resolve(_record("left-pad"), "app/main.ts").reason == "external"

    def test_dynamic_passes_through(self, tmp_path):
        resolver = _resolver(tmp_path)

        record = _record("<dynamic>", kind="dynamic", reason="dynamic_expr")
        assert resolver.resolve(record, "app/main.ts").reason == "dynamic_expr"


class TestMixedService:
    def test_typescript_edges_join_the_graph(self, tmp_path):
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "__init__.py").write_text("")
        (tmp_path / "pkg" / "core.py").write_text("VALUE = 1\n")
        (tmp_path / "app.ts").write_text("import { run } from './runner';\n")
        (tmp_path / "runner.ts").write_text("export function run() {}\n")

        import asyncio

        service = DependencyGraphService()
        output = asyncio.run(service.create(DependencyGraphInput(root_path=str(tmp_path))))

        internal = {(edge.source, edge.target) for edge in output.edges if edge.resolved}
        assert ("app.ts", "runner.ts") in internal
        assert output.stats.internal >= 1
        assert output.stats.files == 4
