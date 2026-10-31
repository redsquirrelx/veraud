# Execution error privacy

## Policy

Error messages are not made safe by replacing recognizable key patterns alone.
Public descriptions are reconstructed from a small host-owned code-to-message map.
Unknown/historical text is replaced with `Error details withheld because their safety
could not be verified.` No raw provider message, response body or traceback is used
as a fallback. Unknown codes become `execution_failed`; unknown exception names
become null. Operational identity and incident time remain separate from messages.

The initial codes are `execution_failed`, `execution_timeout`, `child_execution_error`,
`result_contract_invalid`, `backend_dispatch_failed` and `audit_outcome_unconfirmed`.
Changes to this public catalog must be reviewed and kept consistent across the
Python, backend TypeScript and frontend TypeScript maps referenced below.

## Changes and code references

| Protection | Implementation reference |
| --- | --- |
| Controlled descriptions and safe legacy fallback in Python | [`contracts/public_errors.py`](../../agent-server/src/server/contracts/public_errors.py): `MESSAGES`, `public_error_text`, `public_error_fields` |
| Ignore arbitrary structured descriptions, constrain codes/types and protect identifier fields | [`contracts/execution_error.py`](../../agent-server/src/server/contracts/execution_error.py): `ExecutionErrorDetail.public_values` |
| Sanitize completion and child receipt contracts before callbacks | [`infrastructure/callback/schemas.py`](../../agent-server/src/server/infrastructure/callback/schemas.py): validators on `ExecutionOutcome` and `InvocationReceipt` |
| Recheck outgoing callback payloads; do not log callback URLs, transport exception messages or rejected response bodies | [`infrastructure/callback/client.py`](../../agent-server/src/server/infrastructure/callback/client.py): `CallbackClient._post` |
| Keep audit lifecycle error text public and keep child attribution | [`app/audit_service.py`](../../agent-server/src/server/app/audit_service.py): `AuditService._update`; [`runtimes/invocation_reporting.py`](../../agent-server/src/server/runtimes/invocation_reporting.py): `observe_invocation` |
| Controlled HTTP failure responses and public JSON audit projections | [`api/executions.py`](../../agent-server/src/server/api/executions.py): `_http_error`; [`api/pipelines.py`](../../agent-server/src/server/api/pipelines.py): `_http_error`; [`api/audits.py`](../../agent-server/src/server/api/audits.py): validation handlers, `get_audit`, `get_audit_report` |
| Backend public policy, including error-bearing fields nested inside serialized results | [`security/public-errors.ts`](../src/infrastructure/security/public-errors.ts): `publicErrorText`, `publicErrorResult`, `publicErrorFields` |
| Reconstruct structured errors received from callbacks or historical storage | [`execution-error-detail.ts`](../src/modules/agent-execution/execution-error-detail.ts): `readExecutionErrorDetail`, `storedExecutionErrorDetail` |
| Sanitize before database writes and sanitize old errors on reads; preserve status, usage and incident timestamps | [`agent-execution.repository.ts`](../src/modules/agent-execution/agent-execution.repository.ts): `recordInvocation`, `complete`, `patchResult`, `toStored` |
| No exception text in dispatch/cleanup logs; public descriptions for backend failures | [`agent-execution.service.ts`](../src/modules/agent-execution/agent-execution.service.ts): `fail`, `attachDiagram` |
| Do not log configured connection URLs | [`agent-server.client.ts`](../src/infrastructure/agent-server-client/agent-server.client.ts): `run`, `runPipelineByName` |
| Independent final error-field protection before WebSocket serialization | [`realtime.gateway.ts`](../src/infrastructure/realtime-gateway/realtime.gateway.ts): `broadcast` |
| Protect project audit history/detail and JSON report sections, including historical rows | [`quality-audit.service.ts`](../src/modules/quality-audit/quality-audit.service.ts): `summary`, `reportSection`, `report` |
| Independent browser display policy, without requesting credential values | [`publicErrors.ts`](../../frontend/src/infrastructure/http-client/publicErrors.ts); [`executionErrorDetail.ts`](../../frontend/src/infrastructure/http-client/executionErrorDetail.ts): `readExecutionErrorDetail` |
| Protect the modal, incident collection, audit history/results and pipeline errors | [`ExecutionError.tsx`](../../frontend/src/shared/audit-monitor/ExecutionError.tsx); [`auditIncidents.ts`](../../frontend/src/features/project-management/auditIncidents.ts); `QualityAudits.tsx`, `QualityAuditResults.tsx`, `PipelineResult.tsx` in the same feature directory |

## Verification

Only fake values are used: an API key, a password, a Bearer token, and a URL with
userinfo/query credentials. No real provider runs, real secrets or working-database
migrations are needed.

- [`test_public_error_security.py`](../../agent-server/tests/test_public_error_security.py): outgoing root/child callbacks, rejected response bodies, transport logs, unknown codes/types.
- [`execution-error-details.integration.test.ts`](../src/tests/execution-error-details.integration.test.ts): actual HTTP root/child callbacks, database values, WebSocket events, historical HTTP projections and reconnects against temporary databases.
- [`audit-reconciliation.test.ts`](../src/modules/agent-execution/audit-reconciliation.test.ts): backend dispatch logs and unchanged reconciliation semantics.
- [`PublicErrorSecurity.test.tsx`](../../frontend/src/shared/audit-monitor/PublicErrorSecurity.test.tsx): legacy and forged structured messages cannot appear in modal HTML; the browser receives no secret-comparison configuration.
- Existing lifecycle, cancellation, pagination and modal tests now assert public descriptions rather than trusting arbitrary fixture messages.

## Compatibility and boundaries

- Existing historical database rows and logs are not destructively rewritten. Reads
  project public descriptions; new writes sanitize the recognized error fields.
- Incident presence, identity, dates, ordering, usage and cancellation semantics are
  retained. Descriptive text is deliberately less specific when its safety is unknown.
- This policy targets execution **error contracts**. It is not a general repository
  secret scanner: source evidence, prompts, arbitrary non-error output, binary Word
  artifacts and third-party tracing/logging need their own access/redaction policies.
  Opaque non-JSON `result` strings are preserved as output, not certified as messages.
  Parsed JSON projections fail closed: a sanitization failure never returns the
  unsanitized original JSON as a fallback.
- Identifier syntax/prefix checks are defense in depth, not a guarantee that arbitrary
  secret values can be recognized. Message safety comes from controlled templates.
- No frontend credential registry is introduced. If historical secrets were already
  exposed, rotate them and review retained logs/backups separately.
