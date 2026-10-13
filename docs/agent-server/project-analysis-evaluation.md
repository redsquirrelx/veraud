# Project Analysis Verification and Evaluation

For the subsequent reduced workflow and real-model measurements, see
[simplification results](project-analysis-simplification-results.md). The findings
below describe the earlier baseline verification and its provider failures.

## Verification recorded on 2026-10-12

The end-to-end scripted graph checks cover source/tool routing, complete/partial/failed
results, multiple targets and history removal, bounded corrections/repairs, evidence
that was never delivered, synthesis additions, budget preservation, adaptive follow-ups,
external cancellation, provider retries/terminal stopping, and resource cleanup.
A fixture deliberately describes contradictory behavior in `README.md`; that text
does not enter the investigation or alter the source-backed result.

The complete agent-server test suite passed: **233 tests**. Targeted Ruff checks
cover the new project-analysis modules, runner, and tests.

## Six-case offline evaluation

Command, from `agent-server`:

```powershell
.venv\Scripts\python.exe -m server.run_project_analysis --evaluate-workspace --smoke --max-investigations 2 --repeat 2 --quiet
```

| Case | Repetitions | Result | Statement/status stability | Citation validity |
| --- | ---: | --- | --- | ---: |
| PyShop | 2 | partial | stable | 1.0 |
| Hexagonal Python | 2 | partial | stable | 1.0 |
| Mario | 2 | partial | stable | 1.0 |
| GitFolio | 2 | partial | stable | 1.0 |
| Hexagonal TypeScript | 2 | partial | stable | 1.0 |
| FastAPI | 2 | partial | stable | 1.0 |

The 12 runs used 96 scripted model invocations and 48 repository tool calls.
These are offline invocations, not paid provider calls. Source citation rate was
1.0 and reference-functionality location/component overlap was 0.0, as expected
for the deliberately nonsemantic smoke model. These numbers verify protocol and
traceability, not responsibility/flow correctness or handoff usefulness.

## Explicit real-provider runs

The initial limited PyShop run generated a valid plan, executed two repository
queries, and stopped on a provider `ClientError`. It retained a diagnosable failed
result: three logical/provider attempts, two tool calls, 2,063 retrieved characters,
and approximately 29.16 seconds. No substantive validated findings were available.

A subsequent explicit six-case real-model evaluation used one investigation per
case, at most 12 logical model calls, a 120-second per-case timeout, no retries,
and a shared 12-second request interval. All six returned structured failures;
there were seven logical model calls and zero tool calls. A targeted diagnostic
planning run then confirmed `ClientError (HTTP 429)` from the configured Google
provider. No additional provider retries were attempted after that diagnostic.

The real-provider evaluation therefore does not establish functional accuracy,
semantic citation sufficiency, production readiness, or useful architect handoff.
Token/cost totals for failed calls are unknown, not zero.

## Semantic review status

Evaluation infrastructure and pinned annotations are implemented. Full real-model
semantic evaluation and calibration are **blocked by provider availability**.
Rerun the documented commands once the configured provider accepts requests.
Assess each annotated responsibility/flow and every supported claim against source;
record semantic errors separately from structural citation validity. Establish
acceptance thresholds against the baseline pipeline before asserting readiness.

Current implementation limits include static extraction omissions, bounded planning
catalogs and target count, incomplete runtime/call resolution, immutable-ID rather
than semantic synthesis deduplication, and model interpretation errors that cannot
be rejected merely by checking reference shape or source access.
