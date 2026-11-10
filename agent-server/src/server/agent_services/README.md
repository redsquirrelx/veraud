# Agent services

Cross-cutting services for investigators, coordinators and managers. These are not
domain agents or general application services. They may be composed by the app,
but must not import `server.app`, `server.api` or concrete agent implementations.

## Execution tracking

`execution_tracking.ExecutionObserver` unifies lifecycle notifications
(`mark_running`, `progress`, `invocation`, `complete`) with activity capture
(`scope`) and acknowledged delivery (`flush`). `default_callback_sink()` builds
the observer with the existing backend transport when a backend is configured.
Application startup retains one delivery worker; do not start one per agent.

```python
from server.agent_services.execution_tracking import ExecutionObserver

observer = ExecutionObserver(sink)  # Injectable backend port; None disables tracking.
with observer.scope(execution_id):
    await observer.mark_running(execution_id)
    result = await agent.run(tools, request)
    # Report progress/outcome with the existing typed wire contracts as appropriate.
await observer.flush()  # Also delivered by the application-level worker.
```

Capture is inherited by child tasks/tools, including V2 graph nodes. Activity
records identities, timings, statuses and allowed metrics, not prompts, source
content, responses or exception text. Notification and event HTTP endpoints,
payloads, retries and acknowledgement semantics are unchanged. The observer does
not duplicate lifecycle notifications as additional invocation records.

With `ExecutionObserver(None)`, notifications are no-ops and `scope` suppresses
capture, including inside an inherited active scope. Existing standalone runs
without a backend execution ID retain no history. Low-level `execution_event_scope`
remains available for explicit instrumentation/tests: with an ID it buffers even
without a transport. Such callers must arrange delivery themselves.

The outbox is volatile, not local durable history. Only acknowledged events are
removed. Backend outages retain pending events for retry; the existing 10,000-event
bound still raises `BufferError` rather than silently dropping history. Process
exit loses unacknowledged events. No local persistence mode is introduced here.

Canonical modules:

- `observer.py`: unified facade, callback port and backend factory.
- `events.py`: task-local capture and LangChain/native runtime instrumentation.
- `buffer.py`: bounded outbox and shared delivery worker.
- `callback/`: HTTP transport and existing wire schemas.

Old `infrastructure.execution_events`, `infrastructure.execution_event_buffer`,
`infrastructure.callback.{client,schemas}` and `app.callback_port` imports are
same-module compatibility aliases, not additional implementations. Production
consumers use `agent_services` directly.

## Budgeting and consumption

[`budgeting/`](budgeting/README.md) owns the global `budgets_enabled` switch,
hierarchical token and retrieval ledgers, execution timing and resource metrics.
Accounting remains active when enforcement is disabled. There are no per-agent
`unlimited_*` switches. Pacing and provider RPM/TPM quotas stay separate in their
existing infrastructure. Tracking observes consumption; it does not enforce it.
