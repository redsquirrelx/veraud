"""TypeScript/JavaScript symbols come from tree-sitter, never raising.

Covers the spike contract: top-level declarations plus methods of top-level
classes, mirroring the Python extractor's scope. No model or network involved.
"""

from server.services.repo_map.extractors import (
    TypeScriptSymbolExtractor,
    build_default_extractors,
)


def _triples(source):
    return [(symbol.kind, symbol.name, symbol.line) for symbol in TypeScriptSymbolExtractor().extract(source)]


class TestTypeScriptSymbols:
    def test_registers_both_languages(self):
        extractors = build_default_extractors()

        assert set(extractors) >= {"python", "typescript", "javascript"}

    def test_extracts_declarations(self):
        source = (
            "export class Foo { bar(x) { return x; } }\n"
            "interface Props { a: string }\n"
            "function add(a, b) { return a + b; }\n"
        )

        assert _triples(source) == [
            ("class", "Foo", 1),
            ("method", "bar", 1),
            ("interface", "Props", 2),
            ("function", "add", 3),
        ]

    def test_nested_definitions_are_skipped(self):
        source = "function outer() { function inner() { return 1; } return inner(); }\n"

        assert _triples(source) == [("function", "outer", 1)]

    def test_garbage_and_empty_yield_nothing(self):
        assert TypeScriptSymbolExtractor().extract("not valid ((((") == []
        assert TypeScriptSymbolExtractor().extract("") == []
