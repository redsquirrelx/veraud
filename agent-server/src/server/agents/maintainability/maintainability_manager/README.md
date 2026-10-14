# MaintainabilityManagerAgent

## Inspection and integration boundary (before implementation)

- Both subordinate coordinators expose `await .run(fresh_repository_toolset, typed_request)`
  and compile native LangGraph state machines. They are snapshot-bound runnables, not
  `BaseAgent` HTTP services. The manager uses the same interface and a compiled graph;
  `docs/agent-server/generic-pipelines.md` describes a different application contract.
- `modularity/agent.py::_Execution` already implements concurrent bounded dispatch,
  child repository contexts, whole-envelope reservations, deadlines and sanitized failures.
  Its registry/request/config hooks can be reused at the next hierarchy level.
- Coordinator results use `status=completed|partial|failed`, `consumption`, `invocations`
  and `consolidated_findings`, unlike the proposed flat investigator result. Manager
  records must retain these whole nested assessments, without flattening their evidence.
- Modularity's serialized investigator results need role-based rehydration: its public
  base result annotation does not describe responsibility/dependency extensions. The
  manager adapter uses the existing investigator registry to restore these types.
- Each coordinator owns separate child tool ledgers; its own toolset ledger is empty.
  Manager evidence must come from nested invocation records, not its own repository reads.
- Evidence/coverage sufficiency is explicit: each selected supported dimension needs a
  completed assessment, no material gaps, valid provenance and a completed, planned,
  source-backed invocation for each registered investigator. Empty findings are allowed;
  absence of findings is not compliance. Partial results cannot satisfy coverage.
- Supported dimensions are modularity and reusability. Other requested dimensions stay
  unsupported and prevent a complete report; unrequested dimensions are not gaps.
- Planning and coverage are deterministic policies; only cross-assessment synthesis uses
  the existing structured model runtime. The manager never inspects repository source.

## Exact workflow

```text
START -> analyze_audit_scope -> plan_audit -> delegate_auditors
      -> collect_assessments -> synthesize_assessments
           --no--> refine_audit_plan -> delegate_auditors
           --yes--> finalize_audit -> END
```

There are exactly seven executable nodes. `coverage_router` is a state-only conditional
edge. `yes` means finalization, including forced stops: the separate typed
`CoverageDecision.sufficient` remains false on exhausted limits, unsupported requests,
unactionable gaps or stalled work. Neither a model nor a forced exit can certify coverage.

## Contracts and lifecycle

The public interface is `await MaintainabilityManagerAgent(model, config).run(tools, request)`.
Pass a fresh toolset and an already analyzed immutable repository snapshot. The shared
CLI analyzes it once; nested contexts reference the same snapshot and policy. No manager
source browsing, repository-wide rescan, application execution or audited-file writing occurs.

`MaintainabilityRequest` retains objective, context, criteria, targets and optional reuse
target context. `dimensions` defaults to modularity/reusability, is normalized and
deduplicated; other names are retained as unsupported. `depth` is forwarded as an intent,
not permission to exceed limits. Optional `dimension_targets` restricts each selected
coordinator to a subset of overall targets. Empty overall targets means all accessible
repository files; consumer/counterevidence reads may still navigate beyond focal targets.
Project/revision identity comes from the supplied snapshot, not model assumptions.

Planning is deterministic: one assignment per requested supported dimension, with goals,
evidence expectations and explicit success criteria. Each assignment has a logical
`assignment_id`, execution `invocation_id`, round and per-dimension attempt. Scope, IDs,
criteria and constraints go to the existing typed public coordinator requests. No fake
coordinators are used by default. The test injection seam is `coordinator_factory`.

The shared dispatch implementation (`modularity/agent.py::_Execution`) handles semaphore
admission, optional staggering, child contexts, timeouts and whole-child resource
reservations. Small configuration/evidence/correlation hooks allow nesting without
duplicating its scheduler. Actual coordinators retain their own cognitive workflows and
independent investigator responsibilities. A manager follow-up targets one coordinator;
that coordinator still owns its internal planning/delegation policy.

Concurrent workers return one bounded batch; only collection appends records. Unknown,
duplicate, stale-round and mismatched assignment replies are ignored and recorded, with
no second usage charge or overwrite. Collection checks schemas, scope/identity, resource
bounds, subordinate IDs, nested source ranges/hashes and Git attribution, collected
evidence citations and consolidated finding contributors. Invalid outputs cannot supply
coverage. Failures retain sanitized error types and conservative reserved costs. Partial
assessments retain full nested findings, discarded hypotheses, observations, coverage and
limitations. Cancellation propagates and cancels pending work, rather than producing a
successful result; callers may cancel explicitly and will not receive a fabricated report.

## Synthesis, coverage and refinement

The manager's only model call is `synthesize_assessments`, using local prompts and the
existing structured-call runtime, lean provider schemas, validation, retries, quotas,
deadlines and diagnostics. Context contains compact summaries/classifications/assumptions
and stable source references, not duplicated code or full nested histories. Full typed
assessments remain in the report. Context is bounded per call; automatic history
compaction is not implemented.

