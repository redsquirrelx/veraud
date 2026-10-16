# ReuseOpportunityAgent

Independent, read-only **reusability** investigator:

> Do conceptually similar functionalities exist that could share an implementation?

Similarity is navigation, not a compulsory refactor. Existing abstraction quality
belongs primarily to `AbstractionAgent`; this agent compares separate implementations.

## Integration map

All paths below are relative to `agent-server/src/`.

| Established extension point | Reuse |
| --- | --- |
| `server/runtimes/investigation/agent.py`: `InvestigationAgent` | `await ReuseOpportunityAgent(model, config).run(fresh_toolset, request)`; wrapper `.llm` and optional injected `provider_pacer` supported. |
| Same file: `InvestigationExecution` | All cognitive nodes, model calls, native structured output, retries, token/deadline/call budgets, provenance and critical review. Only graph wiring and domain evaluation/finalization are specialized. |
| `server/runtimes/investigation/schemas.py`, `state.py` | Extends existing request/config/evaluation/finding/result contracts; reuses `InvestigationState`, including evidence, hypotheses, unresolved gaps and resource counters. |
| `server/runtimes/repository/tools.py` | Seven existing read-only tools; compact serialization, identical-query cache, evidence registry, access policy and measurements. |
| `server/services/repository_analysis/` | Existing symbols, source ranges, retained source and static relationships; no parser, embedding service or alternative framework added. |
| `test-agents/run_architecture_boundary.py` | Shared YAML/`.env` configuration, snapshot construction, budgets and tracing via `run_audit(..., agent_class=ReuseOpportunityAgent)`. |

The package exports the agent and public request/config/result classes, matching the
other investigators' construction interface. There is no existing reusability parent
coordinator to register with. The modularity registry intentionally stays unchanged.
`docs/agent-server/generic-pipelines.md` describes `PipelineDefinition`/`BaseAgent`
service contracts, not this snapshot-bound investigator interface. No incompatible
HTTP registration, new service or coordinator is introduced.

## Discovery and language coverage

`discovery.py` scopes existing indexed **functions/methods**, selects at most 160
symbols in stable path/line/ID order, compares bounded source features, and retains
at most 8 ranked **pairs**. Both bounds are configurable. It considers:

- Identifier-erased token shapes: catches renamed implementations.
- Shared vocabulary in the indexed source: can shortlist different syntax, such as
  iterative accumulation versus `sum` with a comprehension.

The signal cutoffs only bound navigation; they are not numerical quality thresholds,
semantic equivalence tests or recommendations. Groups have stable hashed IDs from
their indexed member identities. The result exposes omitted symbols/groups, inspected
paths and unassessed groups; discovery is never claimed exhaustive. It sends only
shortlist metadata/signals, not the repository source, into preparation context.

| Language | Existing evidence available |
| --- | --- |
| Python | Python AST-derived functions, methods, classes, signatures/ranges and imports; retained excerpts and source search. |
| JavaScript | Tree-sitter symbols/ranges and static import relationships; source search/excerpts. |
| TypeScript/TSX | Tree-sitter TypeScript/TSX symbols/ranges and static imports; type text may be inspected in excerpts, without type-checker guarantees. |
| Others/unindexed constructs | Accessible retained text can be searched if admitted by existing policy, but no reliable automatic pair discovery is promised. |

There is no general semantic-similarity tool, complete call graph, reference resolver,
or data-flow index exposed by the current toolset. `find_symbols`, `list_relationships`,
`search_repository_text` and `get_source_excerpt` map those inspection responsibilities
as far as the actual infrastructure permits. Import relationships plus caller source
provide static context only. Dynamic/external links and unsupported syntax remain
unknown. Different languages can share vocabulary without being able to share code.

## Native graph and bounded routing

```text
START -> plan_investigation -> investigate
  investigate --use_tools--> tools -> investigate
  investigate --validate--> evaluate_evidence
  evaluate_evidence --inspect--> investigate
  evaluate_evidence --finalize--> review_findings -> finalize -> END
  evaluate_evidence --limited_finalize--> limited_review -> limited_finalize -> END
```

Decision values are closed `InspectRoute` and `ValidationRoute` string enums mapped
to real conditional LangGraph edges. Preparation, inspection, tools, evaluation and
critical review are the established runtime nodes, not an alternative execution engine.
The reviewer is an internal stage, never delegation. Native node traces, sanitized
node/route logs and `execution_trace` expose routing.

Host validation can override `sufficient=true`. Only a specific evidence gap permits
reinspection; no-actionable-gap, iteration, model/tool/token/context or time limits
end with explicit limited output. Native schema constraints are projected through
the existing `lean_schema` for actual chat models and fully validated locally.

## Evidence and decisions

Each examined group compares purpose, inputs/outputs, pre/postconditions, failure
behavior, side effects, dependencies, invariants, meaningful differences, variation,
proposed boundary, qualitative benefit/migration complexity, risks and counterevidence.

- **recommended**: both distinct selected implementation bodies must be inspected,
  with callers and static relationship anchors for each, and no declared unresolved
  unknowns. A source declaration alone cannot support the body comparison.
- **conditional**: both implementation sources still required; missing caller/contract
  knowledge or important differences must be explicit conditions, not hidden assumptions.
- **not_recommended**: preserve an inspected rejected comparison and rationale; no
  negative finding is required just to populate the result. An accepted observation
  with this classification means the comparison passed review, not “perform reuse.”

