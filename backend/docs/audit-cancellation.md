# Audit cancellation

`POST /api/projects/:id/audits/:auditId/cancel` returns HTTP 202 with the audit summary.
The audit must belong to the project and be a quality audit; otherwise it returns 404.
Repeated requests retain the first `cancellationRequestedAt`. Finished audits are unchanged.

Apply the migration with `pnpm prisma migrate deploy` and regenerate the client with
`pnpm prisma generate` before starting the backend.

## Lifecycle

- Persist the request before contacting agent-server. An atomic dispatch claim cannot
  succeed after the request is saved. Undispatched work can therefore be cancelled locally.
- A dispatched audit stays Waiting/Running with `auditStatus: cancelling` until its
  outcome is confirmed. Sending or acknowledging the request does not confirm termination.
- If `run_id` is not known yet, retain the request and deliver it after a running or
  invocation callback provides the identity. Do not replay the pipeline POST.
- Retry failed communication and resume persisted pending requests on backend startup.
  An unavailable or missing remote run is not proof of cancellation.
- On a confirmed cancelled snapshot, retain published records and recorded usage.
  Existing `agent-execution.updated` events carry the request timestamp and interruption reason.
- As in existing report delivery, `executionStatus: Completed` denotes a delivered
  outcome, not successful coverage: `auditStatus` and `interruptionReason` are `cancelled`.
  A concurrent normal terminal outcome is not overwritten by late cancellation callbacks.

The frontend connection is a separate phase. No new audit or provider execution is
started by requesting cancellation.
