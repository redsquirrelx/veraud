# ReusabilityAgent

Read-only coordinator for `AbstractionAgent`, `ReuseOpportunityAgent` and
`ComponentAdaptabilityAgent`. It coordinates their results; it never independently
inspects source or repeats their analytical work.

## Exact topology

```text
START -> plan_assessment -> delegate_investigations -> collect_findings
      -> synthesize_findings
           --yes--> delegate_investigations
           --no---> finalize_assessment -> END
```

This is the requested five executable nodes plus the conditional decision (six
cognitive stages). The decision is a typed, deterministic conditional **edge**, not
a node. No follow-up-planning, reviewer, validation or limited-finalization nodes are
added. Follow-up assignments, continuation rationale and limit reasons are prepared
inside synthesis. Exhausted/unverifiable work follows the same `no` edge and yields
partial/failed output, not a separate finalizer.

## Integration map and contract differences

Paths below are relative to `agent-server/src/`.

| Existing extension point | Integration |
| --- | --- |
| `server/runtimes/coordination/execution.py`: `CoordinatorExecution` | Shared dispatch, semaphore/start pacing, deadlines, per-invocation envelope reservation, collection/accounting and synthesis recovery. Contract/registry/request/validation/context hooks allow independent dimension specialization. |
| Same file: `CoordinatorSynthesisExecution` | Existing budgeted native structured-output calls, lean schema, retries, usage reconciliation, diagnostics and shared `ProviderPacer`. |
| `server/agents/maintainability/modularity/coordinator/schemas.py`, `synthesis.py` in the same directory | Specializes existing assignment/invocation/gap/assessment contracts and reuses namespacing, grouping, conflict, resolution and request-key helpers through configurable types/keys. |
| `server/agents/maintainability/reusability/abstraction/`, `reuse_opportunity/` and `component_adaptability/` in the same parent directory | Registry points directly to the real classes and their request/result models. Public invocation remains `await agent.run(fresh_toolset, typed_request)`. No duplicated analysis or investigator delegation. |
| `server/runtimes/repository/` | Each invocation has a fresh context/toolset on the same immutable snapshot and access policy; only investigators inspect code. Collection checks the actual retrieved ledger and source provenance. |
| `test-agents/run_architecture_boundary.py` | Shared YAML/`.env` model loader, snapshot/budget harness and existing LangSmith tracing. |

The contracts differ in important ways: specialized findings/coverage must survive
serialization; every investigator has an explicit completed/partial/failed status;
adaptability alone accepts an explicit `target_context`. Collection uses discriminated
result types, preserves nested findings/assessments and respects those explicit statuses.
Targets go into **all three** typed requests, not merely a text hint. A missing target
context stays null; the adaptability investigator must qualify plausible contexts.

The package exports `ReusabilityAgent`, `ReusabilityRequest`, `ReusabilityConfig` and
`ReusabilityAssessment`. `registry.py` registers exactly these three investigators.
The coordinator is callable via the established harness/public interface and has its
own trace/agent type. The modularity registry is not changed. As documented in
`docs/agent-server/generic-pipelines.md`, HTTP `PipelineDefinition`/`BaseAgent` execution
is a different contract; no incompatible HTTP registry integration is invented.

## Plan, dispatch and safe collection

Planning follows the existing coordinator's deterministic policy: initially assign all
three lenses with explicit research questions, scope, priority and evidence expectations.
It uses the request and existing project metadata, not another full-repository scan or
an extra planning-provider call. Initial and follow-up assignments have distinct request
and invocation UUIDs, a shared assessment identity and an explicit per-round identity.

Independent calls run under the existing semaphore, optional staggered starts and
shared provider admission. `delegate_investigations` awaits the bounded dispatch batch;
`collect_findings` validates and appends all returned records. Worker tasks never mutate
graph lists; one collection update preserves prior rounds and differing completion orders.

Collection validates specialized schemas, repository/revision/snapshot/objective identity,
usage bounds, target context, actual retrieved evidence IDs, source ranges/hashes and
commit attribution. Accepted source claims cannot cite unknown/unretrieved evidence.
Schema-invalid returns cannot supply conclusions, but their genuine tool observations
remain attached to the failed invocation. Raw exception details are not exposed.
Partial, timeout, skipped and failed results never silently become complete.

## Synthesis, follow-ups and evidence

- Source/finding references are `invocation_id/local_id`; repeated investigator IDs
  never erase execution provenance. Original results, discarded/unsupported hypotheses,
  findings, uncertainties, warnings and coverage remain in invocation records.
- Only accepted, nonwithdrawn findings enter supported consolidation. Equivalent
  same-polarity observations may merge, including cross-investigator duplicates;
  original classifications/assumptions/contributors remain available. Shared paths alone
  do not establish equivalence. Severity is retained only when consistent; no invented
  scores or confidence averages are introduced.
- Useful abstraction, harmful coupling, recommended/conditional/rejected sharing and
  qualified adaptation risks cannot be flattened indiscriminately. `finding_relationships`
  connects support, tradeoffs, dependencies and explicit conflicts without erasing lenses.
- Substantive `conclusions` require known accepted finding refs and source evidence those
  findings actually cite. Unknown refs, incompatible grouping, inaccessible gap targets
  and untracked conflict relationships reject synthesis explicitly rather than certify it.
- Contradictions remain material gaps and disputed conclusions/groups until supported
  resolution. Host-rejected duplicate findings are not treated as semantic contradictions.
  Conflict relationships retain unresolved/resolved state and synthesis history.
