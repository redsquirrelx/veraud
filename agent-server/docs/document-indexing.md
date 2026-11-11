# Directory-scoped Markdown indexing

`DocumentIndexingService` is a deterministic service under
`server.services.document_indexing`. It has no dependency on agents, LangGraph,
embeddings, or model providers. SQLite must provide FTS5 and Git must be installed.

## Usage

From `agent-server/`, index a directory and list its Markdown documents:

```powershell
uv run document-indexing "C:\path\to\repository"
uv run document-indexing "C:\path\to\repository" --query "architecture"
uv run document-indexing "C:\path\to\repository" --query "architecture" --output "results.json"
uv run document-indexing "C:\path\to\repository" --commit HEAD --database "C:\indexes\docs.sqlite" --limit 10
```

The default database lives in the host cache (`LOCALAPPDATA` on Windows,
`XDG_CACHE_HOME` or `~/.cache` elsewhere), under `veraud/document-index.sqlite`.
It must be outside the audited repository. Search prints original section
locations, heading hierarchy, BM25 scores, and previews capped at 1000 characters.
Exit codes are 0 for success (including no matches), 1 for indexing errors, and
2 for invalid arguments. You can also run the file directly:

```powershell
uv run python src/server/run_document_indexing.py "C:\path\to\repository" --query "architecture"
```

`--output` writes an optional UTF-8 JSON test report: index summary, all document
metadata (regardless of `--limit`), the query, and up to `--limit` search results
with full content, headings, original line ranges, and provenance. Without
`--query`, `results` is empty. Console previews may be truncated, but exported
content is not. Parent directories are created as needed. Existing files are
never overwritten; choose a new filename for each report. SQLite is still the
persistent search index; JSON is only a readable export.

For programmatic use:

```python
from server.services.document_indexing import DocumentIndexingService
from server.runtimes.repository.document_tools import create_document_tools

# Use a persistent host-owned path outside the audited checkout.
service = DocumentIndexingService("appdata/document-index.sqlite")
index = service.index_repository("/workspace/project", commit="HEAD")
documents = service.list_documents(index.index_id, limit=20, offset=0)
hits = service.search_fragments(index.index_id, "gateway boundary", limit=10)
if hits:
    hit = hits[0]
    original = service.read_section(
        index.index_id, hit.path, hit.start_line, hit.end_line
    )

# Optional tools usable by LangChain or a LangGraph ToolNode.
tools = create_document_tools(service, index.index_id)
```

The tools expose `list_documents`, `search_documents`, and
`read_document_section`. Their Pydantic argument schemas forbid unknown fields.
The host binds the index: the model cannot choose another repository or commit,
index files, or access arbitrary filesystem paths. Returned values are JSON-safe
data including repository, commit, path, SHA-256 content hash, section ID,
header hierarchy, and inclusive one-based line ranges.

No agents or existing repository tools are automatically connected or changed.
Documentation is repository-authored narrative, not independently validated
evidence of code behavior. Existing audit policies remain unchanged.

## Sources and splitting

- `commit` defaults to `HEAD` and is resolved and verified once as a Git commit.
  Files are read from that immutable commit, strictly within the supplied directory.
  The directory may be a subdirectory of a larger Git repository; its path is never
  replaced by the enclosing Git root. Returned paths are relative to that scope.
  Local modifications, untracked files, symlinks, submodule entries and excluded
  dependency/build directories are not indexed. Invalid commits and directories
  outside Git fail explicitly instead of being treated as unversioned sources.
- Discovery reuses repository analysis's excluded-directory policy and extends
  it for documentation build outputs and common caches. Only `.md` files are
  included (case-insensitive); `docs/`, README files, and ADRs are allowed.
- LangChain's `MarkdownHeaderTextSplitter` supplies ATX (`#` through `######`)
  hierarchy and code-fence handling. Setext underlines are retained as body text,
  not interpreted as heading boundaries. Paragraphs under the same heading are
  combined; repeated identical headings remain distinct sections.
- Splitter-normalized text is aligned monotonically with original lines. Exact
  source slices, including indentation, tabs, blank lines, and CRLF, are retained.
  Unsupported alignment fails rather than inventing ranges. Empty documents are
  listed but contain no searchable sections. UTF-8 is required; decoding failures
  abort indexing rather than silently dropping a document.

