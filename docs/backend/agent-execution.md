# Backend Contract — Agent Executions

Tracks one invocation of one agent. The **backend** creates the row and starts the
agent; the agent-server only ever **updates** that row. Agents never create
executions.

Source of truth: `backend/src/modules/agent-execution/`
(repository, service, controller)

## Lifecycle

The backend starts the agent over HTTP and then gets out of the way. The agent
reports its own progress back over HTTP, because it is the only side that knows
how the run went.

```
backend                        agent-server                  row
   |
   |-- POST /api/agent-executions -> 201 { id, status: "Waiting" }
   |
   |  (background, never awaited)
   |-- resolve evaluation -> workspace path
   |-- POST /api/agents/run ------>  |
   |    { agent_type, input,          |-- POST /:id/running      -> "Running"
   |      execution_id }              |   or
   |                                   +-- POST /:id/completion  -> "Completed" | "Failed"
   |
   |<- websocket agent-execution.updated (each transition)
```

| Status | Meaning |
|---|---|
| `Waiting` | Invocation registered, agent not reached yet |
| `Running` | Agent started |
| `Completed` | Finished successfully; `result` holds the output |
| `Failed` | Finished with an error; `error` is required |

`result` is the serialized agent output and is **opaque** to the backend: each
agent defines its own shape (e.g. the analyzer returns a project description),
so the backend stores and returns it without inspecting its fields.

The backend writes `Failed` in exactly two cases: the agent-server could not be
reached, or the run never started — plus the pipeline's `Skipped` close of the
architect row when the analyzer failed first. Everything else is reported by
the agent.

## Starting the agent

`open(agentType, evaluationId)` creates the row, broadcasts `opened`, and then
dispatches in the background. It never awaits the run, so the `201` returns while
the agent is still working: an agent takes minutes.

The input is built by the backend, not by the caller —
`evaluationId → evaluation → projectVersion → project → the checkout in the
workspace` — sent as `{ root_path }`.

`execution_id` travels in the request body: it is what the agent-server reports
progress against. Without it the agent still runs, it just reports nowhere.

## Starting a pipeline

`openPipeline(evaluationId)` creates two rows, `analyzer` + `architect`, on the
same evaluation, broadcasts one `opened` per row, and dispatches the
architecture-audit pipeline in the background:

```
backend                        agent-server                  rows
   |
   |-- POST /api/pipelines/architecture-audit/run -------->  |
   |    { input: { root_path },                                |-- POST analyzer/running      -> "Running"
   |      execution_ids: { analyzer, architect } }             |-- analyze -> POST analyzer/completion
   |                                                          |-- POST architect/running     -> "Running"
   |                                                          |-- describe -> POST architect/completion
   |
   |<- websocket agent-execution.updated (each transition, both rows)
```

The pipeline derives the architect input server-side from the analyzer output,
so the backend never parses one agent's result to feed another. There is no
chaining in `complete()`: both rows exist before the pipeline starts.

- Analyzer fails → its row closes as `Failed`, the architect row closes as
  `Failed` with a `Skipped:` error. No row hangs in `Waiting`.
- Architect fails → the analyzer row stays `Completed`.
- The pipeline request itself fails to start (unreachable agent-server, missing
  checkout, no pipeline support in the invoker) → both rows close as `Failed`
  with the same error.
- Pipeline timeout (600s) → every row still open closes as `Failed`.

The invoker ceiling for pipelines is 660s (`PIPELINE_INVOKE_TIMEOUT_MS`):
the 600s pipeline deadline plus headroom for the callbacks to land.

## `POST /api/agent-executions`

Registers an invocation. Called by the backend, not by agents.

Request:

```json
{
  "agentType": "analyzer",
  "evaluationId": 12
}
```

`agentType` must already exist in `agent_settings` (foreign key).
`evaluationId` must reference an existing evaluation.

Response `201`: `id`, `evaluationId`, `agentType`, `status` (`Waiting`), `result`,
`error`, `inputTokens`, `outputTokens`, `createdAt`, `startedAt`, `finishedAt`.

Keep the returned `id`: every later call addresses the run by it.

## `POST /api/agent-executions/:id/running`

Marks the run as in flight. Called by the agent-server. Returns the same shape as
above with `status: "Running"`.

## `POST /api/agent-executions/:id/completion`

Closes the run. Called by the agent-server.

Request:

```json
{
  "status": "Completed",
  "result": "{\"kind\":\"library\",\"summary\":\"...\"}",
  "error": null,
  "inputTokens": 1200,
  "outputTokens": 180
}
```

`status` is `Completed` or `Failed`. `Failed` requires a non-empty `error`.
`result` and the token counts are nullable.

A callback on an already-closed run is **ignored** and the stored row is
returned unchanged, so a retried or duplicated callback cannot overwrite a
finished result.

## `GET /api/agent-executions/:id`

Returns the same shape. Useful for reconnecting the UI after a reload: the id
is known, and the current status can be polled or awaited over the websocket.

## Errors

| Code | Meaning |
|---|---|
| `400` | Malformed body, or non-numeric `:id` |
| `404` | Unknown agent execution |
| `422` | `Failed` without an error message, or an `agentType`/`evaluationId` that does not exist |

## Websocket events

Broadcast on `/ws` for every transition:

| Event | When |
|---|---|
| `agent-execution.opened` | Row created (`Waiting`) |
| `agent-execution.updated` | `Running`, `Completed` or `Failed` |

Payload is `{ type, execution }` where `execution` has the same fields as the
HTTP response. The UI keys off `execution.id`.

## Notes

- **No authentication yet.** Any caller can close an execution with an arbitrary
  result. Local use only until a shared secret or signature is added.
- `agent_settings` must have a row for the `agentType`; both it and
  `evaluationId` are foreign keys, and a missing one is reported as `422`.
  A pipeline needs rows for **both** `analyzer` and `architect`: a missing
  `architect` row fails `POST /api/projects/:id/analyze` with `422`.
  `agent_settings` rows are inserted manually (tests seed them); there is no
  admin endpoint for them yet.
- The agent-server derives where to report from `PORT_BACKEND`. If it is not
  configured the run still works, it just reports nowhere and the row stays
  `Waiting`.
- Token counts stay null: the agent-server does not return usage yet.