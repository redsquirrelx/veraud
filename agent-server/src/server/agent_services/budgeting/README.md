# Agent budgeting

One process-wide setting in `agent-server/launch.json`:

```json
{"budgets_enabled": false}
```

- `true`: enforce configured execution/parent/task budgets.
- `false`: bypass budget admission for cumulative tokens, model attempts, tool
  calls, active/wall execution deadlines, request deadlines and repository
  retrieval sizes/counts. Accounting remains enabled.

The checked-in/local launch configuration was migrated from the old unlimited-token
setting to `budgets_enabled=false`. With no launch setting, the safe default is
`true`. Restart the process after changing it; policy is loaded once per process.
There is no per-agent, per-invocation or ContextVar override. Agent settings reject
`unlimited_model_calls`, `unlimited_tool_calls`, `unlimited_token_budget` and
`budgets_enabled`. Runner agent configuration files cannot change the global switch.
Legacy policy contexts accept only the already-effective global policy.

The switch does **not** disable pacing, provider RPM/TPM quotas, provider terminal
failure handling, bounded provider/schema retries, explicit cancellation, cleanup
grace periods, evidence/provenance validation, access permissions or read-only
snapshot rules. Provider-supported output generation sizes and protocol/schema
validity bounds remain; no unlimited provider capacity is implied. Domain stopping
rules (finished tasks, no progress, graph rounds) remain domain decisions, not
resource opt-out flags.

## Owners

- `policy.py`: launch loading, strict global boolean, admission and timeout helpers.
- `shared_tokens.py`: atomic hierarchical reservations and actual/estimated usage.
- `tokens.py`: text-model accounting and total/objective/input admission.
- `timing.py`: active/wall deadlines and cancellation-safe execution helpers.
- `retrieval.py`: shared retrieved-character ledger.
- `usage.py`, `telemetry.py`: always-on resource metrics and content-free measurements.

Shared numeric configuration declarations stay in `config/agents/`, following its
single-owner rules; neutral audit output contracts remain in `server/contracts/`.
Agent/runtimes own when they request resources, but not independent enable switches.
Old repository metric/timing/token modules and `server.config.token_budget` are
same-module compatibility aliases, not additional ledgers or policies.

Disabling budgets can permit unbounded cost, reads or execution duration. The
operator can still cancel explicitly; backend tracking can still report consumption.
