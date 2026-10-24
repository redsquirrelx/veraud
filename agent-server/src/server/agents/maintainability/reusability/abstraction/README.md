# AbstractionAgent

Independent, read-only maintainability investigator for **reusability**:

> Do abstractions facilitate reuse, or introduce unnecessary complexity and coupling?

Recognizes beneficial abstraction, unnecessary indirection, concrete coupling, missed
reuse, justified boundaries and inconclusive investigations. More abstraction is not
automatically better; one implementation does not establish overengineering.

## Integration map

Paths below are relative to `agent-server/src/`:

| Existing extension point | Integration |
| --- | --- |
| `server/runtimes/investigation/agent.py`: `InvestigationAgent` | Established `await agent.run(fresh_toolset, request)` interface; injected model/wrapper and optional shared `provider_pacer`. |
| Same file: `InvestigationExecution` | Inherited native `StateGraph`/`ToolNode`, structured output, bounded corrections/retries, logs, token accounting, cancellation, time/tool/context guards and commit verification. |
| `server/runtimes/investigation/schemas.py` | Extends `AuditRequest`, `InvestigationConfig`, `Evaluation`, `Finding` and `AuditResult`; preserves provenance and original rejected/unsupported candidates. |
| `server/runtimes/repository/tools.py` | Reuses all seven existing bounded, read-only inspection tools and evidence ledger. |
| `server/services/repository_analysis/schemas.py` | Existing symbol, inheritance/base-name and relationship indexes provide deterministic candidate navigation; no new parser or graph service. |
| `server/app/tracing_port.py` | Standalone harness wraps execution with existing tracing; native graph/model calls inherit tracing. |
| `test-agents/run_architecture_boundary.py` | Shared YAML/`.env` loader, snapshot creation, execution budgets, LangSmith span and caller-owned client cleanup. |

There is no existing reusability coordinator using this investigator protocol. The
generic pipeline infrastructure described in `docs/agent-server/generic-pipelines.md`
uses `PipelineDefinition` and the `BaseAgent` execution service, a different contract.
No incompatible HTTP registration or new coordinator is introduced. The modularity
coordinator intentionally retains its original three investigators; this agent does
not delegate and is not silently added to that registry.

## Workflow and conditional routing

The inherited graph maps the requested responsibilities to established node names:

```text
START -> plan_investigation [prepare context + hypotheses]
      -> investigate [inspect abstractions]
          -> tools -> investigate
          -> evaluate_evidence [validate findings]
              -> investigate, for specific evidence gaps while budgets permit
              -> review_findings [existing internal critical review]
                  -> finalize -> END
```

Both tool-use and evidence-sufficiency routes use native conditional edges. There is
no duplicated orchestration graph or independent reviewer agent. Domain checks run
during evaluation as well as finalization: unsupported declarations, relationships,
consumers, category/citation support and pending hypotheses become explicit evidence
gaps. The host can override an LLM's `sufficient=true`; hard budgets terminate loops.
An insufficient assessment without an actionable gap finalizes with limitations.

## Discovery, scope and validation

- `discovery.py` deterministically ranks top-level indexed declarations by incoming
  relationships and inheritance information, then stable path/line/ID ordering. Files
  without eligible symbols remain fallback candidates. Ranking is navigation, not a
  quality score. `max_candidates` defaults to 12; participant count defaults to 12.
- `AbstractionRequest.targets` contains repository-relative files/directories limiting
  assessed declarations. Relevant implementations and consumers elsewhere in the same
  accessible repository may be followed. Invalid/traversing/inaccessible targets are
  rejected. Tools retain the repository policy; this is not a separate filesystem sandbox.
- `AbstractionPlan.hypotheses[].declaration_ids` explicitly binds each original question
  to its committed selected declarations. Exact selected IDs are preferred; exact file
  paths (all selected declarations in that file) and `path:qualified_symbol` are normalized
  to IDs. Unknown/empty bindings remain blockers. Evaluations cannot replace the original
  question or attach declarations outside that binding to support a conclusion.
- Candidate metadata cannot support a finding. Source ranges must cover the complete
  indexed declaration body; each behavioral participant requires inspected body source
  and an explanation. Imports and single-line search matches alone do not suffice.
- Consumer/implementation/test/composition links require actual resolved internal
  relationships to the abstraction; delegate/contract links use the opposite direction.
  Their source declaration anchors must have been inspected. Metadata, an unrelated
  excerpt, unknown IDs or unverifiable commit attribution cannot support acceptance.
