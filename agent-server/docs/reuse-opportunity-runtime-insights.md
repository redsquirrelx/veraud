# Reuse-opportunity runtime notes

- `ReuseOpportunityAgent` lives in `maintainability/reusability/reuse_opportunity/`; its prompts
  are local. It extends the existing investigator interface, not `BaseAgent`/HTTP
  pipelines. No reusability coordinator currently exists; modularity dispatch is unchanged.
- Python AST and JS/TS/TSX Tree-sitter symbols support bounded function/method pair
  discovery. Identifier-erased shapes and shared vocabulary can shortlist renamed or
  differently written behavior, but are not semantic equivalence or quality scores.
  Current static imports are not a complete call/data-flow graph. Other languages and
  unindexed constructs have no automatic discovery guarantee.
- Positive recommendations require inspected implementation bodies and caller context
  at verified static relationships. Conditional comparisons retain unknowns. Distinct
  business semantics, side effects and intentional isolation can justify no opportunity.
- Native LangGraph conditional edges use closed enums for tools/validation and
  inspection/normal/limited finalization. Node/route logs and result `execution_trace`
  make actual execution visible; shared budgets, retries and 14 RPM / 250,000 TPM apply.
- Existing compact/cache tools are enabled, with smaller default source reads. Identical
  retrievals reuse the cache but still consume call admission. History compaction is not
  implemented; bounded transcripts can still hit the hard context cap.
- `completed` means selected comparisons passed investigation/review, not global coverage
  or mandatory refactoring. Filter accepted findings AND their classification; inspect
  linked `examined_groups` for concrete differences, conditions and risks. Errors/limits
  preserve evidence with partial/failed status. Caller cancellation propagates.
- Deterministic tests use actual graphs/indexes/tools and simulated model judgments.
  Google native schemas/tools/usage are also tested with mocked transport, not paid API
  calls. `REUSE_OPPORTUNITY_LIVE=1` enables the optional paid seeded evaluation. See the
  agent README for commands, an observed offline trace and a source-backed sample view.
