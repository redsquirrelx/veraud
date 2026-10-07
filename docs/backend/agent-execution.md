# Backend Contract — Agent Executions

Tracks one invocation of one agent. The **backend** creates the row when it
invokes an agent and passes the id to the agent-server; the agent-server only
ever **updates** that row. Agents never create executions.

Source of truth: `backend/src/modules/agent-execution/`
(repository, service, controller)

## Lifecycle

```
backend                      agent-server                  row
   |
   |-- POST /api/agent-executions ------> |
   |<- 201 { id, status: "Idle" }
   |                                       |
   |-- pass id to agent ---------> run ----+--> POST /:id/running        -> "Running"
   |                                    or
   |                                       +--> POST /:id/completion     -> "Completed" | "Failed"
   |
   |<- websocket agent-execution.updated (each transition)
```

| Status | Meaning |
|---|---|
| `Idle` | Invocation registered, nothing has run yet |
| `Running` | Agent started (optional: the agent may skip this) |
| `Completed` | Finished successfully; `result` holds the output |
| `Failed` | Finished with an error; `error` is required |

`result` is the serialized agent output and is **opaque** to the backend: each
agent defines its own shape (e.g. the analyzer returns a project description),
so the backend stores and returns it without inspecting its fields.

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

Response `201`: `id`, `evaluationId`, `agentType`, `status` (`Idle`), `result`,
`error`, `inputTokens`, `outputTokens`, `createdAt`, `startedAt`, `finishedAt`.

Keep the returned `id`: every later call addresses the run by it.

## `POST /api/agent-executions/:id/running`

Optional. Marks the run as in flight. Returns the same shape as above with
`status: "Running"`.

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
| `422` | `Failed` without an error message |

## Websocket events

Broadcast on `/ws` for every transition:

| Event | When |
|---|---|
| `agent-execution.opened` | Row created (`Idle`) |
| `agent-execution.updated` | `Running`, `Completed` or `Failed` |

Payload is `{ type, execution }` where `execution` has the same fields as the
HTTP response. The UI keys off `execution.id`.

## Notes

- **No authentication yet.** Any caller can close an execution with an arbitrary
  result. Local use only until a shared secret or signature is added.
- `agent_settings` is currently empty, so registering any `agentType` fails on
  the foreign key until a row exists for it.