Citations resolve through the actual retrieved-evidence ledger; file/symbol identities,
full body coverage (including adjacent excerpts), internal relationship endpoints,
source anchors and Git blob provenance are checked. Unknown/out-of-scope groups,
duplicate assessments, invented citations and missing tradeoff fields cannot support
acceptance. Recommended conclusions need semantic critical review as well: deterministic
checks do not prove equivalence, purity, business intent or low migration risk.

Exact group duplicates retain one accepted finding and rejected duplicates with
`duplicate_of`. `stable_id` identifies a member pair across runs with the same indexed
locations; the original model finding ID is preserved for review history. Related pairs
are not forcibly merged into a speculative global abstraction. Prior comparisons and
candidates survive later iteration failures. Consumers must inspect classification
and filter `validation_status == "accepted"` before treating a finding as supported.

Shared `modularity_impact` carries the reuse/maintenance consequence for compatibility;
the detailed comparison is linked through `group_id` to `examined_groups`. No new
quality score, calibrated confidence rubric or measured savings is invented.

## Resources, safety and execution

The agent enables the existing compact tool serializer/cache on its fresh toolset,
and tightens caller limits to at most 80 source lines / 4,000 characters per excerpt
by default. Repeated successful queries reuse cached retrieval; invocation costs and
provenance are still recorded, and tool-call admission is not bypassed. Excerpts are
bounded; longer implementations require adjacent reads. Assessments store compact
comparisons and references, not additional copies of raw source. The shared transcript
still retains bounded tool messages; automatic history compaction is not implemented,
so accumulated context can reach the existing hard limit and finalize partially.

All existing defaults apply, including 100,000 context characters, 14 RPM / 250,000 TPM,
provider retries and hard budget guards. Cancellation propagates to the caller, rather
than being disguised as a completed assessment; clients remain caller-owned. ToolNode
argument failures and repository-tool errors appear as content-free `tool_failures`.
Even after recovered errors, assessment status remains conservatively `partial`.

`completed` means selected groups were investigated and critically reviewed, not that
the repository is globally reusable. Supported conditional decisions and valid empty
findings can complete. Missing evidence, limits or errors yield `partial`; failure
before a usable plan/source investigation yields `failed`. Available evidence survives.
The audited project is never edited, executed or refactored.

From `agent-server`:

```powershell
uv run pytest src/test-agents/test_reuse_opportunity.py -q
uv run python src/test-agents/run_reuse_opportunity.py C:\repos\project
uv run python src/test-agents/run_reuse_opportunity.py C:\repos\project --request request.json --config limits.json
```

Request example: `{"targets":["src/orders","src/billing"]}`. Config example:
`{"max_groups":4,"max_iterations":2}`. Provider/model comes from
`config/dev-agents.yaml`, `--agent-config dummy` by default; credentials use root
`.env` / `LLM_API_KEY`. Existing LangSmith tracing is optional; set
`LANGSMITH_HIDE_INPUTS=true` and `LANGSMITH_HIDE_OUTPUTS=true` to hide source/results.
Untracked/dirty files inside a Git checkout cannot be attributed to its commit and
therefore cannot support an accepted commit-bound finding.

Optional **paid** seeded model evaluation, skipped by default:

```powershell
$env:REUSE_OPPORTUNITY_LIVE = "1"
uv run pytest src/test-agents/test_reuse_opportunity.py -v -s -k live
```

`REUSE_OPPORTUNITY_AGENT_CONFIG` selects another YAML entry. The test uses a temporary
copy of the small seed, real tools and a real model. It requires a source-backed
comparison, not a particular recommendation or wording; usefulness/accuracy must be
evaluated separately. Offline tests validate orchestration/guards, not semantic accuracy.

## Example trace and source-backed finding

Observed offline against a temporary copy of
`src/test-agents/fixtures/reuse_opportunity/`, using the actual graph/tools and
**simulated model judgments** (not a paid or semantic-accuracy result):

```text
plan_investigation -> investigate -> [use_tools] tools -> investigate
 -> [validate] evaluate_evidence -> [finalize] review_findings -> finalize
assessment status=completed; 5 model calls; 5 tool calls
```

Abbreviated finding/comparison view (full results also retain snapshot/content hashes,
actual symbol IDs, evidence IDs, confidence and review rationale):

```json
{
  "stable_id": "REUSE-89fc597f02a40d12",
  "classification": "recommended",
  "validation_status": "accepted",
  "shared_responsibility": "Sum amount fields and round the aggregate.",
  "evidence": [
    {"path":"sales.py","symbol":"order_cost","lines":[1,3]},
    {"path":"billing.py","symbol":"invoice_value","lines":[1,5]},
    {"path":"orders.py","symbol":"quote","lines":[1,5]},
    {"path":"invoices.py","symbol":"preview","lines":[1,5]}
  ],
  "differences": "Comprehension plus sum versus iterative accumulation.",
  "proposed_boundary": "Consider domain-local amount aggregation, without generic strategy machinery.",
  "risks": "Confirm numeric contracts and common policy ownership; preserve independent policies when necessary.",
  "benefit": "Qualitative centralization of the shared rounding rule; no measured savings."
}
```

This proposal is deliberately qualified: similar source and valid citations alone do
not establish safe floating-point/numeric equivalence or common domain ownership.