- Missed reuse requires distinct inspected components, a concrete duplication comparison,
  compatible variation analysis and reuse benefit. No dependency is required between
  independent duplicated implementations.
- Useful abstraction requires actual consumer evidence plus benefit/variation analysis.
  It is reported as an info-level design observation, never a compliance violation.
- Unnecessary abstraction requires consumer and delegate/implementation evidence, a
  concrete indirection cost, counterevidence analysis and a proportional alternative.
  Coupling requires an explained reuse consequence. Single-implementation boundaries
  can be `justified_boundary`, with discarded hypotheses and no negative finding.
- Exact duplicate accepted concerns are consolidated conservatively; duplicate candidates
  remain rejected with `duplicate_of`, retaining original review/evidence history.
- Invalid linked assessments downgrade resolved hypotheses during evaluation. Final
  resolution also requires exactly one independent scope review, valid assessments bound
  to the same hypothesis and checked source citations, including candidate-free runs.
  `critical_review` retains the model judgments; final host statuses are authoritative.
- Review supplies an explicit `resolution` and must cover every committed declaration
  and all linked assessment citations. It can resolve a prior host downgrade after valid
  repair; `hypothesis_validation_history` retains each proposed and host-validated state.
  Unrelated assessments are retained as inconclusive without contaminating a scoped
  conclusion. Out-of-scope findings still cannot be accepted.
- Bounded navigation supplies real relationship endpoints and missing source reads.
  Repeated unchanged validation/source coverage stops as `no_investigation_progress`.
  Closing token reservations preserve evaluation/review headroom under the hard budget.

## Result and execution

`AbstractionResult` preserves shared fields and adds `investigator`,
`quality_attribute="reusability"`, `status`, `abstractions_investigated`, `coverage`,
`inconclusive_investigations` and content-free `tool_failures`. Findings add `category`,
`assessment_ids` and `basis`. Existing `modularity_impact` carries the reuse/maintenance
consequence for protocol compatibility. Existing numeric confidence is a model/review
estimate, not a new calibrated score or a newly invented quality threshold.

`completed` requires sufficient evidence, completed review, resolved planned declarations
and no unsupported findings or pending hypotheses. `partial` preserves incomplete
investigations and results at limits; `failed` denotes failure before a usable plan/source
investigation. Empty findings are not evidence of compliance or global reuse quality.
Consumers must filter findings by `validation_status == "accepted"`.
Coverage separates `planned_declarations` from `unplanned_candidates`; discovery is not
a promise to assess every indexed candidate. `unassessed_candidates` records outstanding
planned declarations. A completed scoped investigation may retain an inconclusive
out-of-scope side assessment; its status does not certify that side assessment.

All shared defaults apply, including 100,000 context characters and provider admission
limits of 14 RPM / 250,000 TPM. Explicit config can change budgets and rate limits.
Native models receive the existing lean-schema projection to reduce generation
complexity; original Pydantic constraints remain enforced locally. Adapter compatibility
is tested with the actual Google adapter and mocked transport, including native tools,
output caps and provider-reported token accounting, without paid calls.
Clients remain caller-owned; no writes, persistence, refactoring or code execution occurs.

From `agent-server`:

```powershell
uv run pytest src/test-agents/test_abstraction.py -q
uv run python src/test-agents/run_abstraction.py C:\repos\project
uv run python src/test-agents/run_abstraction.py C:\repos\project --request request.json --config limits.json
```

The live runner uses `config/dev-agents.yaml` (`--agent-config dummy` by default),
`LLM_API_KEY` from `.env`, and optional `LangSmithTracingBackend`. Use
`LANGSMITH_HIDE_INPUTS=true` and `LANGSMITH_HIDE_OUTPUTS=true` to hide source/results.

## Known limitations

Static index/source checks establish provenance and minimum structural support, not
semantic equivalence, beneficial reuse, actual runtime dispatch or historical causality.
Interpretation and critical review remain LLM responsibilities. Dynamic/external or
unindexed usage remains inconclusive, not a negative conclusion. Source-only inferred
links are deliberately not promoted to verified graph links in this version.

Discovery is bounded and not exhaustive; nested declarations and unsupported language
features may need targeted source investigation or remain uncovered. Narrative docs
are excluded by the existing access policy; architectural intent must be declared or
supported by accessible code. Provider-history compaction preserves cited source and the
authoritative ledger/history, while reducing old uncited tool payloads. `inspected_paths`
means files with retrieved fragments, not complete file inspection. Offline fixtures
exercise real graphs/tools with simulated provider responses and do not establish live
provider reliability or semantic precision across arbitrary repositories.
