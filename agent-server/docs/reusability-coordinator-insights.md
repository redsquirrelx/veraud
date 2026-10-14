# Reusability coordinator: integration notes

- `maintainability/reusability/` coordinates exactly the three implemented reusability
  investigators. It has five executable nodes plus the decision edge from synthesis:
  yes returns directly to delegation; no finalizes. No additional planner/reviewer/
  limited-finalizer node exists. Synthesis prepares follow-ups and limit reasons.
- Reuses `ModularityAgent`'s dispatch, reservations, collection, native synthesis and
  quota infrastructure through small contract/registry hooks. Existing modularity
  topology/defaults remain intact. Public exports and the shared YAML runner expose
  execution; HTTP `BaseAgent`/`PipelineDefinition` registration is a different contract.
- All requests receive real `targets`; adaptability also receives the optional target
  context unchanged. Typed union results preserve specialized findings/coverage and
  explicit partial/failed status through JSON, instead of flattening to `AuditResult`.
- Each assessment/request/invocation/round has identity. Workers never concurrently
  mutate shared result lists: bounded gather returns a batch, collection appends once.
  Genuine observations survive malformed/failed returns, without accepting their claims.
- Namespaced ledger-backed source refs, source ranges/hashes and Git attribution guard
  supported conclusions. Group same-polarity equivalents; link distinct tradeoffs rather
  than erase them. Contradictions stay disputed until grounded targeted resolution.
- Follow-ups require material gaps and remaining resources. Duplicate completed work,
  same-question failure retry loops and zero-progress rounds are bounded. New retrieval
  IDs alone do not count as new source. Failed/limited work takes the ordinary no edge.
- Shared provider admission remains 14 RPM / 250,000 TPM, including synthesis/retries.
  Whole-child reservations and the caller's stricter budget may skip dispatch even if
  coordinator config alone looks sufficient. All prior warnings/results remain visible.
- Offline graph tests do not prove semantic accuracy. Separate integration runs actual
  investigators/tools with simulated models. `REUSABILITY_E2E_LIVE=1` enables an optional
  paid seeded smoke; no paid calls are required for deterministic verification.
- Dedicated E2Es: `uv run pytest src/test-agents/test_reusability_e2e.py -v -s`.
  Default-registry investigators/graphs/tools are real; only model responses are
  simulated. Visible tracing events/reporting distinguishes assessment status from
  pytest status. The live opt-in now lives only in this suite, avoiding duplicate
  paid smokes in `test_reusability.py` and the E2E file.
