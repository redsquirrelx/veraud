# Independent project graph extraction

The project header's **Analyze** action now starts a `graph.extract` **Task**, not
an audit. Audit configuration and **Start audit** remain in the Analysis section.
No `AgentExecution`, evaluation, model, LLM or auditor is involved in extraction.

## Request and lifecycle

- `POST /api/projects/:id/graph` accepts `{ branch, commitHash, regenerate? }` (full 40-character
  lowercase commit hash). The project must have a ready checkout. It returns
  **202** with extraction metadata without waiting for Graphify. Active requests
  for the same project/commit reuse the task; simultaneous creation is guarded.
  Completed graphs are reused by default (`reused: true`) without creating a
  task or invoking agent-server. Only `regenerate: true` requests a new extraction.
- The registered service executor dispatches `POST /api/graphs` to agent-server.
  Acceptance is not task success: the executor waits for a terminal callback.
- Agent-server reports `preparing`, `extracting`, `saving`, `completed` or `failed`
  through `CallbackClient` to `POST /api/tasks/:taskId/graph-callback`. Each job has
  a random capability token. Only its SHA-256 hash is persisted; tokens are not
  returned to the frontend or included in WebSocket events. Callback bodies are
  compact and never carry graph contents, source, provider configuration or raw
  exception messages. Failed callbacks may carry an allowlisted `errorCode` for
  repository/commit availability, snapshot preparation, missing Graphify, timeout,
  storage, interruption or a generic extraction failure. Backend transport and
  queue errors are categorized separately. Legacy callbacks without a code use
  the generic failure category.
- Backend persists progress and publishes existing `task.updated` notifications.
  Progress is monotonic; duplicate and out-of-order callbacks cannot reverse a
  terminal outcome. Task states retain `Queued`, `Running`, `Succeded`, `Failed`.
- `GET /api/projects/:id/graph?commitHash=...` restores the latest extraction for
  that revision. Frontend refetches on task notifications and polls active work
  every three seconds (five seconds after request failure), without blocking
  navigation. It ignores late responses for a previously selected commit.
  Loading a stored completed graph does not show a new-generation toast; a newly
  observed completion shows one confirmation per task. The graph section offers
  **Regenerate graph** for an available graph and **Retry** for a failed attempt.
  Retry explicitly requests another extraction and never treats the failed graph
  as a reusable artifact. If regeneration fails, `previousGraphTaskId` references
  the earlier completed artifact for downloading; `graphAvailable` still describes
  only the current task's result. Localized error descriptions never expose raw
  exception text, filesystem paths or credentials.
- `GET /api/projects/:id/graph/:taskId/artifact` streams the completed graph via
  backend. No full graph is sent in callbacks, WebSocket messages or list/status
  responses. The graph section offers a download; this change does not add an
  interactive node/edge renderer.

## Snapshot and storage

Agent-server validates that the repository resolves directly inside its configured
workspace. `git archive <commit>` creates a private source snapshot without
changing HEAD or copying dirty/untracked files. Archive traversal is rejected and
symlinks are not extracted. Graphify parses this snapshot with its existing
isolated code-only adapter. Neither repository code nor agent pipelines run.

By default artifacts live beside the workspace:

```text
appdata/graphs/<project_id>/<commit_hash>/<task_id>/
  manifest.json
  graphify-out/graph.json
```

The immutable manifest records project, task, requested branch, commit and Graphify
version. Temporary snapshots are removed on completion/failure. Output is renamed
into its published directory only after extraction succeeds, so partial output
is never downloadable. Numeric IDs avoid project-name collisions and traversal;
the branch name is metadata, not a path component. Backend and agent-server must
resolve the same workspace; artifacts are served by agent-server, so backend
does not need direct access to the graphs directory.

Agent-server developer environment settings:

| Setting | Default | Purpose |
| --- | --- | --- |
| `GRAPHS_ROOT` | Workspace parent / `graphs` | Artifact root. |
| `GRAPH_TIMEOUT_SECONDS` | 480 | Graphify deadline. |
| `GRAPH_MAX_PENDING` | 8 | Bound accepted jobs; parsing runs one job at a time. |

## Failure and restart semantics

Backend enforces a ten-minute remote deadline and attempts remote cancellation
after timeout/dispatch failure. Agent-server bounds snapshot creation and parsing,
retries callbacks three times and cancels jobs on graceful shutdown. Concurrent
Git checkout changes do not alter the selected commit snapshot.

Graph task metadata is durable in the new `graph_extraction` table. Execution
queues and locks remain single-process and memory-only. Backend startup marks
persisted active graph tasks **Failed/interrupted**, rather than pretending to
resume them; the user may start another extraction. An agent-server crash or
lost terminal callback is detected by the backend deadline. There is no automatic
retry, distributed queue or exactly-once guarantee. Published artifacts are
retained; no retention/deletion policy is introduced here.

## Deployment and focused checks

Apply the checked-in Prisma migrations before starting the backend. This change
adds `20261101000000_graph_extraction`; development database migrations are not
automatically applied by application startup.

```powershell
# backend (deploy only against the intended database)
pnpm exec prisma migrate deploy
pnpm exec prisma generate
pnpm exec tsx --test src/tests/project-graph.integration.test.ts

# agent-server
uv run --locked pytest tests/test_graph_extraction.py tests/test_graphify.py tests/test_repository_structure.py

# frontend
pnpm exec vitest run src/features/project-management/useProjectGraph.test.ts src/pages/project/ProjectDetailPage.test.tsx src/pages/project/ProjectDetailPage.i18n.test.tsx
```
