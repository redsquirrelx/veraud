# ComponentAdaptabilityAgent

Read-only **reusability** investigator answering:

> Which constraints make a component difficult to reuse in another context?

It investigates context-specific adaptation obstacles, not abstraction quality
(`AbstractionAgent`) or opportunities for shared implementation (`ReuseOpportunityAgent`).
Dependencies, framework types and global state are not automatically defects.

## Integration map and registration

Paths are relative to `agent-server/src/` unless otherwise stated.

| Existing extension point | Integration |
| --- | --- |
| `server/agents/modularity_runtime/agent.py`: `InvestigationAgent` | Public package export and `await ComponentAdaptabilityAgent(model, config).run(fresh_toolset, request)`; accepts existing `.llm` wrappers and optional shared `provider_pacer`. |
| Same file: `InvestigationExecution` | Inherited planning/evaluation/review, native structured output, bounded schema/provider retries, token/deadline/tool/model limits and Git provenance. Specialized inspection returns typed decisions; only native graph wiring/domain checks are added. |
| `server/agents/modularity_runtime/schemas.py`, `state.py` | Extends existing request/config/evaluation/finding/result contracts and reuses the established graph state. Snapshot argument supplies repository/revision/index; no competing repository service or state framework. |
| `server/agents/repository_runtime/tools.py` | Seven existing read-only tools, policy, compact serializer, cache, source/evidence registry and telemetry. |
| `server/services/repository_analysis/` | Existing Python/JS/TS symbol/import indexes and retained source provide bounded deterministic navigation. |
| `test-agents/run_architecture_boundary.py` | Shared `run_audit(..., agent_class=ComponentAdaptabilityAgent)` and YAML/`.env` model loading; tracing and client ownership are unchanged. |

Reconnaissance found two existing reusability investigators, not a third independent
one or a reusability parent coordinator. The package exports the same callable contract
as those investigators. `trace_name`/`agent_type` identify this agent in the existing
runner/tracer; model settings come from the selected YAML entry, without duplicating
provider configuration. The modularity investigator registry remains unchanged.

`docs/agent-server/generic-pipelines.md` describes `PipelineDefinition`/`BaseAgent`
HTTP-service contracts, not this snapshot-bound interface. There is no compatible
reusability coordinator to register with yet; no incompatible HTTP registration or
new coordinator is fabricated. Tests verify the existing invocation/harness and shared
result contract, not integration with a nonexistent parent.

## Input, discovery and evidence

- `targets`: repository-relative files/directories; `component_ids`: optional actual
  file/symbol IDs from the supplied index. IDs must exist within targets and accessible
  retained source. Relevant consumers/configuration elsewhere in the accessible snapshot
  can be followed. Scope is not a separate filesystem sandbox.
- `target_context`: optional explicit description. If absent, the result retains `null`;
  any assessed plausible context must be labeled `plausible` with nonempty assumptions.
  Explicit target descriptions must be preserved exactly, not silently rewritten.
- Discovery ranks top-level classes/functions/interfaces (or file fallbacks) using
  bounded lexical signals for imports, constructors/service locators, environment reads,
  globals/static state, framework types, configuration, I/O, public interfaces, platform
  APIs and schema access. Explicit symbol IDs can select nested components.
- Defaults: 6 selected components, 160 scanned files, 24,000 scanned characters/file,
  12 signals/component and 16 assessed constraints. Coverage exposes omissions and
  truncated scans. Signals contain line/rule hints, not raw repository dumps or proof.
  Comments, optional paths or already-mitigated defaults can trigger false positives.
- Python AST and JavaScript/TypeScript/TSX Tree-sitter indexes provide symbol ranges
  and static imports. No complete call graph, type checker or data-flow resolver exists
  in the exposed tools. Other languages may have accessible source/file fallback but
  no equivalent structural guarantee. Narrative docs remain excluded by existing policy.

Findings must cite inspected source, never discovery metadata alone. Host checks require
full selected-component body coverage (adjacent bounded reads permitted), known evidence
IDs, actual component IDs, matching classifications/types and verified commit attribution.
Every non-unknown assessment needs source-backed seam inspection including component
source, plus counterevidence analysis. External factories/adapters require additional
actual inspection, not an assertion that no extension point exists anywhere.

`verified_obstacle` additionally requires an explicit target, inspected representative
consumer instantiation/configuration and source covering the resolved internal import/
relationship anchor, with no declared important unknowns. These are static constraints,
not proof of mandatory runtime invocation. Semantic relevance still needs critical review.

## Structured workflow and decisions

```text
START -> plan_investigation -> investigate
investigate --use_tools--> tools -> investigate
investigate --validate--> evaluate_evidence
evaluate_evidence --inspect--> investigate
evaluate_evidence --finalize--> review_findings -> finalize -> END
evaluate_evidence --limited_finalize--> limited_review -> limited_finalize -> END
```

The requested prepare/inspect/tools/validate/finalize responsibilities map to these existing
node names. The existing internal critical review is retained as part of finalization,
not a delegated investigator. Routes are real LangGraph conditional edges with closed enums.

Inspection uses `InspectionDecision`: `action=use_tools` with typed tool names and JSON
argument strings, or `action=validate` with no requests. It does **not** infer readiness
from free-form text. Argument schemas are supplied only during inspection to reduce
context duplication. Pydantic rejects invalid decisions; bounded schema corrections
apply. Host tool argument/permission failures stop safely before executing the batch.

