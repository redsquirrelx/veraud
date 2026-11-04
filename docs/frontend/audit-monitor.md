# Global audit monitor

The application `Dock` mounts `shared/audit-monitor/LiveAuditMonitor` instead of
the previous `AgentMenu`. It drives the existing non-modal `AuditStatusDrawer`,
including expandable audits, pipelines and agent rows. Its tab is available even
when no runs are recorded. Opening it leaves the rest of the page usable.

## Real data

Invocation rows form expandable manager → coordinator → investigator branches
using `parent_invocation_id` from compact receipts, with the real root agent as
the group header, rather than repeating its category
and then rendering the same root inside. Empty or unidentified groups retain a
generic category header. Each branch retains its own
state and usage; the monitor shows one row per agent type within each audit.
Repeated invocations update that row from the latest start time (receipt order
for historical reports without timestamps), including its ID, state, usage,
timestamps and error. Progress counts distinct agents. Branch expansion and
first-appearance ordering survive invocation changes; retained children resolve
historical parent IDs to the parent's current row. Missing parents or cyclic
historical links remain visible as roots. The playground includes nested branches.
Participant receipts arrive through lifecycle callbacks while the audit runs.
The final report reconciles those rows by invocation ID without adding duplicates.

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
  “Not reported” when no execution or attribute outcome is available.
  `maintainability_manager` belongs to Maintainability and `security` belongs to
  Security, including joint audits and before catalog loading. Functional adequacy
  uses its own `functional_adequacy` root and attribute label. Descendants stay
  in their actual root's category; each agent type is counted once.
- Live callbacks carry invocation/parent IDs, agent/run identity, timestamps,
  cumulative provider usage and terminal outcomes. Refresh restores persisted receipts.
  Active agent rows also show a translated phase badge from the actual graph node
  or security stage. `phase_sequence` orders transitions per invocation so stale
  hydration and callbacks cannot roll the badge back. Terminal updates clear it;
  historical receipts without phase information show only their lifecycle status.
  Phase changes bring the blue background and glow up over 160 ms, hold the peak
  until 240 ms, then fade over 1.2 seconds. Token updates do not restart it.
  This phase highlight runs regardless of the system's reduced-motion preference.
  Native investigator and coordinator/manager synthesis calls publish cumulative
  provider input/output tokens to their own invocation after each attempt. Child
  usage is not copied into the parent row. Missing usage stays unreported; budget
  reservations and estimates are never displayed as provider-reported tokens.
  Rows reuse `AgentTokenUsage` from the previous agent menu: total tokens,
  budget bar/percentage when a captured budget is available, limits and an
  expandable input/output/estimated breakdown. An orchestrator's captured budget
  is not assigned to its children; missing per-agent budgets remain unrecorded.
- Final report invocation IDs reconcile agent rows with their actual
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
