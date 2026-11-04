# Graphify adapter

The official [Graphify Labs package](https://github.com/Graphify-Labs/graphify)
is **`graphifyy==0.9.100`** (double `y`). Install the locked environment with
`uv sync --locked`. Its tree-sitter requirement is `>=0.25,<0.26`; the lock
currently resolves `0.25.2` for both Graphify and the existing JS/TS parsers.

```python
from pathlib import Path
from server.services.graphify import GraphifyAdapter

# Inside an async service; use a fresh, per-run directory outside the snapshot.
result = await GraphifyAdapter(timeout_seconds=120, max_workers=1).extract(
    repository_path=Path("/snapshots/project"),
    output_directory=Path("/artifacts/run-123"),
)
graph_file = result.graph_file
```

The adapter runs `python -I -m graphify extract ... --code-only` using the
server's interpreter, with provider backends, query logging and automatic
assistant updates disabled. Provider credentials and Python/Graphify overrides
are not inherited. The working directory, home and cache are isolated in the
output directory; the repository snapshot remains read-only. No assistant
skills, Git hooks or MCP connections are installed.

`GraphifyResult` returns the generated graph path and elapsed seconds. This
initial integration checks that the artifact exists and is nonempty; it does
not parse or validate the graph schema. CLI stdout/stderr are discarded rather
than exposing source data or exception details. `GraphifyError.code` identifies
invalid paths, unavailable processes, timeout, unsuccessful execution or missing
output. Cancellation is propagated after stopping the extraction process tree.

The output directory must not already exist or overlap the snapshot. The caller
owns artifact retention and cleanup, including partial artifacts after failure.
Only local AST extraction is supported: there are no LLM calls or automatic
changes to audit execution, budgets or evidence. The adapter itself is local;
the project graph API below schedules it independently of audit execution.
This is process isolation, not an OS security sandbox; use trusted snapshots and
the service's existing filesystem/access policies.

## Repository structure service

`server.services.repository_structure.RepositoryStructureService` is the
application-facing entry point for static extraction. It delegates exclusively
to `GraphifyAdapter`; it does not construct agents, models or provider clients.
Its `extract_structure(repository_path, output_directory)` coroutine returns
`GraphifyResult`, preserving adapter errors and cancellation. The structure is
the generated Graphify graph artifact, not a new normalized internal schema.

```python
from pathlib import Path
from server.services.repository_structure import RepositoryStructureService

result = await RepositoryStructureService().extract_structure(
    Path("/snapshots/project"), Path("/artifacts/new-run")
)
```

## Background project extraction

`POST /api/graphs` accepts a backend-owned task/project ID, branch, full commit
hash, workspace checkout path and callback capability token, returning `202`
without waiting. `GraphJobs` bounds background work and reports compact lifecycle
callbacks through `CallbackClient.graph_task`, never the agent execution routes.
`GraphExtractionService` creates an isolated Git snapshot for that exact commit,
runs the existing structure service, and atomically publishes artifacts under
`appdata/graphs/<project_id>/<commit_hash>/<task_id>/`. Dirty files and checkout
switches do not change the selected snapshot. Snapshots are removed after use.

`DELETE /api/graphs/:task_id` requires the matching `X-Graph-Token` and cancels
active work. `GET /api/graphs/:project_id/:commit/:task_id/artifact` serves only
published artifacts. Backend proxies downloads and checks the task's outcome.
Root paths and Graphify deadlines are developer environment settings, not
agent configuration. See [the backend integration contract](../../backend/docs/project-graph.md)
for configuration, callback authentication, persistence, migration and restart
semantics. This is a single-process background executor, not a durable job queue.

On Windows, Uvicorn reload workers may use `SelectorEventLoop`, which cannot
launch asyncio subprocess transports. Snapshot Git commands, Graphify and process
tree termination share `infrastructure.process.create_process`: native asyncio
where supported, otherwise process creation in a worker thread with nonblocking
polling and cancellation cleanup. This preserves `dev` hot reload without
blocking the API or disabling extraction deadlines. Regression tests exercise a
real Git snapshot and Graphify under the Windows selector loop.

Failed jobs log the task ID, last phase, public error code and exception **type**.
Raw exception messages, repository contents, callback tokens and provider secrets
are not logged by this diagnostic. The frontend shows a service description for
`graph.extract`; a missing Git command is expected for this task kind.

### Try a local directory

From `agent-server/` in PowerShell:

```powershell
uv sync --locked
uv run --locked python -m server.run_graphify "C:\repos\example" --out "C:\artifacts\new-run"
```

The equivalent direct script invocation is:

```powershell
uv run --locked python src/server/run_graphify.py "C:\repos\example" --out "C:\artifacts\new-run"
```

The runner uses the service (and therefore the adapter), prints the graph path
and duration, and exits `1` on extraction failure or `130` on interruption.
Invalid CLI arguments exit `2`. Optional `--timeout` and `--max-workers` override
the adapter's limits. `--out` must be a new directory outside the source tree;
use a different directory for each run. No backend, API key or LLM is required.

Run the focused checks with:

```powershell
uv run --locked pytest tests/test_graphify.py tests/test_repository_structure.py tests/test_graphify_integration.py -v
```

The integration test runs the real service and adapter on a temporary mixed
Python/TypeScript repository. It reads only the generated graph and checks file
modules, classes, functions, methods, containment, cross-file inheritance and
cross-file calls to known definitions. It also checks that the source tree is
unchanged. No Graphify mocks, provider credentials or running server are needed.

### Integration against the real Veraud repository

An additional opt-in test fetches `https://github.com/redsquirrelx/veraud` into a
temporary checkout pinned to commit `f8250927f91fa00bc524c38d035c07c212c1b719`.
It analyzes the entire checkout through the real service and adapter, and checks
Python `source_code.py` and TypeScript `directoryTree.ts` modules, function
definitions, containment and known calls. It also verifies the checkout stays
clean. No dependencies or code from the cloned project are installed or executed.

From `agent-server/` in PowerShell:

```powershell
$env:RUN_GRAPHIFY_VERAUD_INTEGRATION = "1"
uv run --locked pytest tests/test_graphify_integration.py::test_extract_real_veraud_repository -v
Remove-Item Env:RUN_GRAPHIFY_VERAUD_INTEGRATION
```

This test requires Git and network access. Network or extraction failures fail
the enabled test; it is skipped only when not explicitly enabled. Extraction
uses two workers and a 600-second timeout. The normal focused suite retains the
fast synthetic fixture without downloading a repository on every run. Updating
the pinned revision requires reviewing the expected symbols and relationships.
