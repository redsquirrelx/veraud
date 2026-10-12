# Connecting to the backend WebSocket

The backend exposes a native WebSocket at `/ws` for Git task and agent execution
notifications. Open `/docs/ws` on the backend host and port for the AsyncAPI
portal, or `/docs/ws/spec` to download its YAML. The generated AsyncAPI contract is
`backend/src/infrastructure/asyncapi/asyncapi.yaml`; its authoring sources are
described in [the AsyncAPI setup guide](asyncapi.md).

## Address and handshake

Use the backend host and port, not the frontend or agent-server address:

```text
HTTP backend:  http://localhost:7501 → ws://localhost:7501/ws
HTTPS deployment: https://backend.example.com → wss://backend.example.com/ws
```

The HTTPS address above is an illustrative deployment address. TLS must be
provided by the deployment; the gateway does not configure TLS. AsyncAPI's
development hostname and port variables are editable defaults, not automatic
discovery of the backend serving a documentation page.

The browser establishes a GET upgrade automatically when constructing a WebSocket.
The application requires no auth token, subscription request, query parameter
or subprotocol. All connected clients receive all broadcast events. The backend's
HTTP CORS configuration should not be interpreted as WebSocket authorization.

The current frontend constructs its URL from `VITE_BACKEND_URL`, defaulting to
`http://localhost:7501`, by replacing the initial `http` with `ws` and appending
`/ws`. Configure that base without a trailing slash: the existing helper does
not normalize one and would produce `//ws`. Reverse-proxy path prefixes must be
routed consistently with the configured backend base URL.

## Reading messages

A minimal browser consumer for a known backend URL:

```js
const backend = new URL("http://localhost:7501")
backend.protocol = backend.protocol === "https:" ? "wss:" : "ws:"
backend.pathname = "/ws"
const socket = new WebSocket(backend)

socket.addEventListener("message", ({ data }) => {
  let event
  try {
    event = JSON.parse(String(data))
  } catch {
    return
  }
  switch (event?.type) {
    case "task.updated":
      console.log("Task state", event.task)
      break
    case "agent-execution.opened":
    case "agent-execution.updated":
      console.log("Execution state", event.execution)
      break
  }
})
```

This example logs live events only; it does not implement recovery or schema
validation. There is no subscribe/acknowledgement command to send. Each message
is JSON text with a top-level type discriminator and a task or execution object.
Reconcile by `task.id` or `execution.id`; those are entity IDs, not unique event IDs.
Execution timestamps are ISO strings; execution result is an opaque JSON string
or null, not a nested object. Task messages omit the repository names supplied
by the task HTTP response.

## Lifecycle and delivery

Opening a socket does not send a greeting, snapshot or historical messages.
Only later broadcasts are delivered. No application replay cursor, sequence
number, acknowledgement or missed-event buffer exists.

WebSocket preserves send order within a live connection. Independent task and
execution updates may interleave. The application provides no ordering across
connections and does not guarantee exactly-once delivery. Synchronous send
failures are logged without an application-level retry.

- Tasks normally emit Queued, Running, then Succeded or Failed. Preserve the
  existing spelling `Succeded`.
- Executions open as Waiting; the running callback is optional, so a run can
  finish without a Running notification.
- Completion callbacks on a finished row return that row unchanged and still
  broadcast an updated notification. Consumers can receive the same state again.
- The running callback currently writes Running even if the execution was
  terminal. Do not assume monotonic transitions. This is a recorded discrepancy
  with its existing HTTP description, not a new behavior introduced by AsyncAPI.

Notifications carry state, rather than a guaranteed distinct transition record.
Replacing the known entity by ID handles repeated notifications, but does not
provide version-based reconciliation of concurrent HTTP responses and events.

## Reconnecting and recovering state

The frontend uses two separate connections to this shared stream: one in
`useTasks`, another in `AgentExecutionsProvider`. Both retry after close using a
fixed 3000 ms delay by default, close on error, and cancel retries on unmount.
They do not use exponential backoff. Reconnection is implemented by the clients,
not by a server delivery guarantee.

### Tasks

`GET /api/tasks/active` returns Queued/Running tasks. The task hook calls it on
mount and on every socket open, including reconnections, then replaces its
local array. This can recover active rows but not finished task history.

An in-flight HTTP snapshot can arrive after a newer event and overwrite local
state; there is no versioned merge. Events also lack HTTP-only repository fields,
so consumers should distinguish the HTTP and WebSocket representations.

### Agent executions

`GET /api/agent-executions/{id}` returns current state for a known ID. Keep IDs
returned by HTTP start operations if recovery is required. There is no registered
execution-list endpoint for discovering executions missed during disconnection.

The current agent provider starts empty and does not fetch state on initial
connection or reconnection. Its existing state remains in memory across reconnects,
but events missed while disconnected are not recovered. After a reload, older
runs cannot be discovered from this stream alone.

## Errors, heartbeats and closing

The application defines no error-event payload, heartbeat message, ping timer,
custom close-code catalog or application frame-size policy. WebSocket libraries
still implement their underlying protocol behavior. Treat browser `error` and
`close` events as transport signals, not documented domain messages.

Stop reconnect timers and close the socket when the consumer is disposed.
Lifecycle changes and domain failures are initiated or reported through the
HTTP API; a Failed task/execution notification is an entity-state message, not
a transport error response.

## Documentation workflow

Edit the TypeScript contracts or `asyncApiMetadata.ts`, then run from `backend/`:

```bash
pnpm run docs:ws:generate
pnpm run docs:ws:validate
pnpm run docs:ws:check
```

Connection and recovery explanations are also embedded in the generated
AsyncAPI document. Run `pnpm run docs:ws:prepare` and restart the backend after
changing contracts to refresh the served document. See
[the backend index](README.md) for related HTTP flows.