Only targeted missing evidence permits another inspection while budgets remain. An explicit
`can_investigate_further=false` needs a concrete `continuation_reason` and exits as
`unverifiable`; a sufficient assessment without actionable gaps does not loop blindly.
Hard limits and unrecoverable failures always terminate with limited/failed output.

## Output and interpretation

`ComponentAdaptabilityResult` extends `AuditResult`: findings, original hypotheses,
uncertainty, limitations, provenance and resource counters remain compatible. It adds
`target_context`, `examined_constraints`, `coverage`, `summary`, status, execution trace,
node durations and content-free tool activity/failures.

- `verified_obstacle`: demonstrated, scoped mismatch with the explicit target.
- `context_dependent_risk`: observed constraint with qualified contextual assumptions,
  differences or unknowns; an accepted risk is not a universal portability defect.
- `mitigated`: inspected configuration/injection/adapter seam disproves the suspicion;
  retain the assessment/discarded hypothesis, without forcing a negative finding.
- `unknown`: missing evidence remains transparent; never promoted to an accepted defect.

Findings expose constraint type, adaptation impact, qualitative effort, assumptions and
optional nonmandatory mitigation options. `assessment_ids` link the detailed observed
facts, seams and contrary evidence. Legacy `modularity_impact` carries the reuse/adaptation
consequence. Existing numeric confidence is retained, not invented as a calibrated score.

The host `stable_id` hashes constraint type, normalized root `constraint_key` and assessed
context. Model candidate IDs remain for review history. Stability/merging depend on the
same semantic root key/context; unrelated obstacles must not use a generic shared key.
Accepted observations of the same root across files consolidate source/component/assessment
references, keep conservative confidence/classification, and retain rejected duplicate
candidates with `duplicate_of`. No original candidate is silently erased.

Consumers must filter `validation_status == "accepted"` and inspect classification,
target/assumptions and limitations. `completed` means the selected scope was investigated
and reviewed, not global adaptability certification. Valid empty findings are allowed
after source-backed clearance. Unknowns, missing evidence, limits or errors produce
`partial`; failure before a usable plan/source investigation yields `failed`.

## Safety, limits and execution

No application execution, repository writes, generated refactors or delegation occurs.
The fresh toolset uses existing compact caching; reads tighten caller limits to at most
80 source lines / 4,000 characters by default. Cached retrieval still consumes tool-call
admission and records invocation provenance. Hypotheses/assessments store references and
compact explanations; the shared transcript still retains bounded tool messages. No
automatic history compaction exists; context exhaustion remains an explicit partial result.

Existing defaults apply: 100,000 context characters, 14 RPM / 250,000 TPM, retries and
hard model/tool/token/time guards. Node/route logs and result trace expose decisions;
tool activity reports durations/cache hits without source or arguments. Provider usage
uses existing actual/estimated accounting. External cancellation propagates and clients
remain caller-owned; cancellation is not disguised as a successful report.

From `agent-server`:

```powershell
uv run pytest src/test-agents/test_component_adaptability.py -q
uv run python src/test-agents/run_component_adaptability.py C:\repos\project --request request.json
```

Example request: `{"targets":["src/reports"],"target_context":"Offline processing with a supplied storage backend"}`.
Optional `--config limits.json` accepts shared budgets and local bounds.
`--agent-config dummy` selects `config/dev-agents.yaml`'s existing entry by default.
Credentials come from root `.env` / `LLM_API_KEY`; optional LangSmith tracing is inherited.
Set `LANGSMITH_HIDE_INPUTS=true` and `LANGSMITH_HIDE_OUTPUTS=true` to hide source/results.
Untracked/dirty source cannot support accepted attribution to the checkout's Git commit.

Optional **paid** seeded evaluation, skipped unless explicitly enabled:

```powershell
$env:COMPONENT_ADAPTABILITY_LIVE = "1"
uv run pytest src/test-agents/test_component_adaptability.py -v -s -k live
```

`COMPONENT_ADAPTABILITY_AGENT_CONFIG` selects another YAML entry. The evaluation uses a
temporary copy of `src/test-agents/fixtures/component_adaptability/`, real source/tools
and the real provider. It requires a source-backed assessment, not a particular defect,
classification or wording. Offline tests use actual graphs/tools with simulated model
judgments; they establish orchestration/guards, not semantic precision across projects.

## Observed offline example

Actual graph/tools over a temporary seed copy, **simulated provider judgments**:

```text
plan_investigation -> investigate -> [use_tools] tools -> investigate
 -> [validate] evaluate_evidence -> [finalize] review_findings -> finalize
completed; 5 model calls; 4 tool calls
```

Abbreviated finding: `ADAPT-bebfb102022084f6`, accepted `verified_obstacle` for the
explicit target “Reuse with a supplied offline backend and no fixed production endpoint.”
`service.py:4-9` exposes no backend parameter on its public constructor;
`consumer.py:1-5` uses that default construction path; `backend.py:1-6` shows the fixture
client. Returned evidence covers `service.py:1-9`, `consumer.py:1-5`, `backend.py:1-6`.
The suggested adaptation is to review caller-supplied backend configuration **if needed**.
Attribute reassignment or external overrides may be alternatives; no universal absence
of seams or measured migration effort is asserted. The fixture client merely constructs
a dictionary: this example does **not** demonstrate a real production database connection.
