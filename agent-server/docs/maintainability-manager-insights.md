# Hierarchical maintainability manager

- `maintainability/manager/` exposes a native LangGraph runnable on the
  existing fresh-toolset/request protocol. The exact seven-node workflow has one coverage
  conditional edge and refinement returns directly to delegation. Forced finalization
  uses `yes` with `sufficient=false`; it cannot certify coverage through budget exhaustion.
- Supported dimensions are modularity and reusability. Requested unsupported dimensions
  remain explicit gaps, and unrequested dimensions are excluded from coverage. No full
  ISO/IEC 25010 coverage or numeric quality score is asserted.
- Uses real coordinators and the existing dispatch/accounting/structured-output runtime.
  Small hooks adapt configuration, nested evidence, prior-evidence lookup and correlated
  tracing. Their internal workflows and investigator analyses remain independent.
- Nested ledgers belong to investigators. Collection validates typed nested provenance and
  usage, preserves specialized outputs on JSON round-trip, and rejects stale/duplicate
  attempts without overwriting prior evidence or charging twice.
- Manager model context is compact: summaries, qualifiers and stable references. Initial
  nested recovery testing caught context growth from serializing full evidence repeatedly;
  full assessments remain only in reporting/state, not duplicated into synthesis prompts.
- Coverage requires each coordinator's completed source-backed investigator coverage,
  no material gaps and no blocking manager conflict. Empty findings are valid but absence
  of evidence is not. Supported targeted retries may recover coverage while retaining
  failures; identical requests, stalled progress and all hierarchy limits remain bounded.
- Manager/child envelopes are separate from unchanged coordinator defaults. Whole child
  budgets are reserved before parallel dispatch; returned nested consumption is counted
  once. One pacer shares 14 RPM / 250,000 TPM through the hierarchy on one event loop.
- Deterministic manager tests use controlled outputs; nested E2Es execute real manager,
  coordinators, six investigators and tools with simulated provider judgments. They write
  report/events/node artifacts outside the checkout. Optional real-provider smoke uses
  `MAINTAINABILITY_MANAGER_LIVE=1`; offline results do not establish semantic precision.
