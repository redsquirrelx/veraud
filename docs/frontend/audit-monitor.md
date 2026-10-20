# Global audit monitor

The application `Dock` mounts `shared/audit-monitor/LiveAuditMonitor` instead of
the previous `AgentMenu`. It drives the existing non-modal `AuditStatusDrawer`,
including expandable audits, pipelines and agent rows. Its tab is available even
when no runs are recorded. Opening it leaves the rest of the page usable.

## Real data

- `AgentExecutionsProvider` remains the single WebSocket subscription and restores
  the most recent 50 execution IDs after refresh/reconnect.
- HTTP lookups supply `monitorContext`: project identity, branch, revision,
  evaluation type and declared agent context. Direct runs have no invented project.
- `GET /api/agent-executions/:id?monitor=true` returns a compact quality-audit result:
  selected attributes, evaluation states and recorded invocation receipts. It
  excludes source inventories, evidence content, Blackboard snapshots and Word bytes.
  The original GET and project-scoped report downloads retain the complete artifacts.
- Terminal lifecycle events trigger another lookup. A completion arriving while an
  initial lookup is pending queues a follow-up; stale HTTP state cannot revert the
  live lifecycle, and compact results/context survive subsequent lightweight events.
- The agent catalog supplies quality/workflow grouping. Metadata is never treated
  as proof that a participant ran. Until individual receipts are published, only
  the actual backend orchestrator row is shown. Missing attribute state displays
  “Not reported”; a joint orchestrator is counted once under `quality-audit`.
- Final report invocation IDs populate retrospective agent rows with their actual
  statuses and reported usage. A completed backend request can still show a partial
  or failed quality evaluation. Missing tokens remain unreported rather than zero.

`executionAudits.ts` is the pure adapter between execution/catalog data and
`AuditStatusModel`. Project stages share one group per evaluation; independent
direct runs stay separate. Runs without a project do not render repository links.
The drawer/views remain reusable with fixture models in the component showcase.

## Checks

```bash
pnpm exec vitest run src/shared/audit-monitor src/shared/agent-monitor/agentMonitor.test.tsx src/features/project-management/useAnalysis.test.tsx
pnpm exec tsc -b
```

Backend integration tests cover HTTP monitor context, compact responses and
preservation of the original downloadable report artifacts.
