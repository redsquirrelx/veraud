# Project Analysis Agent and Runner

The new analyst is an independent, in-memory LangGraph workflow. It runs deterministic
target selection, restricted model/tool investigation, finding validation, bounded
adaptive follow-ups, and deterministic report assembly. The retained model-planning
and model-synthesis analyst is available with `--baseline` for comparisons.

## Run a selected checkout

For the small representation-backed agent, use `--orientation`; see
[project orientation](project-orientation.md). This mode uses at most four model
calls and six tools and returns a small orientation rather than the full analyst report.

From `agent-server`, using `uv` and the existing environment:

```powershell
uv run --no-sync python -m server.run_project_analysis ../appdata/workspace/199836402-thisishaykins-PyShop
```

From the repository root:

```powershell
uv run --project agent-server --no-sync python agent-server/src/server/run_project_analysis.py appdata/workspace/199836402-thisishaykins-PyShop --json
```

To synchronize the environment and run the installed console entrypoint, from
`agent-server`:

```powershell
uv run project-analysis ../appdata/workspace/199836402-thisishaykins-PyShop
```

The installed console entrypoint is `project-analysis`. The default model/provider
come from the existing analyzer development configuration. Credentials come from
`LLM_API_KEY` in the environment or repository `.env`, or explicit `--api-key`.
Importing the runner and using offline mode do not require server settings.

```powershell
uv run --no-sync python -m server.run_project_analysis ../appdata/workspace/199836402-thisishaykins-PyShop --provider google --model gemini-3.5-flash-lite --max-investigations 4 --max-model-calls 24 --max-tool-calls 60 --timeout 600 --request-interval 12
```

`--plan-only` selects scope without provider calls; `--baseline --plan-only` runs
the retained standalone model planning subgraph. `--json` emits the structured result to
stdout. Progress uses stderr; `--quiet` suppresses it. `--handoff` emits a validated
`ArchitectureAnalysisInput` for the same snapshot. `--compact-handoff` emits an
`ArchitectureBrief` with immutable functional facts, cited provenance, outcomes,
coverage, and unresolved questions, without candidate audits or model history.
The future architect must verify material claims through the same snapshot tools.
`--trace` uses configured
LangSmith tracing. Nothing writes snapshots, source, reports, or evaluation files
automatically; redirect stdout explicitly if an export is wanted.

Progress is detailed by default and flushed immediately. It includes snapshot
preparation/counts, model/provider identity, planning completion, target number and
priority, model turns and request attempts, pacing/backoff waits, tool names and
source paths, retrieval usage, finding acceptance/corrections, report validation,
and resource cleanup. Model prompts and responses are not printed.

During asynchronous waits, a `still_running` message appears every five seconds
with the current activity, its duration, and total elapsed time. Configure the
interval with `--progress-interval`; `--quiet` disables events and heartbeats.
JSON output remains on stdout, with progress on stderr.

For `provider_wait`, heartbeats include the planned wait, remaining seconds,
attempt/call, HTTP status when available, and the next action. Retry events
distinguish local backoff from provider `Retry-After` hints. The initial pacing
reason is `request_pacing_or_shared_cooldown`, because workspace cases share a
pacer. A long provider-requested cooldown can exceed `--retry-backoff`; it is
still subject to the execution timeout. `provider_wait` means no new request has
been sent yet; `provider_request` means the request is now in flight.

If the requested retry wait exceeds the remaining analysis time, the runner emits
`provider_retry_skipped` with both durations and returns a structured provider
failure immediately. It does not shorten `Retry-After` to send an early request
or leave that impractical cooldown in the shared workspace pacer.

```powershell
uv run --no-sync python -m server.run_project_analysis ../appdata/workspace/199836402-thisishaykins-PyShop --progress-interval 3 --json
```

## Offline protocol verification

```powershell
uv run --no-sync python -m server.run_project_analysis ../appdata/workspace/199836402-thisishaykins-PyShop --smoke --max-investigations 2 --json
```

`--smoke` uses a scripted protocol model. It retrieves retained technical source
and verifies the graph/tool/citation/report contract. It returns `partial` with
explicit limitations and unanswered functional questions: it is not a semantic
project analysis. It needs no credentials and makes no provider calls.

## Runtime and validation

See [context and usage telemetry](project-analysis-telemetry.md) for per-call
composition, stage-level token usage, correction/repeated-query measurements,
and reproducibility metadata. Local token estimates are separate from provider usage.

- `ProjectAnalysisAgent(model).run(tools)` accepts a caller-owned asynchronous
  text model and a fresh `RepositoryToolset` for each execution. No checkpointer
  or automatic persistence is configured.
- Tools bind to the selected direct checkout child of `appdata/workspace`.
  `--workspace-root` is trusted host configuration, not a model tool argument.
  Narrative documentation is excluded, including indirect symbol/evidence access.
- Each investigation has its own history and source-access ledger. Old target
  messages are removed explicitly. Prior accepted findings are bounded context.
- New supported behavioral claims require source evidence accessed during the
  active investigation. Structural imports and declared integrations may cite
  technical metadata; inspected usage requires implementation evidence.