Finding refs are `coordinator_attempt_id/group_id`; evidence refs add the investigator
invocation identity: `coordinator_attempt_id/investigator_invocation_id/evidence_id`.
Original contributors remain available. Shared canonical source ranges create overlap
links, not proof of equivalent defects or independent confirmation. The synthesis model
may propose validated tradeoff/contradiction links. Conflicts require a blocking gap and
a selected coordinator with a narrow question. Unsupported references, inaccessible or
out-of-scope targets, and untracked contradictions reject synthesis explicitly.

Coverage reports requested, assessable, unsupported and covered dimensions as sets/lists,
with no invented quality score. A supported dimension needs a completed valid coordinator
assessment, no material gaps/disputed findings, and a planned completed source-backed
invocation for each of its three registered investigators. Empty findings can be valid;
successful completion describes investigation of a bounded scope, never ISO compliance.
Unsupported dimensions prevent an overall `complete` report, but unrequested dimensions
are not gaps. Overall status is `complete`, `partial`, or `failed`.

Only material actionable gaps enter refinement. It groups them by coordinator and issues
new questions/targets; completed dimensions are not automatically redispatched. Equivalent
questions are blocked, per-dimension attempts and total invocations/rounds are capped,
and lack of new canonical source or recovered coverage stops progress. Coverage may
recover on a later valid attempt without deleting earlier failures. Quality/contradiction
gaps persist until a completed assigned follow-up supplies new source content/ranges and
a validated resolution; new retrieval UUIDs alone cannot close them. Original links/gaps
and every synthesis decision remain in history, including resolved contradiction links.

## Resources and observability

Manager defaults: 2 rounds, 4 coordinator invocations, 2 attempts/dimension, concurrency 2,
1,200 seconds, 300 model calls, 400 tool calls and 1,000,000 tokens. These are hierarchy-wide
envelopes, not changes to existing coordinator defaults: each child retains its configured
`ModularityConfig` envelope (default 96 calls/tools, 300,000 tokens, 600 seconds) and its
separate investigator caps. The caller's repository budget can impose stricter limits.
Two parallel children reserve their whole envelopes before either starts; unknown failed
executions consume reservations, while never-started invocations are skipped. Nested costs
are counted once via each coordinator's consumption, plus manager synthesis costs.

One shared `ProviderPacer` covers manager synthesis, both coordinators and all investigators,
defaulting to 14 RPM / 250,000 TPM. An injected pacer can share accounting across assessments
on one event loop; it is not a persistent cross-process/project quota service. Admission
waits/retries count toward deadlines. Do not interpret an offline success as proof of live
provider reliability or semantic accuracy.

Tracing propagates `audit_id`, assignment/attempt IDs, round, coordinator identity and
`coordinator_attempt_id` into investigator spans. The final report includes node transitions,
per-attempt statuses/durations/costs, synthesis/coverage decisions, full nested assessments,
resolved/unresolved gaps, limits and limitations. Existing LangSmith support is reused;
clients remain caller-owned. `LANGSMITH_HIDE_INPUTS=true` and `LANGSMITH_HIDE_OUTPUTS=true`
hide source/prompts/results in tracing.

## Run and verify

From `agent-server`:

```powershell
uv run python src/test-agents/run_maintainability_manager.py C:\repos\project
uv run python src/test-agents/run_maintainability_manager.py C:\repos\project --request request.json --config limits.json
uv run pytest src/test-agents/test_maintainability_manager.py src/test-agents/test_maintainability_manager_e2e.py -v -s
```

Example request:

```json
{
  "dimensions": ["modularity", "reusability"],
  "targets": ["src/domain", "src/storage", "src/shared"],
  "dimension_targets": {"modularity": ["src/domain", "src/storage"], "reusability": ["src/shared"]},
  "target_context": "Offline processing with a caller-supplied backend",
  "depth": "thorough"
}
```

The runner reuses YAML model configuration (`--agent-config dummy`), root `.env` and
existing credential/client cleanup/tracing infrastructure. No HTTP service registration
is invented for this snapshot-bound protocol.

`test_maintainability_manager.py` runs the real manager graph with controlled subordinate
outputs covering both branches, refinement, failures, scope, conflicts, resolution,
exhaustion, stale/duplicate responses, cancellation, timeouts and mocked Google schema
transport. Controlled judgments do not prove analysis accuracy.

`test_maintainability_manager_e2e.py` uses the default registry and real manager, two real
coordinators, six real investigators and repository tools. Only model I/O is simulated.
Its broader fixture combines domain/storage architecture with reuse candidates and
configuration seams. It exercises internal coordinator follow-up and manager-level
targeted recovery. JSON report/events/node artifacts are written beside the temporary
checkout (`artifacts/`), never inside the audited repository; `-s` prints their paths.

Optional paid smoke (uses default quota admission and existing LangSmith):

```powershell
$env:MAINTAINABILITY_MANAGER_LIVE = "1"
uv run pytest src/test-agents/test_maintainability_manager_e2e.py -v -s -k live
```

`MAINTAINABILITY_MANAGER_AGENT_CONFIG` selects another YAML model entry. The smoke requires
at least one evidence-sufficient coordinator and no manager synthesis failure, not predetermined
findings or mandatory refactors. No paid calls are part of normal deterministic verification.
