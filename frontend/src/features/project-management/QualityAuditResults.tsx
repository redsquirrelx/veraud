import { useEffect, useId, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { AuditEvidenceNavigation } from "./auditEvidenceNavigation.ts"
import type { ParseKeys } from "i18next"
import { useTranslation } from "react-i18next"
import { ApiError } from "../../infrastructure/http-client/httpClient.ts"
import { Badge, Button, Card, Spinner } from "../../shared/ui-kit/index.ts"
import { formatDateTime } from "../../shared/i18n/format.ts"
import { AuditConfigurationDetails } from "./AuditConfigurationDetails.tsx"
import { AuditEvidenceTab } from "./AuditEvidenceTab.tsx"
import { AuditIncidentsTab } from "./AuditIncidentsTab.tsx"
import { useAuditIncidentLabels } from "./auditIncidentLabels.ts"
import { executionStatusLabelKeys, statusLabelKey } from "./projectStatus.ts"
import { useAuditStateLabel } from "../../shared/audit-monitor/monitorLabels.ts"
import { useAuditCancellationRevision } from "../../shared/agent-monitor/useAgentExecutions.ts"
import { QualityAuditFindingsPanel, QualityAuditReport } from "./QualityAuditReport.tsx"
import { useAuditReportSection } from "./useAuditReportSection.ts"
import { downloadQualityAuditReport, getQualityAudit, type QualityAuditSummary } from "./qualityAuditApi.ts"
import "./QualityAudits.css"
import { publicErrorText } from "../../infrastructure/http-client/publicErrors.ts"

type ResultsError = { key: ParseKeys<"projects"> } | { detail: string }
const evaluationLabels: Record<string, ParseKeys<"projects">> = {
  completed: "qualityAudits.evaluation.completed", partial: "qualityAudits.evaluation.partial", failed: "qualityAudits.evaluation.failed",
}

export function QualityAuditResults({ projectId, auditId, projectName, repositoryName }: { projectId: number, auditId: number, projectName: string, repositoryName?: string }) {
  const { t } = useTranslation("projects")
  const { t: tCommon } = useTranslation("common")
  const { t: tEvidence } = useTranslation("auditEvidence")
  const incidentLabels = useAuditIncidentLabels()
  const [audit, setAudit] = useState<QualityAuditSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ResultsError | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [downloading, setDownloading] = useState(false)
  const [search, setSearch] = useSearchParams()
  const requestedTab = search.get("tab")
  const activeTab = requestedTab === "findings" || requestedTab === "evidence" || requestedTab === "incidents" ? requestedTab : "general"
  const requestedEvidenceId = search.get("evidence") || undefined
  const [evidenceVisited, setEvidenceVisited] = useState(false)
  const [qualityResultsOpen, setQualityResultsOpen] = useState(false)
  const tabsId = useId()
  const tabs = [
    { id: "general", label: t("qualityAudits.results.generalTab") },
    { id: "findings", label: t("qualityAudits.results.findingsTab") },
    { id: "evidence", label: tEvidence("tab") },
    { id: "incidents", label: incidentLabels.tab },
  ]
  const pending = audit !== null && ["Waiting", "Running"].includes(audit.executionStatus)
  const cancellationRevision = useAuditCancellationRevision(projectId, auditId)
  const qualityResults = useAuditReportSection(projectId, auditId, "quality_results",
    !loading && !pending && audit?.reportAvailable === true && (activeTab === "findings" || activeTab === "evidence" || qualityResultsOpen), attempt)

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
  }, [projectId, auditId, attempt, cancellationRevision])

  async function download() {
    setDownloading(true)
    try { await downloadQualityAuditReport(projectId, auditId) }
    catch { setError({ key: "qualityAudits.errors.download" }) }
    finally { setDownloading(false) }
  }

  function selectTab(id: string) {
    setSearch((previous) => { const next = new URLSearchParams(previous); next.set("tab", id); return next })
    if (id === "evidence" || activeTab === "evidence") setEvidenceVisited(true)
  }

  function retry() {
    setLoading(true)
    setError(null)
    setQualityResultsOpen(false)
    setAttempt((value) => value + 1)
  }

  const auditStateLabel = useAuditStateLabel()
  const stateLabel = !pending && audit?.auditStatus ? evaluationLabels[audit.auditStatus] : undefined
  const executionLabel = audit ? statusLabelKey(executionStatusLabelKeys, audit.executionStatus) : undefined
  const executionDate = audit ? audit.startedAt ?? audit.finishedAt ?? null : null
  return <AuditEvidenceNavigation.Provider value={`/projects/${projectId}/audits/${auditId}`}>
    <Card className="quality-audit-results" layout="stack" gap="md" align="stretch">
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
          {audit.auditStatus === "cancelling" || audit.auditStatus === "cancelled" ? auditStateLabel(audit.auditStatus)
            : stateLabel ? t(stateLabel) : executionLabel ? t(executionLabel) : audit.auditStatus ?? audit.executionStatus}
        </Badge>
      </dd></div>
      {audit.runId && <div><dt>{t("qualityAudits.runId.label")}</dt><dd><code>{audit.runId}</code></dd></div>}
    </dl>}
    </header>
    <div className="quality-audit-results-tabs" role="tablist" aria-label={t("qualityAudits.results.tabsLabel")}>
      {tabs.map((tab, index) => <button key={tab.id} id={`${tabsId}-tab-${tab.id}`} type="button" role="tab"
        aria-selected={activeTab === tab.id} aria-controls={`${tabsId}-panel-${tab.id}`} tabIndex={activeTab === tab.id ? 0 : -1}
        onClick={() => selectTab(tab.id)} onKeyDown={(event) => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return
          event.preventDefault()
          const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1
            : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length
          selectTab(tabs[next].id)
          event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("[role=tab]")[next]?.focus()
        }}>{tab.label}</button>)}
    </div>
    {pending && <p role="status">{t("qualityAudits.results.unfinished")}</p>}
    {!loading && error && <div role="alert">
      <p>{"detail" in error ? `${t("qualityAudits.results.loadFailed")} ${publicErrorText(error.detail)}` : t(error.key)}</p>
      <Button variant="secondary" onClick={retry}>{t("qualityAudits.results.retry")}</Button>
    </div>}
    <div role="tabpanel" id={`${tabsId}-panel-general`} aria-labelledby={`${tabsId}-tab-general`} hidden={activeTab !== "general"} tabIndex={0}>
    {loading ? <Spinner /> : <>
      {audit && <>
        <div className="quality-audit-history-actions">
          <AuditConfigurationDetails projectId={projectId} auditId={auditId} available={audit.configurationAvailable === true} />
          {!pending && audit.reportAvailable && <Button variant="secondary" disabled={downloading} onClick={() => void download()}>{downloading ? t("qualityAudits.downloading") : t("qualityAudits.downloadWord")}</Button>}
        </div>
        {audit.error && <p role="alert">{publicErrorText(audit.error)}</p>}
        {!pending && (audit.reportAvailable ? <QualityAuditReport key={attempt} projectId={projectId} auditId={auditId} qualityResults={qualityResults} onQualityResultsOpenChange={setQualityResultsOpen} /> : !error && <p className="label">{t("qualityAudits.results.noReport")}</p>)}
      </>}
    </>}
    </div>
    <div role="tabpanel" id={`${tabsId}-panel-findings`} aria-labelledby={`${tabsId}-tab-findings`} hidden={activeTab !== "findings"} tabIndex={0}>
      {activeTab === "findings" && (loading ? <Spinner /> : pending || (error !== null && audit === null) ? null : audit?.reportAvailable
        ? <QualityAuditFindingsPanel resource={qualityResults} />
        : <p className="label">{t("qualityAudits.results.noReport")}</p>)}
    </div>
    <div role="tabpanel" id={`${tabsId}-panel-evidence`} aria-labelledby={`${tabsId}-tab-evidence`} hidden={activeTab !== "evidence"} tabIndex={0}>
      {loading && activeTab === "evidence" && <Spinner />}
      {audit && (evidenceVisited || activeTab === "evidence") && <AuditEvidenceTab key={`${projectId}-${auditId}`}
        projectId={projectId} auditId={auditId} repositoryName={repositoryName} audit={audit} active={!loading && activeTab === "evidence"}
        revision={attempt} findings={qualityResults} onAuditChange={setAudit} requestedEvidenceId={requestedEvidenceId}
        onClearEvidenceTarget={() => setSearch((previous) => { const next = new URLSearchParams(previous); next.delete("evidence"); return next }, { replace: true })}
        onEvidenceSelect={(id) => setSearch((previous) => { const next = new URLSearchParams(previous); next.set("tab", "evidence"); next.set("evidence", id); return next })} />}
    </div>
    <div role="tabpanel" id={`${tabsId}-panel-incidents`} aria-labelledby={`${tabsId}-tab-incidents`} hidden={activeTab !== "incidents"} tabIndex={0}>
      {loading && activeTab === "incidents" && <Spinner />}
      {audit && <AuditIncidentsTab key={`${projectId}-${auditId}`} projectId={projectId} audit={audit}
        active={!loading && activeTab === "incidents"} revision={attempt} />}
    </div>
    {!loading && <div><Button variant="secondary" onClick={retry}>{tCommon("ui.refresh")}</Button></div>}
  </Card></AuditEvidenceNavigation.Provider>
}
