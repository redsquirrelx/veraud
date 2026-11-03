import { useEffect, useRef, useState } from "react"
import { getAgentExecution, type AgentExecution } from "../../infrastructure/http-client/httpClient.ts"
import { Button, Pagination, Spinner } from "../../shared/ui-kit/index.ts"
import { ExecutionError } from "../../shared/audit-monitor/ExecutionError.tsx"
import { useMonitorLabels } from "../../shared/audit-monitor/monitorLabels.ts"
import { formatDateTime, formatNumber } from "../../shared/i18n/format.ts"
import { auditIncidents } from "./auditIncidents.ts"
import { useAuditIncidentLabels } from "./auditIncidentLabels.ts"
import type { QualityAuditSummary } from "./qualityAuditApi.ts"
import "./AuditIncidentsTab.css"

export function AuditIncidentsTab({ projectId, audit, active, revision }: {
  projectId: number, audit: QualityAuditSummary, active: boolean, revision: number,
}) {
  const labels = useAuditIncidentLabels()
  const fields = useMonitorLabels()
  const [attempt, setAttempt] = useState(0)
  const paginationIdentity = `${projectId}:${audit.id}`
  const [pageSelection, setPageSelection] = useState({ identity: paginationIdentity, page: 1 })
  const page = pageSelection.identity === paginationIdentity ? pageSelection.page : 1
  const setPage = (page: number) => setPageSelection({ identity: paginationIdentity, page })
  const [pageSize, setPageSize] = useState(5)
  const [resource, setResource] = useState<{ key: string, execution?: AgentExecution, error?: boolean } | null>(null)
  const cache = useRef<{ key: string, execution: AgentExecution } | null>(null)
  const key = `${projectId}:${audit.id}:${audit.evaluationId}:${audit.executionStatus}:${revision}:${attempt}`

  useEffect(() => {
    if (!active) return
    if (cache.current?.key === key) {
      setResource(cache.current)
      return
    }
    let ignore = false
    setResource({ key })
    getAgentExecution(audit.id, true).then((execution) => {
      if (execution.id !== audit.id || execution.evaluationId !== audit.evaluationId
        || execution.monitorContext?.project && execution.monitorContext.project.id !== projectId) {
        throw new Error("Unexpected audit execution identity")
      }
      if (ignore) return
      cache.current = { key, execution }
      setResource(cache.current)
    }).catch(() => { if (!ignore) setResource({ key, error: true }) })
    return () => { ignore = true }
  }, [active, key, audit.id, audit.evaluationId, projectId])

  if (!active) return null
  const execution = resource?.key === key ? resource.execution : undefined
  if (resource?.key === key && resource.error) return <div role="alert">
    <p>{labels.loadFailed}</p><Button variant="secondary" onClick={() => setAttempt((value) => value + 1)}>{labels.retry}</Button>
  </div>
  if (!execution) return <Spinner />
  const incidents = auditIncidents(execution, audit)
  const pageCount = Math.max(1, Math.ceil(incidents.length / pageSize))
  const currentPage = Math.min(page, pageCount)
  const visibleIncidents = incidents.slice((currentPage - 1) * pageSize, currentPage * pageSize)
  const pagination = <div className="quality-audit-pagination">
    <label>{labels.pageSize}
      <select value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1) }}>
        {[5, 10, 20].map((size) => <option key={size} value={size}>{formatNumber(size)}</option>)}
      </select>
    </label>
    <Pagination page={currentPage} pageCount={pageCount} onChange={setPage} label={labels.pagination} />
  </div>
  return <section className="audit-incidents" aria-label={labels.tab}>
    {["Waiting", "Running"].includes(execution.status) && <p role="status">{labels.pending}</p>}
    {incidents.length ? <>
      {pagination}
      <ol className="audit-incidents-list" start={(currentPage - 1) * pageSize + 1}>{visibleIncidents.map((incident) => <li key={incident.id}>
        <article className="audit-incident" aria-label={`${incident.agentId ?? fields.errorNotRecorded} · ${incident.occurredAt ?? fields.errorNotRecorded}`}>
          <div className="audit-incident-identity"><strong>{incident.agentId ?? fields.errorNotRecorded}</strong>
            <div className="audit-incident-meta"><span>{incident.occurredAt ? labels.date : labels.dateNotRecorded}</span>
              {incident.occurredAt && <time dateTime={incident.occurredAt}>{formatDateTime(incident.occurredAt)}</time>}
            </div>
          </div>
          <ExecutionError error={incident.message} detail={incident.detail}
            identity={`${incident.agentId ?? fields.errorNotRecorded}${incident.invocationId ? ` · #${incident.invocationId}` : ""}`} />
        </article>
      </li>)}</ol>
      {pagination}
    </> : <p className="label">{labels.empty}</p>}
  </section>
}
