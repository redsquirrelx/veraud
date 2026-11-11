# ReuseOpportunityDocDrivenAgent V2 — planning plus evidence investigation

The package implements one V2 investigator node: `plan_investigation`, plus the evidence-driven `investigate`/`tools` loop. Unlike Responsibility V2,
it does not build a deterministic per-file menu: the model correlates supplied
architectural claims into capability-centered reuse investigations through three internal
LLM phases (not graph nodes):

1. `identify`: complete statement projections identify provisional reuse capabilities;
   each must be a concrete reusable functional unit, not an architectural rule,
   dependency-inversion mechanism or decoupled interface by itself.
2. `correlate`: all discovered capabilities are considered globally. They are merged only
   when they describe substantially the same functional capability and the same documented
   reuse intention. Sharing an architectural flow, layer, domain, section or label is not
   sufficient. Seeds limited to conformance, decoupling, provider swapping or abstraction
   effectiveness are excluded. Each seed is accounted for in a group or an explicitly
   reasoned exclusion; the rationale identifies the common capability and shared intention.
   The model may keep analogous capabilities separate and merge differently named
   equivalents. The global claim locator catalog allows complementary claims from other
   portions to be requested by ID.
3. `formulate`: original claims, quotations, reasoning, permissions and exceptions are
   recovered from the whole input before questions are produced. Same-section and exact
   documented-entity neighbors are supplied as context, not automatically as obligations.
   The generated question names a concrete behavior, its actual or unknown consumers and
   providers, and asks for the reuse-or-separation decision. It assesses duplicated
   behavior, behavior already supplied by a shared component, duplicated centralization,
   semantic/contract equivalence, architecture and exceptions as applicable. Each question
   includes a documented reuse expectation, providers/consumers (possibly unknown), and
   uncertainty requiring subsequent source inspection. If evidence supports
   architecture/decoupling only, no investigation is produced.

Context size includes escaped messages, the prompt and schema envelope. The formulator receives
validated `indexed_target_candidates`: indexed files or directories explicitly mentioned by the
group's documentary context, capped at 30 and grounded in the snapshot. Paths appearing only in
documentary text are never silently accepted; the model may use a shown candidate or `[]`.
Navigation is removed before documentary evidence if a request is too large. Full claims are
never truncated to force a fit.
Oversized groups remain pending. All phases use existing provider pacing, retries,
budgets and accounting; no additional graph stage or independent budget is introduced.

Every omitted claim, incomplete phase, unresolved capability and pending group is reported
in planning diagnostics. Statements sent, discovery processed and original evidence reviewed
are distinguished. Full reviewed claims (including complementary exceptions) are retained
in the output. The host validates claim references and indexed files or directories
containing indexed files, and assigns stable IDs. Initial targets may be empty when
localization is unknown; they are hints, not investigation boundaries. Validation errors
supply trusted error codes and concrete correction guidance to the bounded retry loop,
and phase diagnostics distinguish validation from provider/schema failure. Empty plans are valid
when the documentary context does not establish reuse intent.

3. `investigate`: a hypothesis-scoped workspace indexes relevant providers, consumers and
   alternatives by documentative labels, indexed symbols and incoming relationships. It
   reads exact function ranges rather than first-lines/directories, can continue oversized
   functions as successive bounded tool calls, and resolves `path#symbol` conservatively.
   The model returns evidence-aware `tools` or a scoped close. Deterministic queries
   discover relevant source bodies, consumers, and missing comparison pairs; discovery
   hints are never treated as proof of duplication.

   Reusable comparison workspaces retain active function bodies on the authoritative
   evidence ledger while exposing only recent or omitted-result views in model context.
   The model retrieves documentary claims by ID when compact projections are insufficient.
   A close is not simply trusted: the controller validates candidate structure, citation
   provenance, exact scope, symbol coverage and a resolved comparison. Missing bodies are
   appended as focused tool work rather than sent back as schema-only retries.

   `reuse_opportunity` requires provider and independent implementation coverage plus an
   equivalent shareable comparison. `no_reuse_opportunity` requires an adequately covered
   comparison for inspected consumers/alternatives; it is not universal absence of duplication.
   `inconclusive` retains explicit limits and no candidate. Premature closes continue if useful
   tools exist; repeated no-progress turns stop without loops. Candidate comparison remains
   an investigator judgment, not a declaration of compliance.

   The frontier prunes weak alternatives once enough leads exist and fails open only for
   explicitly relevant providers/consumers. Investigation diagnostics are intentionally
   compact: counts, role coverage, deferred leads, comparison resolution and brief budget/progress
   rather than complete entity payloads or bodies.

`investigation_complete` means that the source investigation loop finished and every attempted
investigation produced a scoped result, not that the repository complies or a reviewed finding exists.
`investigation_partial` is required whenever any part of planning or investigation remains inconclusive;
a completed Investigation never adds external findings.
`planning_only` means planning occurred but source investigation could not establish an outcome.
There is no automatic list concatenation or exact-label consolidation after formulation.

The graph ends after the investigate/tools loop; no final synthesis, review or finding publication occurs. The runner accepts `--architecture-context`, supports readable/JSON output and optional `--output-file`, and uses the shared model, tracing, budgeting, cancellation and repository-snapshot services.
