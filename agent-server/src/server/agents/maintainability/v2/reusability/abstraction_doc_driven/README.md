# AbstractionAgent V2 — bounded abstraction planning slice

This package establishes the abstraction investigator's contracts, configuration,
shared `InvestigationAgent` lifecycle, graph topology and runner.

`plan_investigation` currently normalizes documentary claims from
`ArchitectureContextResult` into stable, context-revision-local IDs
(`{document_index.index_id}:{zero_based_position}`), then builds a bounded,
source-free menu of abstraction candidates. Questions are scoped to concrete
architectural guarantees — substitution, independence, encapsulation,
extensibility or reuse — never to functional correctness or generic usefulness. Candidates are:

- interfaces, protocols and abstract classes recognizable from the index;
- documented helpers and type-alias contracts explicitly named in documentation;
- structurally supported candidates with implementers or internal consumers;
- documented candidates paired with the recorded documentary claims.

Documentation matched conservatively through explicit file, module or symbol
references orients selection; ambiguous correspondences are never invented.
Claims about tests are not abstraction purposes. Each candidate carries the
abstraction name and kind, scope, related components (implementations and
consumers), documented purpose or `unknown`, purpose basis (`explicit`,
`inferred`, `unknown`), indicators, a question and traceable
`document_claim_ids`.

Definitive investigation closures require `evidence_assessments` for every
indexed `evidence_needed` requirement. Each resolved or not-applicable requirement
needs a mechanism rationale, delivered source citations and an inspected scope.
Pending requirements or documentary claims prevent `no_finding`; the model must
retrieve the missing evidence or close inconclusive. Conclusions concern only
the inspected sample. These checks enforce traceability, not automatic semantic
verification of whether a quotation proves an architectural assertion.

A single LLM call then selects candidates and formulates concrete questions;
the host validates IDs, assignments, sizes and question location requirements.
`investigate` then runs per selected candidate: the host injects
`get_source_excerpt` (primary and up to three related implementation or
consumer files, 60 lines each), `list_relationships` and `find_symbols`;
coverage_gap requires inspecting at least one implementer or consumer before a
conclusion; the model requests tools or closes with a structured turn; the
host validates evidence, coverage (including implementation/consumer
uninspected files) and claim assessments; each conclusion updates its
hypothesis (`confirmed` / `discarded` / `inconclusive`). Each candidate may
consume up to 5 iterations.

`synthesize` and `finalize` then consolidate investigation results deterministically:
merge candidates by id, compute documentary coverage, produce provisional
`AbstractionFinding` records with `validation_status="insufficient_evidence"`
(consolidated provisional candidate; no critical review performed). The runner
prints hypotheses, investigations and findings.

The state retains `current_investigation`, `pending_queries`, `investigation_results`,
`candidates`, `synthesis` and `documentary_synthesis`; raw documentary indexes are not
retained. Documentary claims selected into the final plan are copied into
`plan.document_claims` with their positional IDs and evidence for traceability.

`provider_request` emits `[DEBUG_LLM_RAW <node>]` to stderr like the Responsibility
runner. The common runtime supplies tracing, provider pacing/retries, invocation
reporting, cancellation, repository snapshot tools and accounting.

The process budget switch remains controlled by `launch.json`; this package does
not override it. The current checkout has `budgets_enabled=false`. Output allowance
defaults to 40,000 tokens per model response.