## Storage and incremental behavior

Repository identity derives from the exact canonical directory path. Parent and
child directories and separate copies remain isolated. Index identity includes
directory identity, verified commit and processing version. A different directory
scope or commit creates a distinct index. Local edits do not change committed
evidence; historical indices remain queryable.

Git blob IDs and processing version identify reusable source blobs. Originals,
sections, and FTS entries are stored once per blob; index/path mappings preserve
provenance even when identical content appears in multiple files or repositories.
Reindexing is idempotent. Unchanged blobs require no repeated reads, splitting or
FTS insertion. Retained source content also carries its SHA-256 hash.
`IndexResult.processed` and `reused` count discovered document paths.

Each indexing operation is transactional. Failure rolls back the new index and
its documents/FTS rows; previously completed indices remain intact. Each call
uses its own SQLite connection, including tools invoked from worker threads.
Host code is responsible for database access control and historical-index
retention; automatic garbage collection is intentionally not provided.

Search uses literal AND-combined words, parameterized FTS5 MATCH, and BM25
(lower scores rank first). Paths and start lines break ties deterministically.
FTS statistics are shared across the database; results are always restricted to
the bound index, but numeric scores are not intended for cross-index comparison.
Search is lexical, not semantic; no vectors, embeddings, or LLM calls are used.

Default resource limits are 2 MB per document, 64 MB per index, and 10,000
documents. They are host constructor options and also apply to reused content.
Listing/search return at most 100 items per call. Source reads accept only an
existing section's exact range. Limit violations and invalid requests raise
`ValueError`; SQLite errors (including unavailable FTS5) propagate explicitly.

## Verification

### Architecture-context discovery

To test the documentary context workflow from `agent-server/`:

```powershell
uv run python src/server/run_architecture_context.py "C:\path\to\repository" --output "discovery.json"
# Print the canonical final result without creating a JSON file:
uv run python src/server/run_architecture_context.py "C:\path\to\repository" --stdout
# Explicit diagnostic export, including internal state and model usage:
uv run python src/server/run_architecture_context.py "C:\path\to\repository" --diagnostics --output-file "diagnostics.json"
# Equivalent installed command:
uv run architecture-context-discovery "C:\path\to\repository" --commit HEAD --limit 20
# Offline metadata-only mode, without credentials or LLM calls:
uv run python src/server/run_architecture_context.py "C:\path\to\repository" --discovery-only --stdout
```

