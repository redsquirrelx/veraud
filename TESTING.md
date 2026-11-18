# Running the tests — Veraud

All suites are local; no CI workflow is committed in this repository yet (quality gates are manual).

## Current state of integration tests

| Layer | Command | Existing integration tests |
|---|---|---|
| backend | `npx tsx --test "src/**/*.test.ts"` (from `backend/`) | 20 files in `backend/src/tests/` (Fastify inject + SQLite via `prisma migrate deploy` + stubbed agent-server boundary). **Preexisting failure**: `src/tests/project-sync.integration.test.ts` (stale — expects hard-coded `agent_settings` seed removed in the catalog refactor) |
| agent-server | `uv run --directory agent-server pytest tests/ -q` | pipeline and HTTP lifecycle tests; skip stale: `--ignore=tests/repository_runtime/test_retry_hints.py`. **Preexisting**: failures in `test_modularity_v2_plan_assessment.py`, `test_architecture_boundary_*.py`, `test_functional_audit_configuration.py`, `test_security_audit.py`, `test_openapi_contracts.py`, `test_project_architecture_definition.py`, `test_execution_failures.py`, `test_finding_resolution_scenarios.py`, `test_modularity_v2_plan_assessment.py` — see INTEGRATION_TEST_REPORT.md |
| frontend | `npm --prefix frontend run test -- --run` (vitest) | component-level integration; e2e via `e2e/` (Playwright) |
| e2e | `npm --prefix e2e run test` | black-box: real frontend/backend/agent-server, mocked and `:live` variants |

## New integration tests added in this pass (not yet committed)

- backend `src/tests/verification-suite.integration.test.ts` — verification-suite endpoints through real app wiring (Fastify + SQLite + artifact store on disk)
- backend `src/tests/credential-boot.integration.test.ts` — boot-time credential migration onto SQLite and fail-closed on corrupted master key (DPAPI; Windows-only, self-skips elsewhere)
- backend `src/tests/trace.integration.test.ts` — audit lifecycle trace written to `workspaceDir/logs` as NDJSON; `VERAUD_TRACE_ENABLED=0` disables it
- backend `src/tests/tasks.integration.test.ts` — `GET /api/tasks/active` filter/order/field mapping
- agent-server `tests/test_verification_suite_http.py` — verification suite HTTP lifecycle (create → poll → download), real artifact store/git, LLM stubbed
- agent-server `tests/test_http_trace_middleware.py` — `x-veraud-trace-*` headers drive NDJSON trace for HTTP requests, error paths included
- agent-server `tests/test_audit_artifacts_http.py` — production artifact publish → HTTP read roundtrip with byte-level integrity enforcement; corrupted store → 404
- frontend `src/features/project-management/qualityAuditVerification.test.ts` — verification-suite HTTP layer (request/poll/download), error mapping

Run the full report: INTEGRATION_TEST_REPORT.md
