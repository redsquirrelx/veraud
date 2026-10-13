# Restricted Repository Tools (Phase 2)

`RepositoryToolset` exposes repository queries over one immutable snapshot. It
binds to a single checkout directly inside the configured workspace and maintains
an in-memory tool budget and retrieval provenance ledger.

## Workspace Binding

The default workspace is this project's `appdata/workspace`. The host selects the
repository by supplying its snapshot. Tool arguments cannot supply a root,
workspace, filesystem reader, or alternate snapshot.

The toolset rejects snapshots outside the workspace, the workspace directory
itself, noncanonical file paths, and processed paths resolving outside the
selected checkout. Absolute paths, Windows drives/UNC paths, parent traversal,
URI-like paths, null characters, and alternate-stream syntax are rejected in
tool path arguments. Valid nested projects inside the checkout remain accessible.

Queries retrieve retained source only. They never open current source files,
resolve imports by reading neighboring checkouts, run repository code, or execute
shell commands. Scope binding resolves path metadata once when constructing the
toolset. Later edits/deletions do not change returned source.

`workspace_root` is optional trusted host configuration for deployments and test
fixtures. It is not part of any agent-facing tool schema. Entity IDs are scoped
to the bound snapshot; an identical relative-path ID in another repository cannot
switch the toolset to that repository.

## Use

```python
from server.agents.project_analysis import (
    ProjectAnalysisContext,
    ProjectAnalysisInput,
    RepositoryToolset,
)
from server.services.repository_analysis import RepositoryAnalysisService

snapshot = RepositoryAnalysisService().analyze_sync(
    "../appdata/workspace/199836402-thisishaykins-PyShop"
)
context = ProjectAnalysisContext(
    snapshot=snapshot,
    input=ProjectAnalysisInput(snapshot_hash=snapshot.repository.snapshot_hash),
)
tools = RepositoryToolset(context)
response = tools.execute(
    "get_source_excerpt",
    {"path": "products/views.py", "start_line": 7, "end_line": 11},
    tool_call_id="call-1",
)
state = tools.initial_state()
```

Use `tools.initial_state()` for the future graph's policy-filtered overview.
The phase-one context's raw query service remains an internal dependency.
`tools.as_langchain_tools()` returns structured adapters with strict argument
schemas. Direct execution accepts the actual model tool-call ID; standalone
LangChain adapters generate their own retrieval call IDs.

## File Access Policy

Filtering happens before search and pagination. Source code, tests, supported
technical configuration, manifests, lockfiles, Docker/Compose, requirements
files, and selected extensionless configuration files are allowed.

Narrative extensions such as Markdown/reStructuredText and ordinary text files
are excluded. README/changelog/contribution-style names are excluded even with
technical extensions. Narrative directories (`docs`, `doc`, `documentation`,
`guides`, `adr`, `adrs`) are excluded, including code located under them. Code
under `docs_src` remains eligible. Recognized architecture/design/security
narrative configuration names are also excluded. Comments/docstrings within
eligible code remain available as context.

The policy is an explicit filename/path/type rule set, not a semantic classifier
of prose. Unsupported file types are excluded by default. Binary, unreadable,
oversized, excluded, or otherwise unretained files cannot be retrieved.

The filtered view also removes symbols, evidence, relationships, and entrypoints
whose required files are excluded, and strips excluded paths/evidence from
aggregate records. Direct symbol/evidence access cannot bypass filtering.
Architecture signals are not exposed by this analyst toolset.

## Available Tools

- `get_repository_overview`, `list_projects`, `list_files`
- `find_symbols`, `get_symbol_source`, `get_source_excerpt`
- `get_dependencies`, `list_relationships`
- `get_outgoing_relationships`, `get_incoming_relationships`
- `list_entrypoints`, `get_infrastructure`, `get_testing_configuration`
- `search_repository_text`, `get_evidence`

File listings omit source content. Overview counts describe the accessible view;
`access_policy.omitted_files` and extraction issue counts retain visibility of
omissions in the original snapshot.

## Limits and Errors

Default `ToolLimits`:

| Limit | Default |
| --- | --- |
| Page size | At most 50 items (20 requested by default) |
| Successful response size | 16,000 serialized JSON characters |
| Source excerpt | 120 complete lines and 12,000 content characters |
| Nested metadata lists | 20 items per field |

Source excerpts cut only at line boundaries. Responses include actual bounds,
`requested_end_line`, and `truncated`, so callers can request the next range.
An oversized source range/line is rejected rather than partially returning a
line with inaccurate evidence bounds.

Pages can return fewer items to fit the serialized response limit, including
provenance overhead. `next_offset` refers to the first undelivered item; `total`
is the accessible query total. Nested-list omissions appear in
`omitted_field_items`. Oversized individual records return a controlled error.

Tool calls, including invalid attempted requests, consume the configured call
budget. Replayed call IDs and calls after exhaustion are rejected without
executing queries. Successful response JSON contributes to the cumulative
retrieved-character budget; controlled errors do not consume content budget but
remain constrained by the call budget. The elapsed-time budget is checked before
execution and before delivery. Calls are serialized to prevent budget races.

Responses contain `status`, `snapshot_hash`, `data`, `evidence`, and a structured
error when applicable. Unknown tools, invalid arguments, excluded references,
invalid ranges, and budget/response limits produce controlled failures.

`tools.budget_usage` reports tool-related counters and elapsed time. Later graph
nodes must preserve model/token counters when merging these into total usage.

## Retrieval Provenance

Evidence is registered only after a successful bounded response is delivered.
Dropped page items and failed requests do not create retrieval records.

- Source excerpts and text-search matches register `kind="source"` with exact
  delivered line ranges.
- Symbols, file records, and evidence/configuration metadata register
  `kind="metadata"`; they do not claim that implementation source was read.
- Records carry snapshot hash, file ID, retained content hash, tool-call ID, and
  applicable snapshot-evidence references.

`tools.validate_report_access(report)` combines phase-one reference validation
with the access policy and ledger. It rejects excluded entity references,
unretrieved citations, and fabricated/modified retrieval records. Semantic
support for a conclusion still requires later investigation validation and
evaluation; metadata retrieval alone is not proof of behavior.

## Verification

```bash
uv run pytest tests/project_analysis -q
uv run ruff check src/server/agents/project_analysis tests/project_analysis
```

Tests cover selected-checkout isolation, prohibited paths, documentation through
direct and indirect retrieval, all query adapters, retained source after deletion,
bounded excerpts/pages, provenance, strict schemas, concurrent budget enforcement,
time/content exhaustion, and report citation forgery.