The runner prepares/reuses the directory snapshot index first (this preparation may read
Markdown), then executes discovery and the bounded cycle
`plan_retrieval → retrieve_documents → extract_knowledge → plan_retrieval`.
After a successful coverage assessment, pending categories return to planning.
Full coverage, a blocking failure, or an empty retrieval plan ends the run; an empty
plan retains pending categories and accumulated knowledge without re-extracting.
All graph exits pass through the deterministic `validate_and_finalize` node, including
discovery-only runs and node failures. It checks the trusted index/catalog/section
provenance, original line ranges and literal quotes without repairing evidence or
calling a model. It builds `ArchitectureContextResult` (in `architecture_context/schemas.py`)
and stores it as `state['result']`. The canonical result includes validated `knowledge`, `knowledge_issues`,
`consulted_documents`, `validation_errors`, `execution_status` (`complete`, `partial`,
`failed`) and `finalization_reason`. Rejected references do not discard valid items.
Only seven confirmed categories without blocking errors constitute complete execution.
Discovery itself reads metadata only. `--database` selects SQLite outside the audited repository;
the default uses the same host cache as `document-indexing`. Optional `--output`
or its alias `--output-file` exports only this canonical final result to a new JSON file,
regardless of the console `--limit`. The result includes `document_index` and
`section_paths` to resolve evidence IDs to consulted-document provenance without
including full source sections. It excludes plans, retrieval history, database paths
and model usage. Add `--diagnostics` to export the operational report instead:
metadata, model usage and the full internal state (including `state.result`).
Existing operational-report consumers must request `--diagnostics`; canonical
consumers validate the JSON directly as `ArchitectureContextResult`, without a
`state` wrapper. Existing saved files are not migrated automatically.
Planning uses the model settings from
`config/dev-agents.yaml`, key `dummy` by default (override with `--agent-config`),
and the existing server `LLM_API_KEY` configuration. `--provider` and `--model`
can override model selection. Only model settings are reused; no other agent is
executed. Nonempty catalogs invoke the LLM and may incur provider costs.
This runner disables cumulative token-budget enforcement only inside its own
execution scope. Consumption, estimates and failed-attempt reservations are still
recorded, but cannot prevent retries or subsequent planning/extraction rounds.
Other agents retain their existing token policy. `--max-total-tokens` is no longer
an option for this runner. The generic model-call cap is also disabled for this
runner. Time, tool, character and context limits remain active; `--timeout`
overrides the execution deadline. LangGraph's step guard accommodates the existing
tool allowance across retrieval rounds.
`--max-output-tokens` explicitly overrides the per-response cap in both model
settings and execution limits. The current development model config uses 4000;
larger extractions may need a higher cap, for example `--max-output-tokens 12000`.
This per-response cap remains active even with cumulative tokens unlimited. Structured responses retain
provider finish metadata: truncated output is reported as
`output_token_limit_reached`, not as a misleading JSON syntax error, and is never
accepted as complete knowledge even if its partial JSON happens to parse.
Clients are closed after success or failure. Empty catalogs need no credentials
and produce an empty plan. Failed discovery skips planning and retrieval.
Planned searches and reads are executed against the retained SQLite index;
Architectural knowledge is extracted from documentation only; no source-code
inspection, compliance evaluation or audit finding generation is performed.
Use `--discovery-only` to skip planning, retrieval and extraction.
Use `--stdout` instead of `--output` to emit the same canonical final result to
standard output; the human-readable summary goes to standard error. The two
options are mutually exclusive. SQLite is still used internally for the index.

`server.agents.architecture_context.discover_documents` is an opt-in deterministic
LangGraph node, not a registered runnable agent. Host code supplies the existing
audit index and binds the service; discovery never creates or refreshes an index:

```python
from functools import partial
from server.agents.architecture_context import discover_documents

node = partial(discover_documents, indexing_service=service)
update = node({"document_index": service.get_index(index.index_id)})
# Or: graph.add_node("discover_documents", node)
```

The node checks index identity, paginates metadata only, and sorts `documents` by
relative path. `document_discovery_status` is `ready` for a valid catalog,
including an empty one, or `error` for inaccessible/mismatched indices. On error,
the catalog is cleared rather than exposing stale or partial metadata.
`retrieval_context` is a bounded planner-facing summary; the full catalog remains
in state and must not be inserted wholesale into a model prompt.

### Retrieval planning (opt-in)

`server.agents.architecture_context.plan_retrieval` is a separate async LangGraph
node. Bind a caller-owned `BudgetedModel` using `partial(plan_retrieval,
model=managed_model)`. Reuse that same managed runtime across iterations so model
attempts, provider pacing, token reservations, and deadlines share existing
execution limits. No providers or credentials are constructed by this node.
The runner invokes this node by default; `--discovery-only` retains offline mode.

Input state contains `documents`, optionally `pending_categories`,
`retrieval_history` (previous attempted operations), `retrieved_sections`
(`DocumentSection` objects), and the previous `retrieval_plan`. Default pending
categories are architectural style, components, responsibilities, relationships,
constraints, interfaces_and_contracts, and architectural decisions.

The node makes one managed call using the existing schema-validated JSON output
path and returns `retrieval_plan` plus the cumulative `retrieval_round`. Up to four tasks are permitted per plan:
`search` has a brief lexical `query`; `read` has an exact catalog `path`. Unknown
paths/categories, blank or wordless queries, extra operations, and repeated
operations (including reordered/case-changed AND terms) fail validation without
a corrective LLM call. No searches, document reads, or architectural extraction
are executed. Empty catalogs or no pending categories return an empty plan
without using the model; failed discovery is an error, not an empty catalog.