- Synthesis prepares only targeted follow-ups for material gaps, deduplicated by
  investigator/question/targets/task/subjects. Empty proposed target lists inherit assessment scope.
  Equivalent completed questions cannot repeat without genuinely new source evidence.
  An essential initial failure gets at most one same-question retry without new evidence.
- Follow-ups carry original declaration/group/component commitments, question, assessed
  context and sharing boundary. Discovery prioritizes committed declarations/groups;
  adaptability receives exact component IDs. An unrelated completion cannot close them.
- Source gaps require new source content/ranges, not merely new retrieval UUIDs.
  Validation repairs can close with previously read source only after a host-verified
  invalid-to-valid transition of the assigned commitment and resolved final hypothesis.
  Contradictions additionally require justified withdrawal refs. Earlier evidence/results
  remain append-only. Provider-terminal and collection-contract blockers prevent retries.
- Synthesis receives final host hypotheses/analyses, not raw review approval. Repeated
  candidate/assessment/hypothesis diagnostics become a single bound repair task. External
  context remains a limitation. Conditions, unknowns and the exact sharing boundary are
  retained in findings/consolidation and passed through the manager's synthesis context.
- After the first follow-up, no new source, finding judgment or supported gap resolution
  stops the cycle as `zero_progress`. Maximum rounds/invocations, aggregate budgets and
  deadlines also guard continuation. Limits always follow the normal `no` edge.

`status=completed` requires usable results and no unresolved material gaps. Partial
investigations, unresolved conflicts, failed synthesis or exhausted budgets remain
explicitly partial (or failed when no usable investigator result exists). A successful
targeted retry may recover an earlier failure without deleting its original record.
Completion describes the selected scope, never global reuse quality or ISO compliance.

## Resource policy and observability

Defaults are inherited from `ModularityConfig`: 2 rounds, 6 invocations, parallelism 3,
600 seconds, 96 model/tool calls and 300,000 aggregate tokens. Each child reserves its
whole configured envelope before dispatch (default 12 model calls / 16 tool calls /
60,000 tokens / 180 seconds). Both coordinator config and the caller's repository
budget apply; the stricter bound wins. Unknown failed calls conservatively consume
reservations; never-started calls are skipped without charging unused envelopes.

Synthesis and **all three** investigators share the existing 14 RPM / 250,000 TPM
limiter. A caller-supplied `provider_pacer` can share accounting with other assessments
on one event loop; there is no cross-process/project persistence. Retries, token
estimates/actual usage, quota waits, start staggering and provider spacing use existing
runtime mechanisms rather than test-specific scheduling.

Node transitions, per-invocation statuses/durations/usage, structured decisions/rationales,
synthesis history and provider diagnostics are observable. Existing LangSmith spans
include assessment, request, invocation and round identities. No coordinator repository
tools are enabled, no audited code is executed/written, and clients remain caller-owned.
Cancellation propagates instead of being labeled successful completion.

## Run and verify

From `agent-server`:

```powershell
uv run python src/test-agents/run_reusability.py C:\repos\project
uv run python src/test-agents/run_reusability.py C:\repos\project --request request.json --config limits.json
uv run pytest src/test-agents/test_reusability.py -v -s
uv run pytest src/test-agents/test_reusability_e2e.py -v -s
```

Request example:
`{"targets":["src/orders","src/billing"],"target_context":"Offline processing with a supplied backend"}`.
Provider/model uses `config/dev-agents.yaml` (`--agent-config dummy` by default), root
`.env` / `LLM_API_KEY`, and optional LangSmith tracing. Set `LANGSMITH_HIDE_INPUTS=true`
and `LANGSMITH_HIDE_OUTPUTS=true` to hide source/results in traces.

Optional **paid** smoke with all real investigators, a real provider and a temporary
seeded repository (skipped unless explicitly enabled):

```powershell
$env:REUSABILITY_E2E_LIVE = "1"
uv run pytest src/test-agents/test_reusability_e2e.py -v -s -k live
```

`REUSABILITY_E2E_AGENT_CONFIG` selects another YAML entry. The smoke requires at least
one completed source-backed investigator and no unresolved synthesis failure, not
particular wording or a compulsory refactor. It does not guarantee semantic accuracy.

Deterministic tests exercise the actual coordinator graph/conditional edges with controlled
investigator results, both routes, failure, resource exhaustion, concurrency, schema/ledger
consistency, grouping and contradictions. Separate offline integration executes all three
actual investigator graphs/tools, simulating only models; Google synthesis transport is
also mocked separately. Semantic equivalence, materiality, causal judgments and language
coverage still depend on the investigators/model. Prompts/evidence context are bounded
but not automatically compacted; actual provider quotas and semantic quality remain
unverified until live evaluation and review.

The dedicated E2E suite `test_reusability_e2e.py` uses the **default registry**, no
investigator factory, actual investigator graphs and read-only tools. Only the shared
provider's responses are simulated. The seed `fixtures/reusability/` contains an
abstraction with consumers, two comparable methods, fixed construction and an external
configuration seam. Source-backed findings exercise all three perspectives; judgments
are still simulated rather than claims of semantic precision.

It covers direct completion, targeted follow-up, provider failure, unavailable source,
round exhaustion, unfunded token envelopes and zero-progress termination. With `-s`,
actual invocation start/end events, rounds, statuses, costs, diagnostics and executed
nodes are visible. Provider mode and assessment status are reported separately from
pytest pass/fail. Existing runtime configuration owns concurrency/pacing/quotas; the
offline suite disables minute admission to stay fast, and the live case keeps it enabled.
