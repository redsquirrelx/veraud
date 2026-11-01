import { auditAgentName } from "../../shared/audit-monitor/auditStatus.ts"
import { useAuditStateLabel, useMonitorLabels } from "../../shared/audit-monitor/monitorLabels.ts"
import { formatDateTime } from "../../shared/i18n/format.ts"
import { demoChronologyPipelines } from "./auditChronologyDemo.ts"
import { chronologyExecutions } from "./auditChronology.ts"
import { useAuditChronologyLabels } from "./auditChronologyLabels.ts"
import "./AuditChronologyTab.css"
import "../../shared/audit-monitor/AuditStatusView.css"

/** Isolated preview of the monitor's invocations; no audit requests or actions. */
export function AuditChronologyTab({ active }: { active: boolean }) {
  const labels = useAuditChronologyLabels()
  const fields = useMonitorLabels()
  const stateLabel = useAuditStateLabel()
  if (!active) return null
  const rows = chronologyExecutions(demoChronologyPipelines)
  const date = (value: string | null) => value
    ? <time dateTime={value}>{formatDateTime(value, { dateStyle: "short", timeStyle: "medium" })}</time>
    : fields.notRecorded
  return <section className="audit-chronology" aria-label={labels.tab}>
    <p className="audit-chronology-demo" role="note">{labels.demoNote}</p>
    <p className="audit-chronology-order">{labels.order}</p>
    {rows.length ? <div className="audit-chronology-scroll" role="region" aria-label={labels.tab} tabIndex={0}>
      <div className="audit-chronology-columns" aria-hidden="true">
        <span>{labels.agent}</span><span>{fields.states}</span><span>{fields.started}</span><span>{fields.finished}</span>
      </div>
      <ol className="audit-chronology-list">{rows.map(({ agent, pipelineId, path }) => {
        const identity = `${auditAgentName(agent)} · #${agent.id}`
        const route = path.map(auditAgentName).join(" → ")
        return <li key={`${pipelineId}:${agent.id}`} className="audit-chronology-event">
          <article className="audit-chronology-row" data-state={agent.state} aria-label={identity}>
              <span className="audit-chronology-identity" title={`${route} · #${agent.id}`}>
                <span className="mono audit-chronology-path">{route}</span>
              </span>
              <span className="audit-chronology-state"><span className="audit-run-dot" aria-hidden="true" />{stateLabel(agent.state)}</span>
              <span className="audit-chronology-date" title={fields.started}>{date(agent.startedAt)}</span>
              <span className="audit-chronology-date" title={fields.finished}>{date(agent.finishedAt)}</span>
          </article>
        </li>
      })}</ol>
    </div> : <p className="label">{labels.empty}</p>}
  </section>
}