The prompt contains a budget-bounded path/line menu ordered by hints specific to
the pending categories, not one generic architecture/README grouping. Catalog
headings are not fabricated: the service's document metadata has none.
Executed attempts and unexecuted plans are separate, and neither counts as
recovered knowledge or category coverage. Source excerpts and their existing
headings come only from already retrieved sections. Each history view has a
character budget and explicit omission counts; duplicate validation still uses
the entire state history, even when older entries are omitted from the prompt.
It does not resend the full catalog or document hashes/provenance. Omitted paths are reported; lexical
search still targets the full index. Accumulated claims, open issues and compact
retrieval suggestions guide later planning. On a later round, insufficient
context/tokens/calls/time returns an empty plan with `context_stop_reason`, keeping
accumulated knowledge intact. Provider/validation errors still propagate.

### Deterministic retrieval

`server.agents.architecture_context.retrieve_documents` executes `retrieval_plan`
using the same bound `DocumentIndexingService`. `read` pages original sections
for an exact indexed path with `read_document_sections`; `search` uses FTS5/BM25.
The node never reads the checkout, invokes Git, or calls an LLM. Index preparation
remains separate and commit-verified as described above.

`retrieved_sections` retains unique `DocumentSection` objects including original
content, hierarchy, paths, line ranges, hashes, index identity and commit. Both
existing and returned metadata must match the audited index/catalog. Stale
catalogs or previously retained sections are rejected; foreign result pages are
not admitted. Different source paths remain distinct even with identical text.

`retrieval_history` now records `RetrievalRecord` entries: the original task, bound `index_id`,
`status` (`ok`, `no_results`, `error`, `limited`), `executed`, result `section_ids`,
and optional `error` detail. A failed or limited attempt does not imply coverage.
`executed=False` means admission failed before a read/search call. The planner
consumes these outcomes and remains compatible with earlier task-only history.
Previously attempted operations are not re-executed by this node.

A valid empty search is `no_results`, whereas an inaccessible index or query
failure is `error`. Reading an existing empty document is `ok` with no sections.
Errors do not prevent independent later tasks from running. If a later read page
fails, earlier valid fragments remain retained and the operation is still marked
`error`, with IDs identifying exactly what was obtained.

The existing `ToolLimits` and `ExecutionBudget` contracts control page size,
source lines/characters, response characters, cumulative retrieval characters,
and source-call count. `retrieval_usage` reuses `BudgetUsage` across iterations;
each search/read page counts as a call, including failures. Admitted serialized
section payloads count toward character usage, including duplicates, although
only one copy is stored. Whole source sections exceeding limits are omitted
and marked `limited`, never silently shortened or given invented ranges. Hitting
the search page cap is also reported as `limited` because more results may exist.
An optional shared `ActiveDeadline` bounds admission between calls.

The runner exports the final result with `--output` or `--stdout` (full source content
and operational outcomes require `--diagnostics`), reports
section counts in its summary, and returns a nonzero exit code for retrieval
errors or limits. Valid empty results remain successful. The workflow is not
registered as a production audit agent.

### Incremental knowledge extraction

`extract_knowledge(state, model=managed_model)` makes bounded schema-validated
managed calls, one per batch of previously unprocessed whole sections. Batches are
filled while the measured prompt fits the context limit; accumulated claims/issues
are supplied to each batch so later batches can avoid duplication and preserve
contradictions. The prompt requires exhaustive rule detail: identifier, normative
keyword, scope, allowed dependencies, applicability conditions, explicit limits and
exceptions as separate claims. It also distinguishes code-applicable constraints
from audit-methodology rules, which retain their identifier but use constraint
`unspecified` and an explicit methodology label.

`knowledge` stores typed `KnowledgeClaim` entries: category, subject, statement,
related subjects, explicit/derived/unknown certainty, reasoning, constraint modality
and supporting `section_ids`. `knowledge_issues` stores unknowns, ambiguities,
documentary discrepancies and referenced paths/links needing retrieval. These are
documentary interpretations, never audit findings or claims about actual code
behavior.

The prompt includes whole new sections (ID/path/lines/headings/content), accumulated
claims/issues and compact catalog paths; it omits repository identities and hashes.
The node extracts all categories regardless of the original retrieval category.
Every new assertion/issue must cite at least one section in the current batch,
optionally with earlier section IDs. All citations, including accumulated knowledge,
are checked against the retained snapshot before state updates. A response that cites
only previously processed sections triggers one bounded correction retry with the
exact new section IDs. If it still fails, the batch is not applied, its sections
remain unprocessed and execution stops as `limited`; prior knowledge is retained.
Unknown section IDs remain strict validation errors. A provider
`output_token_limit_reached` splits the batch deterministically and retries its
halves. A single whole section that still exceeds the output cap or the context limit
is never truncated: it remains unprocessed and extraction is marked `limited`.

