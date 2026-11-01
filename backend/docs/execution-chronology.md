# Execution history

## Source and persistence

`agent-server/src/server/contracts/execution_event.py` defines content-free events:
UUID, stream, monotonic sequence, occurrence time, audit/invocation/parent identities,
action/parent-action identities, source/tool-call identity, kind, status, and allowlisted numeric metrics.
No prompts, responses, tool arguments, credentials or exception messages are retained.

`agent-server/src/server/infrastructure/execution_events.py` observes LangChain/LangGraph
through its public configure hook, independently of LangSmith. Existing graphs,
nodes, models and routes are not rewritten. Correlated start/end pairs distinguish
each attempt, including repeated nodes and invocations. Shared repository tools
also record attempts rejected before charging budgets. Native tool wrappers and
repository execution are separate instrumentation layers, not additional token usage.
The security adapter uses one generic proxy for its non-LangGraph components;
the scanner implementations themselves are unchanged.

`agent-server/src/server/infrastructure/execution_event_buffer.py` assigns sequences
under a thread lock and queues events temporarily in memory for asynchronous delivery.
Agent-server writes no execution-history files or databases. Only backend stores
history durably, in Prisma. Acknowledged batches are removed from memory; ambiguous
responses retry the same IDs with bounded backoff while the process remains alive.
Pending events do NOT survive a restart. The buffer holds at most 10,000 events;
when full, recording raises rather than silently dropping history or growing without
bound. Instrumentation requires a backend-owned execution ID; standalone runs without
one are not buffered. There is no disk spool or local replay on startup.

## Backend API

`src/modules/agent-execution/execution-events.ts` exposes:

- `POST /api/agent-executions/:id/events`: batches of 1–100 events; transactional,
  append-only and idempotent. A replay cannot change payload, sequence, stream
  ownership or an established audit identity. Delayed events remain admissible
  after completion without reopening or changing the execution.
- `GET /api/agent-executions/:id/events?offset=0&limit=100`: paginated history
  (maximum 200), ordered by occurrence time, stream and source sequence. Returns
  source timestamps separately from backend receipt timestamps. Offset pagination
  is not a frozen snapshot: refresh from the beginning when late events arrive.

`prisma/schema.prisma` stores immutable events separately from mutable invocation
receipts; unique constraints protect event identity and per-stream sequence.
Apply `20261031000000_execution_events` with the project's migration deployment
workflow before enabling delivery. The working database is not migrated by tests.

## Coverage and limits

Captured boundaries: execution and invocation lifecycle, every instrumented graph
runnable, repeated phase entries, native and repository tool calls, native/text
model calls, gateway provider attempts/errors/retries, pacing/quota waits, timed
activities, knowledge publication and audit state changes (including cancellation).
Instrumentation preserves existing results, exceptions, deadlines and accounting.

This is an operational event history, not a Python statement/syscall profiler or
LLM token transcript. Third-party internals outside these boundaries are not traced.
An abrupt process death loses events not yet acknowledged by backend and can leave
a persisted start without its finish: display that as unconfirmed, not success.
Sequences order a source stream; wall-clock timestamps
cannot prove a total order between different machines with skewed clocks.
Old audits are not backfilled. The frontend DEMO is deliberately unchanged.

The new callback follows the application's existing callback trust/deployment
boundary. Event identity validation does not replace network-level authentication.
