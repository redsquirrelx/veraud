# Structured execution errors

`AgentExecution.errorDetail` is an optional incident object, persisted in the nullable
`agent_execution.error_detail` column. Internal invocation receipts retain the same
object under `error_detail` in their existing receipt storage.

Fields: `agentId`, `invocationId`, `occurredAt` (ISO 8601 timestamp or null), `code`,
`exceptionType`, `message`. Source identity and time are preserved when a parent
forwards a child incident. No exception type or incident date is inferred from
historical messages or execution completion dates.

- Completion callbacks accept `errorDetail`; invocation callbacks accept `error_detail`.
- HTTP execution lookups, project audit summaries and WebSocket events expose the data.
- Compact monitor projections retain incidents without requiring full reports or evidence.
- Duplicate/stale terminal callbacks return stored metadata unchanged. Omitted/null details
  cannot erase a previously recorded incident. Terminal records are not retroactively enriched.
- Backend dispatch failures record `backend_dispatch_failed`, backend identity and detection
  time with a safe description. Unconfirmed audit outcomes use `audit_outcome_unconfirmed`;
  this is a communication incident, not evidence of agent failure.
- Completed/delivery and cancellation semantics are unchanged. Public error text is
  now controlled; unverifiable historical descriptions are withheld. See
  [execution error privacy](execution-error-privacy.md) for the policy and code references.
- Legacy rows remain null; partial coverage or cancellation alone does not synthesize an error.

Apply before deploying code that queries the new column, from `backend/`:

```sh
pnpm prisma migrate deploy
pnpm prisma generate
```

Migration: `20261030010000_execution_error_details`. It adds a nullable column only;
existing executions, results, usage and receipts are not rewritten.