- Entity/reference validation does not establish semantic correctness. A cited
  comment, docstring, or irrelevant implementation can still be misinterpreted;
  annotated review assesses sufficiency separately.
- Completed orientation requires project identification or explicit unanswered
  orientation questions. Scope completion is distinct from resolving every question.
- Follow-ups enter the plan only after origin/reference validation, priority,
  duplicate, and budget checks. Repeated proposals do not create unbounded loops.
- Accepted records are immutable. Deterministic assembly deduplicates exact IDs;
  distinct records and conflicting claims remain visible. No model copies, selects,
  or rewrites accepted IDs in the default workflow. Independently valid records
  can survive rejected fields or a token stop; their investigation remains incomplete.
  A singleton object where an object-array is required is wrapped deterministically;
  no facts, IDs, primitive values, or evidence are invented to repair a response.
- The investigator receives objective-specific type contracts and bounded recent
  unique tool results, a query ledger, relevant components, and field-level errors.
  Omitted history is explicit. Equivalent compact queries reuse in-memory results;
  provenance is registered separately for each delivered response.
- Coverage, snapshot identity, outcomes, and evidence are assembled deterministically.
  Failed results retain the accepted plan, validated findings, and retrieval ledger
  even if no final report can be produced.
- Only a valid report can be converted to architecture input. The future architect
  must query the same snapshot and verify material analyst claims directly.

### Limits and operational behavior

Runner default limits are 6 investigations, 24 logical model calls, 100 tool calls,
150,000 retrieved characters, and 600 seconds after snapshot/context preparation.
No model calls are reserved for reporting. Each target permits six model turns;
each turn permits four tools. One finding correction is allowed by default.
Compact source responses have at most 80 lines/2,200 characters with actual ranges
and truncation, and pages at most 25 items. Full retained source remains queryable.
Library callers can supply independent investigation/tool limits.

Token defaults: `--max-total-tokens 60000`, `--max-input-tokens 6000`,
`--max-objective-tokens 20000`, `--max-tokens 3000` (provider output ceiling).
Request admission uses a conservative input estimate (at least 0.45 tokens per
serialized character, calibrated upward from reported usage) plus the output
ceiling. Retries also require admission. `accounted_tokens` combines reported
usage and conservative reserves for attempts without usage; `estimated_tokens`
identifies the estimated portion. This operational estimate is separate from
telemetry's `ceil(characters / 4)` diagnostic estimate. Unknown actual usage stays
null. These are admission limits, not guaranteed exact provider billing ceilings.
`usage.reported_input_tokens` and `usage.reported_output_tokens` always expose the
available provider counts; `usage.unknown_usage_attempts` explains incomplete
totals. Reported counts exclude unmeasured consumption and are not full-run totals
when any attempt is unknown. The readable output shows these counts as well.
Budget exhaustion preserves valid facts and finalizes deterministically.

```powershell
uv run python -m server.run_project_analysis ../appdata/workspace/1373928788-Cesar-Sanchez-sof-Polleria --max-investigations 4 --max-total-tokens 60000 --max-objective-tokens 25000
```

Provider attempts and retries are accounted separately from logical model calls.
Transient transport/408/429/5xx failures use bounded shared pacing/backoff; terminal
failure stops further model use for that execution. HTTP status is reported without
printing credentials or provider response bodies. Token totals remain null if the
provider does not supply usage for every call. Gemini calls honor sampling/output
limits and request JSON output. External cancellation propagates and the runner
closes its owned provider clients in `finally`.

`complete` means the accepted planned scope finished with a valid report;
`partial` means a valid report has unfinished scope or recorded execution issues;
`failed` means no valid report was produced. Deferred candidates remain visible.
Exit codes: `0` valid report/plan (including partial), `1` structured failure or
missing repository, `2` configuration/scope error, `130` cancellation.

## Workspace evaluation

The evaluator consumes the six pinned cases in `agent-server/benchmarks/workspace.yaml`.

```powershell
uv run --no-sync python -m server.run_project_analysis --evaluate-workspace --smoke --max-investigations 2 --repeat 2
uv run --no-sync python -m server.run_project_analysis --evaluate-workspace --max-investigations 4 --max-model-calls 24 --timeout 600 --request-interval 12 --json
uv run --no-sync python -m server.run_project_analysis --evaluate-workspace --case pyshop --repeat 2 --input-price 0.25 --output-price 1.50 --json
```

Prices are explicitly supplied USD per million tokens, not assumed current rates.
Unknown prices or token counts yield null estimated cost. Repetition stability is
null with one run; with repeated runs it compares accepted statement/status hashes.
It does not measure semantic equivalence or guarantee model determinism.

JSON contains the complete result, reference annotations, claims, citation ranges,
review questions, usage, reference-commit check, and structural metrics. Source-location
overlap and file coverage are proxies; they do not score semantic correctness.
Reference coverage is not scored when the pinned commit does not match.

Review supported claims against their actual source for responsibility/flow correctness,
source sufficiency, runtime wiring, unanswered questions, and usefulness for architectural
investigation. An HTTP/quota failure is an operational result, not a quality score.
See [the recorded verification](project-analysis-evaluation.md).
