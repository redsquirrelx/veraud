# AbstractionAgent V2 — bounded abstraction planning slice

This package establishes the abstraction investigator's contracts, configuration,
shared `InvestigationAgent` lifecycle, graph topology and runner.

Claims are referenced by positional ID (`claim-{zero_based_position}`), local to
one committed `ArchitectureContextResult` revision, never a global hash, and they
must not survive reindexing. The plan's `document_claims` catalog holds a nested
`DocumentClaimRecord` per relevant claim — `{claim: KnowledgeClaim,
document_index, section_paths, status, reason, scope_paths}` — covering
applicable, uncertain, unmapped and not_applicable records (not only matched
ones); the final plan and result retain only claims bound to selected
candidates. Matching is conservative: explicit identifier strength scoring over
the indexed pool, never invented correspondences; ambiguity between equally
explicit abstractions yields `uncertain`, never an invented owner. Claims about
tests and claims outside abstraction categories are catalogued `not_applicable`.
Selected candidates hold at most `max_documentary_claims_per_candidate` claims
(default 6); documented claims beyond the cap are trimmed deterministically in
phase 1, and explicit non-testing claims with no index anchor may be attached by
capability affinity (shared distinctive tokens; one shared directory segment also
binds). Affinity never overrides phase 1; affinity claims remain hypotheses of
relevance, not authoritative assignments.

`plan_investigation` normalizes documentary claims from `ArchitectureContextResult`,
then builds a bounded, source-free menu of abstraction candidates. Questions are
scoped to concrete architectural guarantees — substitution, independence,
encapsulation, extensibility or reuse — never to functional correctness or generic
usefulness. Candidates are:

- interfaces, protocols and abstract classes recognizable from the index;
- documented helpers and type-alias contracts explicitly named in documentation;
- structurally supported candidates with implementers or internal consumers;
- documented candidates paired with the recorded documentary claims.

Each candidate carries the abstraction name and kind, scope, related components
(implementations and consumers), documented purpose or `unknown`, purpose basis
(`explicit`, `inferred`, `unknown`), indicators, a question and traceable
`document_claim_ids`. The selection menu carries each candidate's claim payload
(`id`, `subject`, `statement`, `constraint`, `certainty`) and no separate
`document_claim_ids` array, so obligation requirements anchored to a `claim_id`
remain possible while payload size stays bounded by the per-candidate cap.

A single LLM call then selects candidates and formulates concrete questions; the
host validates IDs, assignments, sizes and question location requirements.
`investigate` then runs per selected candidate: the host injects
`documentary_context` (host-verified claims for this task; provenance-incompatible
or undeliverable claims surface as `unavailable_claims` with reasons instead of
being silently delivered), `get_source_excerpt` (primary and up to three related
implementation or consumer files, 60 lines each), `list_relationships` and
`find_symbols`; coverage_gap requires inspecting at least one implementer or
consumer before a conclusion; the model requests tools or closes with a
structured turn; the host validates evidence, coverage (including
implementation/consumer uninspected files), claim assessments and
candidate/documentary linkage — cited claims must be contradicted, with the
assessment's code evidence included in candidate evidence, a finding_candidate
must cite every contradicted assessment, and supported/not_applicable claims do
not independently justify a candidate. Each conclusion updates its hypothesis
(`confirmed` / `discarded` / `inconclusive`). Each candidate may consume up to 5
iterations. The host records a `document_claim_delivery` receipt at close and
inserts host-pending inconclusive assessments for claims with no validated model
assessment, so nothing documentary silently disappears.

`synthesize` then consolidates deterministically: candidates are merged by id;
`documentary_synthesis` is a validated `DocumentarySynthesis` consolidating local
observations per claim — local assessments with delivery receipts, coverage
counts, scope comparisons and `global_compliance_established=False` — carrying
integrity issues. `finalize` produces provisional `AbstractionFinding` records
with `validation_status="insufficient_evidence"` (consolidated provisional
candidate; no critical review performed). The runner prints hypotheses,
investigations and findings.

The state retains `current_investigation`, `pending_queries`, `investigation_results`,
`candidates`, `synthesis` and `documentary_synthesis`; raw documentary indexes are not
retained. Documentary claims selected into the final plan are copied into
`plan.document_claims` with their record and evidence for traceability, and
`candidate_origins` carry the candidate's `document_claim_ids`.

`provider_request` emits `[DEBUG_LLM_RAW <node>]` to stderr like the Responsibility
runner. The common runtime supplies tracing, provider pacing/retries, invocation
reporting, cancellation, repository snapshot tools and accounting.

Token economy follows the responsibility investigator: per-candidate documentary
claims are capped (`max_documentary_claims_per_candidate`), the documentary
context is character-capped at delivery time (claims beyond the cap are recorded
unavailable, never silently truncated), the planning menu carries question-essential
claim fields only (no statements outside the per-candidate cap, no duplicated
`document_claim_ids` array), and identical excerpts are served from cache. This
payload remains richer than the responsibility menu because obligation-derived
requirements are anchored to claims at selection time; the investigate prompt
still receives the validated delivery receipt.

The process budget switch remains controlled by `launch.json`; this package does
not override it. The current checkout has `budgets_enabled=false`. Output allowance
defaults to 40,000 tokens per model response.
