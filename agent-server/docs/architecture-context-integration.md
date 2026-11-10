# Independent Architecture Context and project analysis

`ArchitectureContextAgent` is registered as `architecture_context`, independently
of quality audits and the legacy project-architecture pipeline. Both the direct
agent and development runner use the same documentary graph topology. The graph
retains prior valid knowledge on later node failures and finalizes deterministically.

## Entry points

- Agent-server: `POST /api/agents/run`, `agent_type: "architecture_context"`.
  Input: `root_path` (repository directory), optional `commit_hash` (defaults to
  `HEAD` for standalone use). Extra narrative/prompt fields are rejected.
  Contracts are discoverable through `GET /api/agents/architecture_context/schema`.
- Backend: `POST /api/agent-executions/direct` accepts **either** explicit `input`
  (existing unassociated direct-run semantics) **or** a project target:

  ```javascript
  {
    agentType: "architecture_context",
    project: { projectId: 2, branch: "main", commitHash: "<40-character SHA>" }
  }
  ```

The project-target form creates/reuses the `ProjectVersion` identified by
project/commit and creates an `ArchitectureContext` evaluation and execution.
It does not change the project's selected version. The backend derives the
checkout path and passes an explicit commit; no local path comes from the browser.
Active context executions are adopted rather than dispatched twice. New attempts
after termination retain previous history.

The indexer reads committed Markdown blobs, not working-tree content. The SQLite
document index stays in the existing host cache outside the repository, shared
with the CLI. Provider clients remain host-owned; model calls reuse shared
budgeting, pacing, tracing and cumulative usage callbacks. The global
`budgets_enabled` switch applies to CLI and production without per-agent overrides.

## Persistence and outcomes

`ArchitectureContextArtifact` stores the canonical result string, schema version,
native execution status, execution ID and project-version relation through Prisma.
Artifact insertion and execution completion share one transaction. Completion
callbacks with missing output or a mismatched commit are rejected; duplicate and
late callbacks do not overwrite terminal outputs. Transport failures without a
canonical result close the execution without inventing an artifact.

The backend verifies the output envelope and commit at its storage boundary;
the full canonical contract remains the Python `ArchitectureContextResult`.
`GET /api/agent-executions/:id` returns the persisted output. No separate public
artifact download route is added; project audits resolve the saved JSON internally.

`Completed` means the agent delivered its result, **not** complete documentary
coverage or architectural compliance. The canonical `complete`, `partial`, `failed`,
evidence, issues, pending categories and validation diagnostics remain in the JSON.
The frontend accepts partial output with an explicit partial-coverage message;
native failed output stops the pipeline, even when delivery was `Completed`.

## Activation

1. In `backend/`, run `pnpm prisma migrate deploy` and `pnpm prisma generate`.
2. Restart agent-server, then restart backend or sync its agent catalog using
   `POST /api/agent-settings/sync`.
3. Configure the model and credential for `architecture_context` in agent settings.
4. Refresh the web application. **Analyze** waits for the graph, then starts and
   tracks context extraction for the same project/commit.

Closing the page stops frontend continuation/polling, not a submitted agent run.
The backend can persist that run's callback without a browser. Pending future
steps are not a durable backend workflow. Analyzing still does not launch an audit
automatically.

## Automatic Maintainability V2 prerequisite

Project audits selecting maintainability require a stored usable context for the
exact project/commit. `GET /api/projects/:id/architecture-context?commitHash=...`
returns availability and source execution metadata, never the large JSON.
The backend chooses the latest valid `complete` or `partial` artifact from a
completed context execution. A failed regeneration does not discard an older
usable context. Other projects/commits, failed-only contexts and corrupted
artifacts cannot satisfy the prerequisite.

The backend injects the unchanged canonical JSON into
`request.documented_architecture`; project audit requests cannot supply `request`.
The immutable audit configuration records the context execution ID, version ID,
schema version and native execution status. A later context does not change an
existing audit's source. Agent-server verifies the document-index commit against
the requested revision and the actual immutable repository snapshot.

The Manager and coordinators carry this field only as transport/provenance data:
their planning prompts exclude `documented_architecture` entirely. Deterministic
dispatch forwards the full typed context only to investigators whose request
schema explicitly declares `documented_architecture`. It is never converted into
free-form `architectural_context` or embedded in delegated objectives. The
documentary ArchitectureBoundary investigator opts in through its native schema;
evidence, issues, partial coverage and limitations are preserved unchanged.

The standalone Manager runner accepts `--architecture-context <context-output>`
to validate the canonical ArchitectureContextResult and use the same transport
path. It does not generate context, summarize it or add a model call. The
standalone Modularity runner already supports the same option. Omitting the option
retains standalone compatibility; project audits still require saved context.

The web configuration has no manual JSON field. Maintainability is blocked during
availability checks, on check failure and without context. Partial coverage is
displayed explicitly. Selecting maintainability in a combined audit blocks the
whole submission when context is missing; it is never silently dropped. Users can
deselect it to run security or functional adequacy independently. The availability
check refreshes after revision/pipeline changes and polls missing context.
