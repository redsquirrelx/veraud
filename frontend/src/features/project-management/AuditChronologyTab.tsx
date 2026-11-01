import { useEffect, useRef, useState } from "react"
import { auditStateFrom } from "../../shared/audit-monitor/auditStatus.ts"
import { useAuditStateLabel, useMonitorLabels } from "../../shared/audit-monitor/monitorLabels.ts"
import { formatDateTime, formatNumber } from "../../shared/i18n/format.ts"
import { Button, Pagination, Spinner } from "../../shared/ui-kit/index.ts"
import { useAuditAgentCatalog } from "./auditAgentCatalog.ts"
import { eventInvocationPaths, loadExecutionEvents, type ExecutionEvent } from "./executionEventsApi.ts"
import { useAuditChronologyLabels } from "./auditChronologyLabels.ts"
import type { QualityAuditSummary } from "./qualityAuditApi.ts"
import { isQualityAuditActive } from "./projectStatus.ts"
import { ExecutionEventDescription } from "./ExecutionEventDescription.tsx"
import { ExecutionEventModal } from "./ExecutionEventModal.tsx"
import { executionEventPresentation } from "./executionEventPresentation.ts"
import { useTranslation } from "react-i18next"
import "./AuditChronologyTab.css"
import "../../shared/audit-monitor/AuditStatusView.css"

