# Global Execution Explorer (live iteration)

The application header/sidebar carries an **Executions** button (next to
Home/Settings in `AppMainNavigation`). It opens the **Execution Explorer**, a
global modal meant to eventually replace the floating audit tab. The current
iteration shows **live quality audits, architecture-context executions and
verification-suite generations, read-only** — everything else stays out.

## What exists today

- `src/shared/execution-explorer/`:
  - `useExplorerExecutions.ts` — the live read path. Reads `useAgentExecutions()`
    (the WebSocket feed + HTTP hydration already used by the audit monitor) and
    the `listAgentSettings` catalog, then keeps quality-audit groups (`monitorContext.evaluationType === "QualityAudit"`, or a known audit root agent — `maintainability_manager` / `security` / `functional_adequacy` — while the row is not hydrated yet), architecture-context runs (`evaluationType === "ArchitectureContext"`, or a WS-only `architecture_context` root) **and verification-suite generations** (`evaluationType === "VerificationSuite"`, or a WS-only `verification_suite` root). Rows are tagged `kind: "audit" | "agent"`; the type filter (`All executions` / `Audits` / `Standalone agents`, with counts) distinguishes audits from agents, keeping semantics and bucketing identical to the monitor.
  - `explorerPresentation.ts` — title builder ("Maintainability + Security · #1231"),
    agent-forest flattening and shared counters over the `AuditStatusModel` tree.
  - `ExecutionExplorerContext.tsx`/`ExecutionExplorerProvider.tsx` — app-wide
    provider/hook (`useExecutionExplorer()` → `{ openExplorer(executionId?), close() }`).
    Mounted once in `AppLayout`; `openExplorer(executionId)` preselects that
    audit when it opens — the seam for contextual opening later.
  - `ExecutionExplorerModal.tsx` — portal modal (~`min(1400px, 100%)` x `85vh`),
    focus trap + focus restoration, background `inert`, Escape and
    overlay-click close, body scroll lock. Type filter (`All executions` /
    `Audits` / `Standalone agents`, with counts) + status filter (`FilterTabs
    compact`, scrollable) + search. Agents list without hierarchy; audits keep
    their tree.
  - `ExecutionList.tsx` / `ExecutionInspector.tsx` / `ExecutionTree.tsx` /
    `ExecutionNodeDetail.tsx` — the two-panel layout. Architecture-context
    runs render directly in the detail pane (no artificial hierarchy), with
    state pill, `AgentTokenUsage` budget bars and per-node errors. Audits keep
    the manager → coordinator → investigators tree with live phases and the
    real pipeline label in the title. Completed executions stay reachable under
    the **Completed** tab; nothing else is removed.
- The button shows a count badge of queued/running/cancelling executions via
  `useAgentExecutions()` (only when > 0). It uses the same feed but does not
  feed the modal.
- Events / Traces / Results render as disabled "coming next iteration" tabs.
- i18n namespaces: `executionExplorer` (es/en) plus `navigation.executions(…)`
  in `common`.

**Verification-suite generations** (the agentic code-writing step) appear as one
agency row per build (`Verification Suite · #id`), with **ftg (Finding Test
Generation) and probe (Testability Probe) receipts as children** — state,
phase, tokens. The deterministic suite validation (`action=execute`) is not
attached to this tracking (yet).

## Responsive behavior

Below 720px the modal goes full-viewport and the panels switch to a
list → detail navigation with a "Back to list" button; the desktop split view
shows both panes. Selection always lands on the detail pane on mobile.

## Design decision worth knowing

The filter heuristic in `useExplorerExecutions` intentionally treats the agent as
identified by root agent type *before* HTTP hydration, so WS-only rows appear
immediately instead of flickering in after the `?monitor=true` lookup returns.
Joint audits share one `evaluationId` and appear as a single grouped row.

## Checks

```bash
pnpm exec vitest run src/shared/execution-explorer src/app src/shared/ui-kit src/shared/i18n
pnpm exec tsc -b
```

Note: the full-suite run on this machine is flaky under parallel load; the only
persistent failures are the two `ProjectDetailPage.test.tsx` cases, which fail
identically without these changes (uncommitted WIP in that file's area).
