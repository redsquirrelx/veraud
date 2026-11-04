import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { listQualityAudits, type QualityAuditSummary } from "../../features/project-management/qualityAuditApi.ts"
import { useAgentExecutions } from "../../shared/agent-monitor/useAgentExecutions.ts"
import { formatNumber } from "../../shared/i18n/format.ts"
import { Button, Card, Spinner } from "../../shared/ui-kit/index.ts"
import { ProjectAuditsIcon } from "./projectSectionIcons.tsx"

export function ProjectAuditSummary({ projectId, commitHash }: { projectId: number, commitHash: string | null }) {
  const { t, i18n } = useTranslation("projects")
  const { t: tCommon } = useTranslation("common")
  const labels = i18n.resolvedLanguage?.startsWith("es")
    ? { version: "Versión seleccionada", total: "Total del proyecto" }
    : { version: "Selected version", total: "Project total" }
  const [audits, setAudits] = useState<QualityAuditSummary[] | null>(null)
  const [failed, setFailed] = useState(false)
  const [revision, setRevision] = useState(0)
  const executions = useAgentExecutions()
  // Ignore phase/token updates; refresh only when a project execution changes status.
  const executionRevision = executions.filter((item) => item.monitorContext?.project?.id === projectId)
    .map((item) => `${item.id}:${item.status}`).sort().join("|")

  useEffect(() => {
    let alive = true
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    async function load() {
      try {
        const rows = await listQualityAudits(projectId, controller.signal)
        if (!alive) return
        setAudits(rows)
        setFailed(false)
        if (rows.some((item) => ["Waiting", "Running"].includes(item.executionStatus))) {
          timer = setTimeout(() => void load(), 3000)
        }
      } catch {
        if (alive) {
          setAudits(null)
          setFailed(true)
        }
      }
    }
    void load()
    return () => { alive = false; controller.abort(); clearTimeout(timer) }
  }, [projectId, revision, executionRevision])

  const versionCount = audits !== null && commitHash !== null
    ? audits.filter((item) => item.commitHash === commitHash).length : null
  return (
    <Card className="project-body-card" layout="stack" gap="md" align="stretch">
      <section className="project-audit-summary" aria-label={t("detail.sections.audits")} aria-busy={audits === null && !failed}>
        <div className="project-audit-summary-heading">
          <h2><ProjectAuditsIcon /><Link to={`/projects/${projectId}/audits`}>{t("detail.sections.audits")} <span aria-hidden="true">→</span></Link></h2>
          {audits === null && !failed && <Spinner />}
        </div>
        <dl className="project-audit-summary-counts">
          <div>
            <dt>{labels.version}{commitHash !== null && <code title={commitHash}>{commitHash.slice(0, 7)}</code>}</dt>
            <dd>{versionCount === null ? "—" : formatNumber(versionCount)}</dd>
          </div>
          <div>
            <dt>{labels.total}</dt>
            <dd>{audits === null ? "—" : formatNumber(audits.length)}</dd>
          </div>
        </dl>
        {failed && <div className="project-audit-summary-error">
          <span role="alert">{t("qualityAudits.errors.load")}</span>
          <Button variant="secondary" onClick={() => { setFailed(false); setRevision((value) => value + 1) }}>{tCommon("ui.refresh")}</Button>
        </div>}
      </section>
    </Card>
  )
}
