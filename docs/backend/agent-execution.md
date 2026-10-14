# Backend Contract — Agent Executions

Tracks one invocation of one agent. The **backend** creates the row and starts the
agent; the agent-server only ever **updates** that row. Agents never create
executions.

Source of truth: `backend/src/modules/agent-execution/`
(repository, service, controller)

## Lifecycle

Current HTTP contracts: backend `/docs` ([documentation index](README.md)).

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
   |      execution_id, config }      |   or
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
agent defines its own shape, so the backend stores and returns it without
inspecting its fields.

The backend writes `Failed` in exactly two cases: the agent-server could not be
reached, or the run never started — plus the pipeline's `Skipped` close of
stages whose predecessor failed first. Everything else is reported by
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

Project analysis calls `openProjectArchitecturePipelineForProject()`: all stage
configurations are verified before a transaction creates the version/evaluation
and one row per stage (`orientation`, `architecture`, `semantic_validation`).
Each row captures its own immutable public configuration. The service
broadcasts one `opened` per row and dispatches the project-architecture
pipeline in the background with every captured transport configuration:

```
backend                        agent-server                  rows
   |
   |-- POST /api/pipelines/project-architecture/run ------>  |
   |    { input: { root_path },                                |-- POST orientation/running    -> "Running"
   |      execution_ids: { orientation, ... },                |-- orientation -> POST orientation/completion
   |      stage_configs: { orientation, ... } }               |
   |                                                          |-- POST architecture/running   -> "Running"
   |                                                          |-- architecture -> POST architecture/completion
   |                                                          |-- ... same for semantic_validation
   |
   |<- websocket agent-execution.updated (each transition, every row)
```

Stage inputs after the first are derived server-side, so the backend never
parses one agent's result to feed another. There is no chaining in
`complete()`: every row exists before the pipeline starts.

- A stage fails → its row closes as `Failed`, later stages close as
  `Failed` with a `Skipped:` error. No row hangs in `Waiting`.
- The pipeline request itself fails to start (unreachable agent-server, missing
  checkout, no pipeline support in the invoker) → every row closes as `Failed`
  with the same error.
- Pipeline timeout (600s) → every row still open closes as `Failed`.

The invoker ceiling for pipelines is 660s (`PIPELINE_INVOKE_TIMEOUT_MS`):
the 600s pipeline deadline plus headroom for the callbacks to land.

## `POST /api/agent-executions`

Registers an invocation. Called by the backend, not by agents.

Request:

```json
{
  "agentType": "dummy",
  "evaluationId": 12
}
```

`agentType` must already exist in `agent_settings` (foreign key).
`evaluationId` must reference an existing evaluation.

Response `201`: `id`, `evaluationId`, `agentType`, `status` (`Waiting`), `result`,
`error`, `inputTokens`, `outputTokens`, `createdAt`, `startedAt`, `finishedAt`.

Keep the returned `id`: every later call addresses the run by it.

## Direct invocation: `POST /api/agent-executions/direct`

Body: `agentType` (non-empty string) and `input` (object with at least one
property), both required. Returns `201` with the execution shape above and
`evaluationId: null`; no project version or evaluation is created.
If `root_path` is present, it must resolve inside the backend workspace:
escaping it returns `422` before creation. A missing checkout fails the created
execution in the background. Other input fields pass through to the agent.

```json
{ "agentType": "dummy", "input": { "code": "def add(a, b): return a + b" } }
```

## Running callback: `POST /api/agent-executions/:id/running`

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

Domain errors use `{ "error": "..." }`. Schema validation `400` errors use
Fastify's `{ statusCode, code, error, message }` shape.

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
  A pipeline needs one row per stage: a missing stage row fails
  `POST /api/projects/:id/architecture` with `422`.
  `agent_settings` rows are inserted manually (tests seed them); there is no
  admin endpoint for them yet.
- The agent-server derives where to report from `PORT_BACKEND`. If it is not
  configured the run still works, it just reports nowhere and the row stays
  `Waiting`.
- The existing callbacks accept input/output counts at completion. Live reporting
  from the agent-server is still pending integration.

## Token usage persistence

Migration `20261014000000_agent_token_budget` adds nullable `estimatedTokens`,
`accountedTokens` and `interruptionReason` to execution rows. Existing
`inputTokens` and `outputTokens` store provider-reported cumulative counts;
estimates are never written into those reported counters. Null means usage has
not been recorded, rather than zero consumption.

`AgentExecutionRepository.updateUsage()` stores cumulative progress while a row
is Running, with `accountedTokens = (inputTokens ?? 0) + (outputTokens ?? 0) + estimatedTokens`.
An atomic update rejects progress that would reduce reported or accounted usage
and ignores progress after completion. Duplicate cumulative updates are safe.
Completion preserves previously recorded usage when counts are absent/null, and
can store a machine-readable interruption reason alongside `error` and the
partial serialized `result`.

The repository and project history read the new fields. Progress HTTP callbacks,
public execution usage fields and WebSocket usage updates will be connected in
the live-reporting phase.
