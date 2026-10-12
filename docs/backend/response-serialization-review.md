# Response serialization review

Step 5 of the backend OpenAPI integration, reviewed on 2026-10-11.

## Method

Response schemas are used by Fastify's serializer, so the audit compares actual
controller payloads against emitted HTTP JSON, independently of the schema
definitions. The baseline is `JSON.parse(JSON.stringify(payload))`, reproducing
the previous JSON behavior, including Date-to-ISO conversion.

`backend/src/tests/helpers/responseSerializationAudit.ts` captures payloads in
`preSerialization`, compares the emitted bodies in `onSend`, and fails the test
application's close hook if any fields or values differ. It also checks that
204 responses remain empty. These hooks are installed only in tests.

The audit is attached to the existing integration suites for project registration,
listing, synchronization, Git/file operations, analysis and versions, AI-provider
CRUD, agent executions and status, plus the task-controller contract test.
These suites exercise the 27 explicit HTTP operations with real controllers,
response schemas and, for integration suites, database repositories.

The checker has regression tests proving that an incomplete response schema is
detected when it silently removes a controller field. Normal dates, nulls and
empty 204 responses are accepted.

## Findings

No serialization changes were detected in the exercised responses. No production
schema corrections were required by this review.

| Area | Checked behavior |
| --- | --- |
| Projects | Registration's small initial snapshot; full list/sync fields; nullable branch/hash/sync date; non-null dates as ISO strings |
| Git and files | Complete branch/tree/commit arrays; currentBranch/detachedHash; taskId; file path/content/byte size |
| Analysis and versions | versionId/evaluationId; nested execution; nullable version fields and lifecycle dates; derivedStatus |
| AI providers | Nested models and credentials; inUse flags; masked key previews; create/update results and empty DELETE bodies |
| Tasks | Repository names, description, command, status, kind and nullable exitCode; null legacy commands and recorded command strings |
| Agent executions | Waiting/Running/Completed/Failed; nullable evaluation/result/error/usage/dates; populated completion results and token counts; duplicate callbacks |
| Errors | Domain message/error forms and emitted Fastify validation payloads preserved |
| Status | online/offline/unknown availability states with the existing successful HTTP response |

Internal database fields are intentionally absent from public controller payloads
and schemas. API keys remain masked before serialization. Project states stored
as general strings remain general strings in public project/version schemas;
the existing task success spelling `Succeded` is preserved.

## Verification

- Full backend suite: 156 tests passed.
- Backend TypeScript: passed.
- Backend lint: passed.

The audit remains part of the suites to catch future schema changes that silently
drop fields. Its guarantees cover the response scenarios exercised by those
tests, not all possible database contents.
