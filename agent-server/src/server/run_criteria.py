"""DEV-ONLY evidence run: do the representations meet the four criteria?

    uv run --no-sync python -m server.run_criteria
    uv run --no-sync python -m server.run_criteria ../appdata/workspace/123-owner-repo

With no root it builds a small Python fixture in a temp directory and checks
each criterion against it, including reading the source back to confirm every
edge points at the line that declares it.

With a root it reports the same criteria against a real repository, which is
where the language ceiling shows up: files are always mapped, but symbols and
edges only exist for languages an extractor handles.
"""

import argparse
import asyncio
import json
import logging
import sys
import tempfile
from pathlib import Path

from pydantic import ValidationError

if __package__ in (None, ""):
    # Launched by path: no package context, so make `server` importable.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.services.collection.schemas import Collection, CollectionInput
from server.services.collection.service import CollectionService

# A small Python project: a package with a subpackage, re-exports, a test, a
# CLI entry point, and third-party imports. Enough to exercise every code path.
FIXTURE: dict[str, str] = {
    "pyproject.toml": '[project]\nname = "shop"\nversion = "0.1.0"\n',
    "README.md": "# Shop\n",
    "shop/__init__.py": "from shop.api import serve\nfrom shop.models import Cart\n",
    "shop/__main__.py": "from shop.cli import main\nmain()\n",
    "shop/models.py": (
        "import os\n"
        "from dataclasses import dataclass\n"
        "\n"
        "@dataclass\n"
        "class Cart:\n"
        "    items: list\n"
        "\n"
        "def total(cart: Cart, tax: float = 0.0) -> float:\n"
        "    return 0.0\n"
    ),
    "shop/api.py": (
        "from typing import Annotated\n"
        "from shop.models import Cart, total\n"
        "\n"
        "class Server:\n"
        "    def __init__(self, host: str, port: int = 8080):\n"
        "        pass\n"
        "    def handle(self, cart: Cart) -> float:\n"
        "        return total(cart)\n"
    ),
    "shop/storage/__init__.py": "from shop.storage.db import Database\n",
    "shop/storage/db.py": (
        "import json\n"
        "from shop.models import Cart\n"
        "\n"
        "class Database:\n"
        "    def save(self, cart: Cart) -> None:\n"
        "        pass\n"
    ),
    "shop/cli.py": (
        "import typer\n"
        "from shop.api import Server\n"
        "\n"
        "def main() -> None:\n"
        "    pass\n"
    ),
    "tests/test_models.py": "from shop.models import Cart\n",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_criteria",
        description="Evidence for the four representation criteria.",
    )
    parser.add_argument(
        "root",
        nargs="?",
        help="Repository to check. Omit to use the built-in Python fixture.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=500,
        help="Cap per representation (default: 500)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the serialized Collection instead of the evidence report",
    )
    parser.add_argument(
        "--save",
        metavar="PATH",
        help="Write the serialized Collection to PATH",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Silence logging",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.quiet:
        logging.disable(logging.CRITICAL)

    temporary: tempfile.TemporaryDirectory | None = None

    if args.root is None:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        for relative, text in FIXTURE.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        print("Root: built-in Python fixture")
    else:
        root = Path(args.root).expanduser().resolve()
        print(f"Root: {root}")

    try:
        payload = CollectionInput(root_path=str(root), max_files=args.max_files)
        collection = asyncio.run(CollectionService().collect(payload))
    except ValidationError as error:
        print(f"error: invalid arguments\n{error}", file=sys.stderr)
        return 2
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.save:
        Path(args.save).write_text(collection.model_dump_json(indent=2), encoding="utf-8")
        print(f"Saved: {args.save}")

    if args.json:
        print(collection.model_dump_json(indent=2))
        return 0

    report(collection, root, cross_check=args.root is None)

    if temporary is not None:
        temporary.cleanup()

    return 0


def report(collection: Collection, root: Path, cross_check: bool) -> None:
    """Print one section per criterion, each with the evidence behind it."""
    repo_map = collection.repo_map
    graph = collection.dependency_graph

    _criterion_1(collection, repo_map, graph)
    _criterion_2(repo_map)
    _criterion_3(graph, root, cross_check)
    _criterion_4(collection, graph)


def _criterion_1(collection: Collection, repo_map: dict, graph: dict) -> None:
    print("\n=== 1. Processes a repository into a structured representation ===")
    print(f"  root           : {collection.root}")
    print(f"  top-level keys : {sorted(collection.model_dump())}")
    print(f"  files mapped   : {len(repo_map['files'])}")
    print(f"  edges mapped   : {len(graph['edges'])}")

    sample = repo_map["files"][:3]
    print("  one file record:")
    for item in sample:
        print(f"    {item}")


def _criterion_2(repo_map: dict) -> None:
    print("\n=== 2. Identifiable modules and signatures ===")
    files = repo_map["files"]

    python_files = [f for f in files if f["language"] == "python"]
    with_symbols = [f for f in files if f["symbols"]]

    print(f"  files mapped        : {len(files)}")
    print(f"  modules (.py)       : {len(python_files)}")
    print(f"  modules with symbols: {len(with_symbols)}")

    languages: dict[str, int] = {}
    for item in files:
        languages[item["language"]] = languages.get(item["language"], 0) + 1
    print(f"  languages           : {dict(sorted(languages.items()))}")

    total = sum(len(f["symbols"]) for f in files)
    print(f"  total symbols       : {total}")

    if not with_symbols:
        print("  !! No symbols extracted: this repository has no language")
        print("     with a symbol extractor. Criterion 2 not met here.")
        return

    print("  signatures:")
    for item in files:
        for symbol in item["symbols"]:
            label = symbol["signature"] or f"{symbol['kind']} {symbol['name']}"
            print(f"    {item['path']:<26} L{symbol['line']:<4} {label}")

    kinds = {s["kind"] for f in files for s in f["symbols"]}
    print(f"  symbol kinds seen   : {sorted(kinds)}")


def _criterion_3(graph: dict, root: Path, cross_check: bool) -> None:
    print("\n=== 3. Identifiable dependencies between processed elements ===")
    edges = graph["edges"]
    internal = [e for e in edges if e["resolved"]]

    print(f"  internal edges : {len(internal)}")
    print(f"  external       : {graph['stats']['external']}")
    print(f"  unresolved     : {len(graph['stats']['unresolved'])}")
    print(f"  dynamic        : {graph['stats']['dynamic']}")
    print(f"  cycles         : {graph['stats']['cycles']}")

    if not internal:
        print("  !! No internal edges: no language with an import extractor")
        print("     resolved to a file. Criterion 3 not met here.")
        return

    print("  internal edges:")
    for edge in internal:
        print(
            f"    {edge['source']:<26} -> {edge['target']:<26}"
            f" [{edge['kind']}] L{edge['line']}"
        )

    print("  non-internal imports:")
    for edge in edges:
        if not edge["resolved"]:
            print(
                f"    {edge['source']:<26} {edge['specifier']:<16}"
                f" reason={edge['reason']:<10} kind={edge['kind']}"
            )

    if cross_check:
        _cross_check(internal, root)


def _cross_check(internal: list[dict], root: Path) -> None:
    """Confirm each edge points at the line that declares it."""
    print("  cross-check against source (line N must mention the target):")
    mismatches = 0

    for edge in internal:
        try:
            lines = (root / edge["source"]).read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
            declared = lines[edge["line"] - 1].strip()
        except (OSError, IndexError):
            print(f"    {edge['source']:<26} L{edge['line']:<4} UNREADABLE")
            mismatches += 1
            continue

        stem = edge["target"].rsplit("/", 1)[-1].removesuffix(".py")
        bare = edge["specifier"].lstrip(".")

        if stem in declared or bare in declared:
            print(f"    {edge['source']:<26} L{edge['line']:<4} OK   {declared[:46]}")
        else:
            print(f"    {edge['source']:<26} L{edge['line']:<4} MISS {declared[:46]}")
            mismatches += 1

    verdict = "all edges point at the declaring line" if not mismatches else f"{mismatches} mismatch"
    print(f"  cross-check result: {verdict}")


def _criterion_4(collection: Collection, graph: dict) -> None:
    print("\n=== 4. Structured and serializable for other components ===")

    raw = collection.model_dump_json(indent=2)
    parsed = json.loads(raw)
    again = json.dumps(parsed, indent=2, ensure_ascii=False)

    print(f"  model_dump_json chars : {len(raw)}")
    print(f"  round-trip identical  : {raw == again}")
    print(f"  root keys             : {sorted(parsed)}")
    print(f"  types                 : repo_map={type(parsed['repo_map']).__name__}, "
          f"dependency_graph={type(parsed['dependency_graph']).__name__}")

    json_only = all(
        isinstance(value, (str, int, float, bool, list, dict, type(None)))
        for value in parsed.values()
    )
    print(f"  plain JSON types only : {json_only}")
    print(f"  sizes                 : repo_map={len(json.dumps(parsed['repo_map']))} chars, "
          f"dependency_graph={len(json.dumps(parsed['dependency_graph']))} chars")

    print("  consumable from the serialized payload alone:")
    # Pick a file that actually carries symbols and edges, otherwise the proof
    # is about an empty record.
    candidates = [f for f in parsed["repo_map"]["files"] if f["symbols"]]
    if not candidates:
        print("    no file in this payload has symbols to read back")
        print("  ^ the repository has no language with a symbol extractor")
        return

    first = candidates[0]
    print(f"    file          : {first['path']} ({first['language']}, {first['lines']} L)")

    for symbol in first["symbols"]:
        label = symbol["signature"] or f"{symbol['kind']} {symbol['name']}"
        print(f"      L{symbol['line']:<4} {label}")

    source = first["path"]
    deps = [
        edge["target"] for edge in parsed["dependency_graph"]["edges"]
        if edge["source"] == source and edge["resolved"]
    ]
    print(f"    depends on    : {deps or '[] (no internal edges from this file)'}")


if __name__ == "__main__":
    raise SystemExit(main())