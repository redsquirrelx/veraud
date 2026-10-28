import { useEffect, useId, useState } from "react"
import { Link } from "react-router-dom"
import type { ParseKeys } from "i18next"
import { useTranslation } from "react-i18next"
import { ApiError } from "../../infrastructure/http-client/httpClient.ts"
import { Badge, Button, Card, Spinner } from "../../shared/ui-kit/index.ts"
import { formatDateTime } from "../../shared/i18n/format.ts"
import { AuditConfigurationDetails } from "./AuditConfigurationDetails.tsx"
import { executionStatusLabelKeys, statusLabelKey } from "./projectStatus.ts"
import { QualityAuditFindingsPanel, QualityAuditReport } from "./QualityAuditReport.tsx"
import { useAuditReportSection } from "./useAuditReportSection.ts"
import { downloadQualityAuditReport, getQualityAudit, type QualityAuditSummary } from "./qualityAuditApi.ts"
import "./QualityAudits.css"

type ResultsError = { key: ParseKeys<"projects"> } | { detail: string }
const evaluationLabels: Record<string, ParseKeys<"projects">> = {
  completed: "qualityAudits.evaluation.completed", partial: "qualityAudits.evaluation.partial", failed: "qualityAudits.evaluation.failed",
}

export function QualityAuditResults({ projectId, auditId, projectName }: { projectId: number, auditId: number, projectName: string }) {
  const { t } = useTranslation("projects")
  const { t: tCommon } = useTranslation("common")
  const [audit, setAudit] = useState<QualityAuditSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ResultsError | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [downloading, setDownloading] = useState(false)
  const [activeTab, setActiveTab] = useState("general")
  const [qualityResultsOpen, setQualityResultsOpen] = useState(false)
  const tabsId = useId()
  const tabs = [
    { id: "general", label: t("qualityAudits.results.generalTab") },
    { id: "findings", label: t("qualityAudits.results.findingsTab") },
  ]
  const pending = audit !== null && ["Waiting", "Running"].includes(audit.executionStatus)
  const qualityResults = useAuditReportSection(projectId, auditId, "quality_results",
    !loading && !pending && audit?.reportAvailable === true && (activeTab === "findings" || qualityResultsOpen), attempt)

  useEffect(() => {
    const controller = new AbortController()
    async function load() {
      try {
        const row = await getQualityAudit(projectId, auditId, controller.signal)
        if (controller.signal.aborted) return
        setAudit(row)
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof ApiError && cause.status === 404
          ? { key: "qualityAudits.results.notFound" } : cause instanceof ApiError && cause.messageSource !== "client"
            ? { detail: cause.message } : { key: "qualityAudits.results.loadFailed" })
      } finally { if (!controller.signal.aborted) setLoading(false) }
    }
    void load()
    return () => controller.abort()
  }, [projectId, auditId, attempt])

  async function download() {
    setDownloading(true)
    try { await downloadQualityAuditReport(projectId, auditId) }
    catch { setError({ key: "qualityAudits.errors.download" }) }
    finally { setDownloading(false) }
  }

  function retry() {
    setLoading(true)
    setError(null)
    setQualityResultsOpen(false)
    setAttempt((value) => value + 1)
  }

  const stateLabel = !pending && audit?.auditStatus ? evaluationLabels[audit.auditStatus] : undefined
  const executionLabel = audit ? statusLabelKey(executionStatusLabelKeys, audit.executionStatus) : undefined
  const executionDate = audit ? audit.startedAt ?? audit.finishedAt ?? null : null
  return <Card className="quality-audit-results" layout="stack" gap="md" align="stretch">
    <header className="quality-audit-results-header" aria-label={t("qualityAudits.results.headerLabel")}>
    <div className="quality-audit-heading">
      <div className="quality-audit-results-title"><h2>{t("qualityAudits.results.title", { id: auditId })}</h2><p>{projectName}</p></div>
      <Link className="ui-button ui-button-secondary" to={`/projects/${projectId}/audits`}>{t("qualityAudits.results.back")}</Link>
    </div>
    {audit && <dl className="quality-audit-results-meta">
      <div><dt>{t("qualityAudits.configurationHistory.branch")}</dt><dd>{audit.branch ?? "—"}</dd></div>
      <div><dt>{t("qualityAudits.configurationHistory.commit")}</dt><dd><code>{audit.commitHash ?? "—"}</code></dd></div>
      <div><dt>{t("qualityAudits.results.executionDate")}</dt><dd>{executionDate && !Number.isNaN(new Date(executionDate).getTime())
        ? <time dateTime={executionDate}>{formatDateTime(executionDate)}</time> : t("qualityAudits.report.notRecorded")}</dd></div>
      <div><dt>{t(pending ? "qualityAudits.report.fields.status" : "qualityAudits.results.finalStatus")}</dt><dd>
        <Badge tone={pending ? "info" : audit.auditStatus === "completed" ? "success" : audit.auditStatus === "partial" || audit.auditStatus === "failed" || audit.executionStatus === "Failed" ? "warning" : "info"}>
          {stateLabel ? t(stateLabel) : executionLabel ? t(executionLabel) : audit.auditStatus ?? audit.executionStatus}
        </Badge>
      </dd></div>
      {audit.runId && <div><dt>{t("qualityAudits.runId.label")}</dt><dd><code>{audit.runId}</code></dd></div>}
    </dl>}
    </header>
    <div className="quality-audit-results-tabs" role="tablist" aria-label={t("qualityAudits.results.tabsLabel")}>
      {tabs.map((tab, index) => <button key={tab.id} id={`${tabsId}-tab-${tab.id}`} type="button" role="tab"
        aria-selected={activeTab === tab.id} aria-controls={`${tabsId}-panel-${tab.id}`} tabIndex={activeTab === tab.id ? 0 : -1}
        onClick={() => setActiveTab(tab.id)} onKeyDown={(event) => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return
          event.preventDefault()
          const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1
            : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length
          setActiveTab(tabs[next].id)
          event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("[role=tab]")[next]?.focus()
        }}>{tab.label}</button>)}
    </div>
    {pending && <p role="status">{t("qualityAudits.results.unfinished")}</p>}
    {!loading && error && <div role="alert">
      <p>{"detail" in error ? `${t("qualityAudits.results.loadFailed")} ${error.detail}` : t(error.key)}</p>
      <Button variant="secondary" onClick={retry}>{t("qualityAudits.results.retry")}</Button>
    </div>}
    <div role="tabpanel" id={`${tabsId}-panel-general`} aria-labelledby={`${tabsId}-tab-general`} hidden={activeTab !== "general"} tabIndex={0}>
    {loading ? <Spinner /> : <>
      {audit && <>
        <div className="quality-audit-history-actions">
          <AuditConfigurationDetails projectId={projectId} auditId={auditId} available={audit.configurationAvailable === true} />
          {!pending && audit.reportAvailable && <Button variant="secondary" disabled={downloading} onClick={() => void download()}>{downloading ? t("qualityAudits.downloading") : t("qualityAudits.downloadWord")}</Button>}
        </div>
        {audit.error && <p role="alert">{audit.error}</p>}
        {!pending && (audit.reportAvailable ? <QualityAuditReport key={attempt} projectId={projectId} auditId={auditId} qualityResults={qualityResults} onQualityResultsOpenChange={setQualityResultsOpen} /> : !error && <p className="label">{t("qualityAudits.results.noReport")}</p>)}
      </>}
    </>}
    </div>
    <div role="tabpanel" id={`${tabsId}-panel-findings`} aria-labelledby={`${tabsId}-tab-findings`} hidden={activeTab !== "findings"} tabIndex={0}>
      {activeTab === "findings" && (loading ? <Spinner /> : pending || (error !== null && audit === null) ? null : audit?.reportAvailable
        ? <QualityAuditFindingsPanel resource={qualityResults} />
        : <p className="label">{t("qualityAudits.results.noReport")}</p>)}
    </div>
    {!loading && <div><Button variant="secondary" onClick={retry}>{tCommon("ui.refresh")}</Button></div>}
  </Card>
}
