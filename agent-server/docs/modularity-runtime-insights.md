# Modularity runtime: operational insights

## Investigators and workflow

- `ModularityAgent` coordinates the existing `ArchitectureBoundaryAgent`,
  `ResponsibilityAgent`, and `DependencyImpactAgent` under `agents/maintainability/`.
- The initial round assigns work to all three. Follow-up rounds target unresolved
  questions; they do not necessarily invoke all three investigators.
- Each invocation has a unique ID, including repeated calls to the same investigator.
- Investigators use read-only snapshot tools to discover files, search code, inspect
  source excerpts, symbols, relationships, evidence, and infrastructure. The coordinator
  synthesizes their results rather than reading source directly.
- Hypotheses remain in the output as `confirmed`, `discarded`, or `inconclusive`
  (`pending` during execution). Confirmation alone does not accept a finding: evidence
  validation and critical review are still required.

## Default limits

| Limit | Coordinator | Each delegated investigation |
| --- | --- | --- |
| Accounted tokens | 300,000 total, including synthesis | 60,000 |
| Model calls | 96 total | 12 |
| Tool calls | 96 total | 16 |
| Timeout | 600 seconds | 180 seconds |
| Context per call | 100,000 characters | 100,000 characters |

- The coordinator allows 2 rounds, 6 invocations, and up to 3 concurrent investigators.
- `ModularityConfig.investigation_start_interval_seconds` staggers investigator starts
  without serializing their subsequent work. It defaults to 0 and is independent of
  provider request spacing. Its shared scheduler spans rounds and honors cancellation
  and the global deadline; assignments that expire before starting are skipped without
  charging an unused investigation reservation.
- Investigators allow 3 internal investigation iterations by default. Standalone
  `run_architecture_boundary.py` uses `max_iterations`, not coordinator `max_rounds`.
- Standalone investigators default to 100,000 total tokens, 16 model calls, 24 tool
  calls, and 300 seconds; these differ from delegated investigation budgets.
- Existing repository budgets and provider output caps can impose lower limits.
  Runners derive an estimated input allowance of 50,000 tokens per call from the
  default character limit. Resource reservations can prevent dispatch before the
  displayed total is exhausted.
- `--config limits.json` overrides defaults in standalone runners. Increasing rounds
  does not increase token, invocation, call, or time budgets automatically.

## Failure interpretation and recovery

- Provider quota defaults are **14 RPM** and **250,000 TPM**, configured through
  `provider_rate_limits.requests_per_minute` and `provider_rate_limits.tokens_per_minute`.
  These are separate from total execution budgets. Both are rolling 60-second limits;
  every attempt, including schema corrections and transient retries, consumes admission.
- A shared limiter covers all three investigators and synthesis in a coordinator run.
  Standalone investigator runners enforce the same defaults. Requests reserve estimated
  input plus capped output tokens and reconcile with reported usage; failed/unknown
  attempts retain estimates. Reconciliation wakes blocked requests when capacity frees.
- Admission combines quota availability, fixed request spacing and provider cooldown.
  Waiting is cancellable and counts against execution deadlines. A request too large
  for the configured TPM stops with `provider_tpm_request_limit`, rather than waiting
  indefinitely. No daily request limit is implemented.
- Quota tracking is local to an assessment by default, not a provider-side quota query.
  Inject the same `ProviderPacer` into multiple agent/coordinator instances on the same
  event loop to share accounting across assessments for the same project/model. Separate
  processes, restarts and other API consumers are not tracked. Estimated token sizes
  and provider-specific accounting can still lead to 429 responses.
- Offline orchestration tests explicitly disable minute quotas; dedicated quota tests
  use a virtual clock. Live tests keep the configured defaults.

Example `limits.json` (accepted by standalone runners via `--config`):

```json
{
  "provider_rate_limits": {
    "requests_per_minute": 14,
    "tokens_per_minute": 250000
  }
}
```

Either limit may be disabled explicitly with `null`; limits are enabled by default.

- `context_limit` means a prompt exceeded the character cap, not the total token budget.
  Raising the cap is a mitigation; automatic context compaction is not implemented.
- `model_or_schema_error` is a broad termination category. Inspect sanitized diagnostics
  to distinguish provider errors, structured-output setup errors, and validation failures.
- Google rate-limit errors can wrap an underlying HTTP 429 exception. Runtime
  classification follows exception chains and honors HTTP `Retry-After` and Google's
  structured `RetryInfo`.
- The agent runtime defaults to 2 provider retries, exponential backoff starting at
  2 seconds, and no fixed spacing between requests. The coordinator shares pacing
  and cooldown across investigators and synthesis. Retries remain subject to token,
  call, and time budgets; cancellation propagates.
- Permanent HTTP 400 errors are not blindly retried. Synthesis uses a lean native
  schema for native chat models to reduce generation complexity while retaining full
  local Pydantic validation. This does not imply that every HTTP 400 is schema-related.
- A later round may recover from a transient synthesis failure without resetting
  resource accounting. Increasing context or rounds does not fix exhausted quotas.

## Assessment status versus test status

- `completed` means the scoped investigation has no material unresolved gaps, not
  that the repository is modular or universally compliant.
- `partial` retains usable results while explicitly reporting missing evidence or
  incomplete investigations. Empty findings are not evidence of compliance.
- A passing test can intentionally validate a partial assessment, timeout, or provider
  failure. Test success and assessment completeness are different outcomes.

## E2E tests versus production behavior

- Offline E2E tests use real investigators, LangGraph workflows, and repository tools;
  only model responses are simulated. They cover one round, targeted follow-up,
  unresolved gaps, provider failure, provenance, and an unchanged audited repository.
- The optional live test configures up to 3 concurrent investigators, 1-second spacing
  between investigator starts, 0.5-second shared provider request spacing, and a
  5-second initial backoff. **These pacing values are test-specific, not production
  defaults; their implementation belongs to coordinator/runtime code, not the test.**
- Runners can inject the same policy using `--config limits.json` with
  `max_parallel: 3`, `investigation_start_interval_seconds: 1`,
  `provider_request_interval_seconds: 0.5`, and `provider_retry_backoff_seconds: 5`.
  Provider-requested cooldowns may still require longer waits.
- The live test requires at least one completed investigator with a plan and retrieved
  evidence, plus no unresolved synthesis failure. Tool activity alone is insufficient;
  passing still does not require a fully completed overall assessment.
- Retry handling, shared cooldown, schema simplification, accounting, and sanitized
  diagnostics are implemented in agent code and also apply outside pytest.

From `agent-server`, show execution progress and provider diagnostics with:

```powershell
uv run pytest src/test-agents/test_modularity_e2e.py -v -s

# Optional paid provider calls; uses .env and config/dev-agents.yaml.
$env:MODULARITY_E2E_LIVE = "1"
uv run pytest src/test-agents/test_modularity_e2e.py -v -s -k live --log-cli-level=WARNING
Remove-Item Env:MODULARITY_E2E_LIVE
```

`-s` exposes investigator progress and per-round summaries; without it, pytest normally
captures successful test output. Offline validation does not prove live provider
compatibility or available quota.