export function AuditChronologyTab({ active, audit, revision }: { active: boolean, audit: QualityAuditSummary, revision: number }) {
  const labels = useAuditChronologyLabels()
  const { i18n } = useTranslation("projects")
  const fields = useMonitorLabels()
  const stateLabel = useAuditStateLabel()
  const catalog = useAuditAgentCatalog(active)
  const [attempt, setAttempt] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(5)
  const [order, setOrder] = useState("newest")
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())
  const [visibleCounts, setVisibleCounts] = useState<Record<string, number>>({})
  const [selection, setSelection] = useState<{ key: string, eventId: string } | null>(null)
  const [resource, setResource] = useState<{ key: string, events?: ExecutionEvent[], error?: boolean } | null>(null)
  const key = `${audit.id}:${revision}:${attempt}`
  const pending = isQualityAuditActive(audit)
  const previouslyActive = useRef(false)
  useEffect(() => {
    if (!active) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    // Bounded final reads catch events acknowledged shortly after completion.
    let finalReads = !pending && previouslyActive.current ? 2 : 0
    previouslyActive.current = pending
    async function load() {
      try {
        const events = await loadExecutionEvents(audit.id, controller.signal)
        if (controller.signal.aborted) return
        setResource({ key, events })
      } catch {
        if (controller.signal.aborted) return
        setResource((previous) => ({ key, events: previous?.key === key ? previous.events : undefined, error: true }))
      }
      if (!controller.signal.aborted && (pending || finalReads-- > 0)) timer = setTimeout(() => void load(), 3000)
    }
    void load()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [active, key, audit.id, pending])

  if (!active) return null
  const refresh = () => { setPage(1); setAttempt((value) => value + 1) }
  if (resource?.key === key && resource.error && !resource.events) return <div role="alert">
    <p>{labels.loadFailed}</p><Button variant="secondary" onClick={refresh}>{labels.retry}</Button>
  </div>
  const events = resource?.key === key ? resource.events : undefined
  if (!events) return <Spinner />
  const names = new Map(catalog.agents.map((agent) => [agent.agentType, agent.name ?? agent.agentType]))
  const selected = selection?.key === key ? events.find((event) => event.eventId === selection.eventId) : undefined
  const orderedEvents = order === "newest" ? [...events].reverse() : events
  const paths = eventInvocationPaths(orderedEvents, names)
  const identities = eventInvocationPaths(orderedEvents, new Map())
  const groups: { id: string, identity: string, path: string, events: ExecutionEvent[] }[] = []
  orderedEvents.forEach((event, index) => {
    const identity = `${event.runId ?? event.streamId}:${identities[index] || event.invocationId || event.streamId}`
    const group = groups.at(-1)
    // Never merge across intervening events: each block keeps its original
    // place in the global timeline, even when a route appears again later.
    if (group?.identity === identity) {
      group.events.push(event)
      // Anchor to the chronologically first event, not the smallest UUID:
      // new events must not remount an existing block on each live refresh.
      if (order === "newest") group.id = event.eventId
    }
    else groups.push({ id: event.eventId, identity, path: paths[index] || fields.notRecorded, events: [event] })
  })
  const pageCount = Math.max(1, Math.ceil(groups.length / pageSize))
  const currentPage = Math.min(page, pageCount)
  const offset = (currentPage - 1) * pageSize
  const pagination = <div className="quality-audit-pagination">
    <label>{labels.pageSize}
      <select value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1) }}>
        {[5, 10, 20].map((size) => <option key={size} value={size}>{formatNumber(size)}</option>)}
      </select>
    </label>
    <label>{labels.sort}
      <select value={order} onChange={(event) => { setOrder(event.target.value); setPage(1); setVisibleCounts({}) }}>
        <option value="oldest">{labels.oldest}</option><option value="newest">{labels.newest}</option>
      </select>
    </label>
    <Pagination page={currentPage} pageCount={pageCount} onChange={setPage} label={labels.pagination} />
  </div>
  return <section className="audit-chronology" aria-label={labels.tab}>
    <p className="audit-chronology-order" role="note">{labels.order}</p>
    {pending && <p role="status">{labels.pending}</p>}
    {resource?.error && <p role="alert">{labels.updateFailed}</p>}
    <div><Button variant="secondary" onClick={refresh}>{labels.refresh}</Button></div>
    {events.length ? <>
      {pagination}
      <div className="audit-chronology-scroll" role="region" aria-label={labels.tab} tabIndex={0}>
        <ol className="audit-chronology-groups" start={offset + 1}>{groups.slice(offset, offset + pageSize).map((group) => <li key={group.id}>
          <details className="audit-chronology-group" open={expanded.has(group.id)} onToggle={(event) => {
             const open = event.currentTarget.open
             if (!open) setVisibleCounts((previous) => ({ ...previous, [group.id]: 20 }))
            setExpanded((previous) => {
              const next = new Set(previous)
              if (open) next.add(group.id)
              else next.delete(group.id)
              return next
            })
          }}>
            <summary>
              <span className="mono audit-chronology-path">{group.path}</span>
              <span className="audit-chronology-date">{formatNumber(group.events.length)} {labels.events}</span>
               <time className="audit-chronology-date" dateTime={group.events[0].occurredAt}>{formatDateTime(group.events[0].occurredAt, { dateStyle: "short", timeStyle: "medium" })}</time>
               {group.events.at(-1)!.occurredAt !== group.events[0].occurredAt && <>
                 <span aria-hidden="true">→</span>
                 <time className="audit-chronology-date" dateTime={group.events.at(-1)!.occurredAt}>{formatDateTime(group.events.at(-1)!.occurredAt, { dateStyle: "short", timeStyle: "medium" })}</time>
               </>}
            </summary>
            {expanded.has(group.id) && <><div className="audit-chronology-columns" aria-hidden="true">
              <span>{labels.event}</span><span>{fields.states}</span><span>{labels.date}</span>
            </div>
            <ol className="audit-chronology-list">{group.events.slice(0, visibleCounts[group.id] ?? 20).map((event) => {
          const state = event.status === "rejected" ? "failed" : event.status ? auditStateFrom(event.status, null) : "unknown"
          return <li key={event.eventId} className="audit-chronology-event">
            <article data-state={state} aria-label={`${event.kind} · ${event.eventId}`}>
              <button type="button" className="audit-chronology-row" data-state={state} aria-haspopup="dialog"
                aria-label={executionEventPresentation(event, i18n.resolvedLanguage?.startsWith("es") ? "es" : "en", names).title}
                onClick={() => setSelection({ key, eventId: event.eventId })}>
              <ExecutionEventDescription event={event} names={names} />
              <span className="audit-chronology-state"><span className="audit-run-dot" aria-hidden="true" />{event.status === "timeout" ? labels.timeout : event.status === "rejected" ? labels.rejected : stateLabel(state)}</span>
               <time className="audit-chronology-date" dateTime={event.occurredAt}>{formatDateTime(event.occurredAt, { dateStyle: "short", timeStyle: "medium" })}</time>
              </button>
            </article>
          </li>
            })}</ol>
            {group.events.length > (visibleCounts[group.id] ?? 20) && <div className="audit-chronology-more">
              <Button variant="secondary" ariaLabel={labels.moreEvents} title={labels.moreEvents}
                onClick={() => setVisibleCounts((previous) => ({ ...previous, [group.id]: (previous[group.id] ?? 20) + 20 }))}>…</Button>
            </div>}
            </>}
          </details>
        </li>)}</ol>
      </div>
      {pagination}
    </> : <p className="label">{labels.empty}</p>}
    {selected && <ExecutionEventModal key={selected.eventId} event={selected} names={names}
      path={paths[orderedEvents.indexOf(selected)] || fields.notRecorded} onClose={() => setSelection(null)} />}
  </section>
}
