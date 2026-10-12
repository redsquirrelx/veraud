/** Authored connection/documentation metadata, separate from event contracts. */
export const asyncApiMetadata = {
  asyncapi: "3.1.0",
  id: "urn:veraud:backend:websocket",
  info: {
    title: "Veraud Backend WebSocket API",
    version: "1.0.0",
    description: [
      "Backend perspective of the shared WebSocket event stream for Git tasks and agent executions. Contracts and examples are generated from the same TypeScript schemas used to derive producer event types.",
      "## Connection\nConnect to `/ws` on the backend host and port using native WebSocket (not Socket.IO). Use `ws` for an HTTP backend or `wss` for a TLS-terminated HTTPS deployment. The development server entry is an editable example, not automatic origin discovery. The backend route does not configure TLS.",
      "The HTTP upgrade uses GET. The application declares no authentication requirement, query parameters or WebSocket subprotocol. HTTP CORS configuration is not a WebSocket authorization policy. No subscribe, acknowledgement or client-command messages are implemented.",
      "## Delivery\nEvery connected client receives all event types as JSON text. Opening the connection sends no greeting, initial snapshot or replay. Notifications describe entity state, not uniquely identified transitions. Messages carry no sequence number, replay cursor or acknowledgement. Events missed during disconnection cannot be replayed, and exactly-once delivery is not guaranteed.",
      "## Recovery\nTasks can be recovered with GET `/api/tasks/active`, which returns only Queued/Running rows. The current task hook fetches on mount and on each socket open; its HTTP response can race with notifications. Executions can be recovered by known ID through GET `/api/agent-executions/{id}`. The current agent provider does not fetch initial or reconnect snapshots, and there is no execution-list endpoint to discover missed runs.",
      "Both frontend consumers reconnect after close with a fixed 3000 ms delay by default, close on error and stop retrying on unmount. This is client behavior, not a server retry or replay guarantee. No application heartbeat, ping schedule, error message or custom close-code catalog is defined.",
      "## Shared channel `/ws`\nOne physical WebSocket connection carries all three message types; operation IDs do not create separate subscriptions. Dispatch by the top-level `type` field and reconcile entities by task.id or execution.id. Those identifiers identify entities, not individual messages.",
      "Broadcasts are sent to all connected sockets. WebSocket preserves send order within a live connection, but tasks and executions may interleave, and the application defines no ordering across reconnects. Send failures are logged without an application retry or delivery acknowledgement.",
      "## Entity lifecycle\nRepeated completion callbacks emit another execution update even when the stored row is unchanged. The running callback currently writes Running without guarding terminal states, so consumers must not assume status transitions are monotonic or that each update represents a new transition.",
      "Task lifecycle: Queued ΓåÆ Running ΓåÆ Succeded or Failed (Succeded is the existing spelling). The running callback for an execution is optional: a run can go from Waiting directly to Completed or Failed. No initial state or history is sent on connection; recover available state through HTTP.",
    ].join("\n\n"),
    license: { name: "ISC" },
  },
  defaultContentType: "application/json",
  servers: {
    development: {
      host: "{hostname}:{port}",
      protocol: "ws",
      description: "Local backend connection. Replace the hostname and port with your backend address. For a TLS-terminated deployment, use wss and its external host and port; this example does not configure TLS or discover the current origin.",
      variables: {
        hostname: {
          default: "localhost",
          description: "Backend hostname, without a URL scheme or path.",
        },
        port: {
          default: "7501",
          description: "Backend listening port.",
        },
      },
    },
  },
  channels: {
    realtime: {
      address: "/ws",
      title: "Backend realtime stream",
      servers: [{ $ref: "#/servers/development" }],
      bindings: { ws: { method: "GET", bindingVersion: "0.1.0" } },
    },
  },
} as const
