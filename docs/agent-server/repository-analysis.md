# In-memory repository analysis

`RepositoryAnalysisService` builds a typed, evidence-backed repository snapshot
without LLM calls, API credentials, or executing repository code. The snapshot
is built internally by the `project-architecture` pipeline definition and the
`run_project_*` CLI runners.

## Snapshot input

The default snapshot summarizes technologies, structure, dependencies, architecture
signals, entrypoints, infrastructure, testing, and extraction coverage. Snapshots
are built programmatically (see Python API below) by the `project-architecture`
pipeline definition and the `run_project_*` CLI runners over a retained checkout.

## Python API

```python
from server.services.repository_analysis import (
    RepositoryAnalysisInput,
    RepositoryAnalysisService,
    RepositoryQueryService,
)

snapshot = await RepositoryAnalysisService().analyze(
    RepositoryAnalysisInput(root_path="../appdata/workspace/199836402-thisishaykins-PyShop")
)
queries = RepositoryQueryService(snapshot)
overview = queries.get_repository_overview()
symbols = queries.find_symbols(name="Product", limit=20)
source = queries.get_symbol_source(symbols.items[0].id)
```

Synchronous callers can use `analyze_sync(...)`. Both methods also accept a
`str` or `Path`. Queries read exclusively from the snapshot, so later edits or
deletions in the working directory do not affect retrieved evidence/source.

Public query methods:

- `get_repository_overview`, `list_projects`, `list_files`
- `find_symbols`, `get_symbol_source`, `get_source_excerpt`
- `get_dependencies`, `list_relationships`
- `get_outgoing_relationships`, `get_incoming_relationships`
- `list_entrypoints`, `list_architecture_signals`
- `get_infrastructure`, `get_testing_configuration`
- `search_repository_text`, `get_evidence`

## Representation and extraction

The immutable Pydantic contracts live in
`agent-server/src/server/services/repository_analysis/schemas.py`. All extractors
consume one sorted inventory with retained UTF-8 source and file content hashes.

| Area | Initial support |
| --- | --- |
| Technologies | File languages, dependency-based framework/tool detection, Python/Node runtime constraints |
| Structure | Directories, Python packages/namespace candidates, file module names, manifest-based project boundaries |
| Dependencies | Python/Node declarations, separate lock-resolved versions, import relations, TypeScript aliases and local workspace targets |
| Architecture | Candidate layers, locally resolved inheritance, repository/port implementation signals, import cycles, static-export settings |
| Entrypoints | Python main guards/conventions, console/package commands, FastAPI/Flask/Django routes, NestJS bootstrap/routes, Next.js entry files |
| Infrastructure | Docker images/commands, Compose services/ports/dependencies, Django database engines, selected database/service SDK integration candidates |
| Tests | Naming-based test files, selected test dependencies/imports/configuration, package/Makefile test commands |

Python symbols use AST; JavaScript/TypeScript use Tree-sitter. Symbols include
complete line spans, decorators, parent ownership, signatures where available,
and base names. Typed relationships preserve internal, external, builtin,
unresolved, and dynamic outcomes. Unresolved imports are not classified using
packages installed on the local host.

Manifest support includes `pyproject.toml`, literal `setup.py` fields,
`setup.cfg`, requirements files, `Pipfile`, and nested `package.json` projects.
Lock support includes `uv.lock`, `poetry.lock`, `Pipfile.lock`, npm, pnpm, and
common Yarn forms. Lock-only packages are recorded as transitive. Constraints,
resolved versions, and runtime requirements remain separate facts.

Evidence records reference retained files and a detection rule, plus line ranges
or configuration keys. Facts distinguish `declared`, `observed`, and `inferred`.
Entity identifiers are deterministic within the repository's relative-path
namespace. The snapshot identity incorporates inventory content/status,
directories, extraction limits, extractor version, and Python version. Git HEAD
is metadata; file hashes represent working-tree contents, including local edits.

## Coverage and boundaries

Default limits are 5,000 retained files, 30 directory levels, 2 MB per file, and
64 MB of retained file bytes. These are source-retention limits, not a cap on
total process memory or the number of discovered file records. Coverage reports
file statuses, parsing/configuration issues, unsupported source languages, and
known limitations. Generated/dependency/VCS directories are skipped; symlink
files and `.env` files are excluded. Other text files can be indexed.

Source files are checked again before publishing the result. Detected changes
during analysis raise `RepositoryChangedError`; this is a best-effort consistency
check, not an atomic filesystem snapshot.

Deep parsing currently covers Python and JS/TS. Other languages are detected,
with unsupported deep analysis reported explicitly. XML headers take precedence
over extensions (including Tiled `.tsx` assets).

Architecture signals are candidates and observations, not compliance judgments.
Route mount prefixes, runtime wiring, dynamic configuration, arbitrary Python
packaging code, complex workspace exports, and unknown import/distribution
mappings can remain unresolved. Test file candidates do not establish test
execution coverage. Text search is literal, in memory, and paginated.

## Verification

```bash
uv run pytest tests/repository_analysis -q
uv run ruff check src/server/services/repository_analysis tests/repository_analysis
```

Fixture tests cover deterministic output, source immutability after filesystem
changes, consistency rejection, monorepo aliases, lock versions, decorators,
evidence references, extraction limits, malformed manifests, and snapshot queries.
