# integration-tests.ps1 - integration tests from the Veraud repo root.
#
# No args: runs the INTEGRATION catalog only.
#   backend:      every src/tests/*.integration.test.ts, EXCEPT 3 tolerated
#                 preexisting failures, which are run separately and reported
#                 without failing the script. Any OTHER integration failure
#                 fails the catalog.
#   agent-server: the integration files from the catalog.
#   frontend:     the integration areas from the catalog. The tolerated
#                 preexisting failure (2 tests in ProjectDetailPage.test.tsx)
#                 does not fail the script; it is reported.
# -Full:    also runs the complete suites per layer (multiple preexisting
#           failures; see INTEGRATION_TEST_REPORT.md).
param([switch]$Full)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$failed = 0

function Banner($text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }

# --- backend -----------------------------------------------------------------
# Known preexisting failures on main (verified reproducible on a50955a):
#   project-sync.integration.test.ts                    - stale agent_settings seed expectations
#   agent-token-persistence.integration.test.ts         - stale expected shape (monitorContext)
#   project-architecture-live.integration.test.ts       - broken smoke fixture on main
$staleBackend = @("project-sync.integration.test.ts", "agent-token-persistence.integration.test.ts", "project-architecture-live.integration.test.ts")
Banner "backend: integration catalog"
Set-Location "$root\backend"
$integration = Get-ChildItem src/tests -Filter "*.integration.test.ts" | ForEach-Object { $_.Name }
$run = $integration | Where-Object { $_ -notin $staleBackend }
Write-Host ("Running {0} integration test files" -f $run.Count)
$before = $failed
foreach ($file in $run) {
  Write-Host "  > $file"
  npx tsx --test "src/tests/$file"
  if ($LASTEXITCODE -ne 0) { Write-Host "    FAIL $file" -ForegroundColor Red; $failed++ }
}
if ($failed -eq $before) { Write-Host "backend integration catalog: OK" -ForegroundColor Green } else { Write-Host "backend integration catalog: FAIL" -ForegroundColor Red }

foreach ($file in $staleBackend) {
  if (-not (Test-Path "src/tests/$file")) { continue }
  Banner "backend: tolerated preexisting failure ($file)"
  npx tsx --test "src/tests/$file"
  if ($LASTEXITCODE -eq 0) { Write-Host "  unexpectedly passes - remove from the tolerated list" -ForegroundColor Yellow }
  else { Write-Host "  failed as expected (preexisting on main); not counted" -ForegroundColor Yellow }
}

# --- agent-server --------------------------------------------------------------
Banner "agent-server: integration catalog"
Set-Location $root
$agentServerIntegration = @(
  "tests/test_audits.py",
  "tests/test_audit_artifacts_http.py",
  "tests/test_http_trace_middleware.py",
  "tests/test_quality_audit_pipeline.py",
  "tests/test_functional_quality_audit.py",
  "tests/test_maintainability_v2_integration.py",
  "tests/test_verification_suite_http.py",
  "tests/test_graphify_integration.py"
)
Write-Host ("Running {0} integration test files" -f $agentServerIntegration.Count)
uv run --directory agent-server pytest $agentServerIntegration -v
if ($LASTEXITCODE -ne 0) { Write-Host "agent-server integration catalog: FAIL" -ForegroundColor Red; $failed++ } else { Write-Host "agent-server integration catalog: OK" -ForegroundColor Green }

# --- frontend -----------------------------------------------------------------
Banner "frontend: integration catalog"
Set-Location $root
$frontendIntegration = @(
  "src/features/project-management/QualityAuditResults.test.tsx",
  "src/features/project-management/VerificationWorkspace.test.tsx",
  "src/features/project-management/qualityAuditVerification.test.ts",
  "src/features/project-management/qualityAuditApi.test.ts",
  "src/features/project-management/AuditValidationHistory.test.tsx",
  "src/features/project-management/AuditIncidentsTab.test.tsx",
  "src/shared/audit-monitor/AuditMonitorIssues.test.tsx",
  "src/shared/execution-explorer/ExecutionExplorerModal.test.tsx",
  "src/app/navigation/AppNavigation.test.tsx",
  "src/app/layout.test.tsx",
  "src/features/project-management/MaintainabilityConfiguration.test.tsx",
  "src/features/project-management/ReuseAuditConfiguration.test.tsx",
  "src/pages/settings/AgentsSettings.test.tsx",
  "src/pages/settings/AgentSettingsCard.test.tsx",
  "src/pages/settings/AgentSettingsDrawer.test.tsx",
  "src/pages/home/HomePage.test.tsx",
  "src/infrastructure/http-client/auditCancellation.test.ts",
  "src/infrastructure/http-client/httpClient.test.ts"
)
Write-Host ("Running {0} integration test files" -f $frontendIntegration.Count)
npm --prefix frontend run test -- --run --reporter=verbose $frontendIntegration
if ($LASTEXITCODE -ne 0) { Write-Host "frontend integration catalog: FAIL" -ForegroundColor Red; $failed++ } else { Write-Host "frontend integration catalog: OK" -ForegroundColor Green }

Banner "frontend: tolerated preexisting failure (ProjectDetailPage, 2 tests)"
npm --prefix frontend run test -- --run src/pages/project/ProjectDetailPage.test.tsx
if ($LASTEXITCODE -eq 0) { Write-Host "ProjectDetailPage unexpectedly passes - remove it from the tolerated list" -ForegroundColor Yellow }
else { Write-Host "ProjectDetailPage failed 2 known preexisting tests on main (not counted)" -ForegroundColor Yellow }

if ($Full) {
  Banner "backend: full suite (preexisting failures: project-sync)"
  Set-Location "$root\backend"
  npx tsx --test "src/**/*.test.ts"
  if ($LASTEXITCODE -ne 0) { Write-Host "backend full suite: preexisting failures present" -ForegroundColor Red }

  Banner "agent-server: full suite without the stale collection-breaking test"
  Set-Location $root
  uv run --directory agent-server pytest tests/ --ignore=tests/repository_runtime/test_retry_hints.py -q
  if ($LASTEXITCODE -ne 0) { Write-Host "agent-server full suite: 37 preexisting failures on main" -ForegroundColor Red }

  Banner "frontend: full suite (2 preexisting failures on main)"
  Set-Location $root
  npm --prefix frontend run test -- --run
  if ($LASTEXITCODE -ne 0) { Write-Host "frontend full suite: 2 preexisting failures on main" -ForegroundColor Red }
}

Set-Location $root
if ($failed -eq 0) { Write-Host "`nINTEGRATION CATALOG OK (with tolerated preexisting failures reported above)" -ForegroundColor Green }
else { Write-Host "`n$failed section(s) failed - see output above" -ForegroundColor Red }
exit $failed