Merging preserves original assertions and combines citations for equivalent wording
(case/whitespace normalization). The prompt asks for stable wording when reusing an
existing assertion. Opposing propositions remain separate; discrepancies are never
deleted. Other questions can be resolved only with new supported knowledge in that
category. Unknown assertions remain historical and create open issues until resolved.

`covered_categories` requires supported non-unknown knowledge, no open issues, and
no relevant referenced catalog document that has not been fully read. Open issues
with `document_references` are resolved against the supplied catalog relative to the
citing section. Unread references block coverage, stay pending and become concrete
read leads; resolving such an issue is deferred until the referenced documents are
fully read. The model's coverage proposal is filtered deterministically. Unsupported
or unresolved categories stay pending without aborting an otherwise valid extraction.
Partial knowledge must retain an issue. `pending_categories` is recomputed from
actual evidence-based coverage, never from reads/searches. A new ambiguity can
reopen a previously covered category. `processed_section_ids` prevents reprocessing
old source content. `retrieval_suggestions` contains validated, nonrepeated leads
for the next planner; it does not execute retrieval itself.

Routing after extraction is deterministic: replan only for pending needs with
concrete useful leads and sufficient remaining execution capacity. Empty plans,
no new sections, no useful leads, exhausted tools/tokens/time/model calls, or the
existing `InvestigationConfig.max_iterations` bound stop the cycle. Both cognitive
nodes share one `BudgetedModel`, token ledger and deadline. Tool usage persists
across rounds. Missing knowledge stays pending even when no useful queries remain.
Both cognitive calls request native `json_schema` output when the adapter supports
it, using the existing lean provider schema. Custom adapters without this capability
retain the JSON-text fallback. Raw responses still undergo strict JSON/Pydantic and
citation validation: duplicate keys are never silently accepted or overwritten.
Usage, provider retries and output limits remain on the same managed runtime.
CLI errors identify `plan_retrieval` or `extract_knowledge`; malformed responses are
reported without printing their source content.
The runner exports claims/issues/coverage and returns nonzero for extraction limits.
`review_extraction` is not implemented; deterministic finalization is performed by
`validate_and_finalize`.

### Operational traces

The architecture-context runner emits operational traces by default to **stderr**,
prefixed with `[architecture_context]`. The existing command needs no extra flag.
`--no-trace` disables these traces and sanitized stack traces (not provider logging).
`--stdout` still emits only the JSON report to stdout.

Traces include index preparation; node/round start, completion and elapsed time;
plans; exact read paths/FTS queries; page counts, retained section IDs, duplicates,
omissions and retrieval limits; extraction input references and result counts;
batch sizes, output-limit splits, citation-correction attempts and skipped sections;
proposed/supported/blocked/accepted coverage; unresolved referenced documents;
pending categories; and deterministic route destinations with explicit
stop/continue reasons. LLM events reuse the managed gateway's
attempt/retry/HTTP-error/usage events, including provider finish reasons.
The token ledger still reports actual consumption and conservative failed-attempt
estimates even though cumulative token enforcement is disabled for this runner.

Errors include the complete exception cause chain and stack frame locations
(file, function, line). Raw exception strings, prompts, responses, document content,
source lines, local variables, and API keys are not dumped. Known validation codes
and sanitized schema locations are retained. Caught retrieval failures also emit
sanitized stack traces, even when later independent tasks continue successfully.

### Commands

```sh
uv run pytest tests/test_document_indexing.py tests/repository_analysis/test_service.py -q
uv run pytest tests/test_architecture_context_discovery.py -q
uv run pytest tests/test_architecture_context_planning.py -q
uv run pytest tests/test_architecture_context_retrieval.py -q
uv run pytest tests/test_architecture_context_extraction.py -q
uv run ruff check src/server/services/document_indexing src/server/runtimes/repository/document_tools.py tests/test_document_indexing.py
```
