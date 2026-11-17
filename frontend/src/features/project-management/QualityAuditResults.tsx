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
import { AuditChronologyTab } from "./AuditChronologyTab.tsx"
import { AuditValidationHistoryPreview } from "./AuditValidationHistory.tsx"
import { useAuditChronologyLabels } from "./auditChronologyLabels.ts"
import { executionStatusLabelKeys, statusLabelKey, isQualityAuditActive } from "./projectStatus.ts"
import { useAuditStateLabel } from "../../shared/audit-monitor/monitorLabels.ts"
import { useAuditCancellationRevision } from "../../shared/agent-monitor/useAgentExecutions.ts"
import { QualityAuditFindingsPanel, QualityAuditReport } from "./QualityAuditReport.tsx"
import { useAuditReportSection } from "./useAuditReportSection.ts"
import { downloadQualityAuditFindings, downloadQualityAuditReport, downloadVerificationSuite, findingsFromQualityResults, getQualityAudit, getQualityAuditReportSection, getVerificationSuite, requestVerificationSuite, startFindingResolution, type QualityAuditSummary, type SuiteAction, type VerificationSuitePage } from "./qualityAuditApi.ts"
import "./QualityAudits.css"
import { publicErrorText } from "../../infrastructure/http-client/publicErrors.ts"
import { VerificationWorkspace } from "./VerificationWorkspace.tsx"

type ResultsError = { key: ParseKeys<"projects"> } | { detail: string }
const evaluationLabels: Record<string, ParseKeys<"projects">> = {
  completed: "qualityAudits.evaluation.completed", partial: "qualityAudits.evaluation.partial", failed: "qualityAudits.evaluation.failed",
}

export function QualityAuditResults({ projectId, auditId, projectName, repositoryName }: { projectId: number, auditId: number, projectName: string, repositoryName?: string }) {
  const { t, i18n } = useTranslation("projects")
  const { t: tCommon } = useTranslation("common")
  const { t: tEvidence } = useTranslation("auditEvidence")
  const incidentLabels = useAuditIncidentLabels()
  const chronologyLabels = useAuditChronologyLabels()
  const revalidationLabels = i18n.resolvedLanguage?.startsWith("es")
    ? { tab: "Revalidación de hallazgos", start: "Iniciar revalidación", starting: "Iniciando…", started: "Revalidación iniciada (ejecución {{id}}).", error: "No se pudo iniciar la revalidación." }
    : { tab: "Findings revalidation", start: "Start finding revalidation", starting: "Starting…", started: "Finding revalidation started (execution {{id}}).", error: "Could not start the finding revalidation." }
  const [audit, setAudit] = useState<QualityAuditSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ResultsError | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [downloading, setDownloading] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)
  const [revalidationStarting, setRevalidationStarting] = useState(false)
  const [revalidationError, setRevalidationError] = useState<string | null>(null)
  const [revalidationStarted, setRevalidationStarted] = useState<number | null>(null)
  const [suiteBusy, setSuiteBusy] = useState(false)
  const [suiteReconnecting, setSuiteReconnecting] = useState(false)
  const [suiteAction, setSuiteAction] = useState<SuiteAction | null>(null)
  const [suiteError, setSuiteError] = useState<string | null>(null)
  const [suiteSummary, setSuiteSummary] = useState<VerificationSuitePage | null>(null)
  const [suiteDefinition, setSuiteDefinition] = useState<VerificationSuitePage | null>(null)
  const [suiteExecution, setSuiteExecution] = useState<VerificationSuitePage | null>(null)
  const [suiteArtifactKey, setSuiteArtifactKey] = useState<string | null>(null)
  const suiteAvailable = suiteArtifactKey === `${projectId}:${auditId}`
  const [suiteScope, setSuiteScope] = useState<string>("all")
  const [suiteTarget, setSuiteTarget] = useState<{ key: string, commit: string } | null>(null)
  const suiteTargetCommit = suiteTarget?.key === `${projectId}:${auditId}` ? suiteTarget.commit : audit?.commitHash ?? ""
  const [suiteDownloading, setSuiteDownloading] = useState(false)
  const [search, setSearch] = useSearchParams()
  const requestedTab = search.get("tab")
  const activeTab = requestedTab === "revalidation" || requestedTab === "verification" || requestedTab === "findings" || requestedTab === "evidence" || requestedTab === "incidents" || requestedTab === "chronology" ? requestedTab : "general"
  const requestedEvidenceId = search.get("evidence") || undefined
  const [evidenceVisited, setEvidenceVisited] = useState(false)
  const [qualityResultsOpen, setQualityResultsOpen] = useState(false)
  const tabsId = useId()
  const tabs = [
    { id: "general", label: t("qualityAudits.results.generalTab") },
    { id: "revalidation", label: revalidationLabels.tab },
    { id: "verification", label: t("qualityAudits.results.verificationTab") },
    { id: "findings", label: t("qualityAudits.results.findingsTab") },
    { id: "evidence", label: tEvidence("tab") },
    { id: "incidents", label: incidentLabels.tab },
    { id: "chronology", label: chronologyLabels.tab },
  ]
  const pending = audit !== null && isQualityAuditActive(audit)
  const cancellationRevision = useAuditCancellationRevision(projectId, auditId)
  const qualityResults = useAuditReportSection(projectId, auditId, "quality_results",
    !loading && !pending && audit?.reportAvailable === true && (activeTab === "findings" || activeTab === "evidence" || qualityResultsOpen), attempt)

  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    let live = false
    async function load() {
      try {
        const row = await getQualityAudit(projectId, auditId, controller.signal)
        if (controller.signal.aborted) return
        setAudit(row)
        setError(null)
        live = isQualityAuditActive(row)
        if (live) timer = setTimeout(() => void load(), 3000)
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof ApiError && cause.status === 404
          ? { key: "qualityAudits.results.notFound" } : cause instanceof ApiError && cause.messageSource !== "client"
             ? { detail: cause.message } : { key: "qualityAudits.results.loadFailed" })
        if (!controller.signal.aborted && live) timer = setTimeout(() => void load(), 5000)
      } finally { if (!controller.signal.aborted) setLoading(false) }
    }
    void load()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [projectId, auditId, attempt, cancellationRevision])

  // Recover an existing operation/result on navigation without dispatching another POST.
  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    async function loadSuite() {
      try {
        const states = await Promise.all([
          getVerificationSuite(projectId, auditId, "execute", suiteScope === "all" ? undefined : suiteScope),
          getVerificationSuite(projectId, auditId, "create", undefined),
        ])
        if (cancelled) return
        const pending = states.find((state) => state.status === "building" || state.status === "recovering")
        if (pending) {
          setSuiteBusy(true)
          setSuiteReconnecting(pending.status === "recovering")
          timer = setTimeout(() => void loadSuite(), 4000)
          return
        }
        setSuiteBusy(false)
        setSuiteReconnecting(false)
        const ready = states.find((state) => state.status === "ready")
        if (ready?.status === "ready") {
          setSuiteSummary(ready)
          if (ready.action === "execute") setSuiteExecution(ready)
          else setSuiteDefinition(ready)
          setSuiteArtifactKey(ready.zip_path ? `${projectId}:${auditId}` : null)
        }
      } catch {
        if (!cancelled) timer = setTimeout(() => void loadSuite(), 4000)
      }
    }
    void loadSuite()
    return () => { cancelled = true; clearTimeout(timer) }
  }, [projectId, auditId, suiteScope])

  async function download() {
    setDownloading(true)
    try { await downloadQualityAuditReport(projectId, auditId) }
    catch { setError({ key: "qualityAudits.errors.download" }) }
    finally { setDownloading(false) }
  }

  async function exportFindings() {
    if (!audit) return
    setExporting(true)
    setExportError(null)
    try {
      const findings = qualityResults.state.status === "loaded"
        ? findingsFromQualityResults(qualityResults.state.data)
        : findingsFromQualityResults((await getQualityAuditReportSection(projectId, auditId, "quality_results")).data)
      await downloadQualityAuditFindings(auditId, audit, findings)
    } catch { setExportError(t("qualityAudits.errors.export")) }
    finally { setExporting(false) }
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

  async function startRevalidation() {
    if (!audit?.commitHash) return
    setRevalidationStarting(true)
    setRevalidationError(null)
    setRevalidationStarted(null)
    try {
      const execution = await startFindingResolution(projectId, auditId, audit.commitHash)
      setRevalidationStarted(execution.id)
    } catch (cause) {
      setRevalidationError(cause instanceof Error ? cause.message : revalidationLabels.error)
    } finally {
      setRevalidationStarting(false)
    }
  }

  async function runSuiteAction(action: SuiteAction) {
    if (!audit?.commitHash) return
    setSuiteBusy(true)
    setSuiteAction(action)
    setSuiteError(null)
    setSuiteSummary(null)
    setSuiteReconnecting(false)
    try {
      const kicked = await requestVerificationSuite(projectId, auditId, {
        action, ...(action === "execute" ? { targetCommit: suiteTargetCommit, group: suiteScope === "all" ? undefined : suiteScope } : {}),
      })
      if (kicked.status === "ready") {
        setSuiteSummary(kicked)
        if (action === "execute") setSuiteExecution(kicked)
        else { setSuiteDefinition(kicked); setSuiteExecution(null) }
        setSuiteArtifactKey(kicked.zip_path ? `${projectId}:${auditId}` : null)
        return
      }
      if (kicked.status === "failed") { setSuiteError(kicked.message ?? t("verificationWorkspace.actionError")); return }
      let failures = 0
      // The backend owns the build; this polls until the artifact is ready, failed or the attempt budget runs out (~10 min).
      for (let attempt = 0; attempt < 150; attempt += 1) {
        await new Promise((resolve) => { setTimeout(resolve, 4000) })
        try {
          const state = await getVerificationSuite(projectId, auditId, action, action === "execute" && suiteScope !== "all" ? suiteScope : undefined)
          failures = 0
          setSuiteReconnecting(state.status === "recovering")
          if (state.status === "ready") {
            setSuiteSummary(state)
            if (action === "execute") setSuiteExecution(state)
            else { setSuiteDefinition(state); setSuiteExecution(null) }
            setSuiteArtifactKey(state.zip_path ? `${projectId}:${auditId}` : null)
            return
          }
          if (state.status === "failed") { setSuiteError(state.message ?? t("verificationWorkspace.actionError")); return }
        } catch {
          failures += 1
          if (failures >= 1) setSuiteReconnecting(true)
        }
      }
      setSuiteError(t("verificationWorkspace.actionError"))
    } catch (cause) {
      setSuiteError(cause instanceof Error ? cause.message : t("verificationWorkspace.actionError"))
    } finally {
      setSuiteBusy(false)
      setSuiteReconnecting(false)
      setSuiteAction(null)
    }
  }

  async function downloadSuite() {
    if (!suiteAvailable) return
    setSuiteDownloading(true)
    setSuiteError(null)
    try { await downloadVerificationSuite(projectId, auditId) }
    catch (cause) { setSuiteError(cause instanceof Error ? cause.message : t("verificationWorkspace.actionError")) }
    finally { setSuiteDownloading(false) }
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
        {!pending && (audit.reportAvailable ? <QualityAuditReport key={attempt} projectId={projectId} auditId={auditId} qualityResults={qualityResults} onQualityResultsOpenChange={setQualityResultsOpen} repositoryName={repositoryName ?? ""} /> : !error && <p className="label">{t("qualityAudits.results.noReport")}</p>)}
      </>}
    </>}
    </div>
    <div role="tabpanel" id={`${tabsId}-panel-revalidation`} aria-labelledby={`${tabsId}-tab-revalidation`} hidden={activeTab !== "revalidation"} tabIndex={0}>
      {activeTab === "revalidation" && <>
        <div className="quality-audit-history-actions">
          <Button variant="primary" disabled={!audit || pending || !audit.reportAvailable || !audit.commitHash || revalidationStarting}
            onClick={() => void startRevalidation()}>
            {revalidationStarting ? revalidationLabels.starting : revalidationLabels.start}
          </Button>
        </div>
        {revalidationStarted !== null && <p role="status">{revalidationLabels.started.replace("{{id}}", String(revalidationStarted))}</p>}
        {revalidationError && <p role="alert">{revalidationError}</p>}
        <AuditValidationHistoryPreview />
      </>}
    </div>
    <div role="tabpanel" id={`${tabsId}-panel-verification`} aria-labelledby={`${tabsId}-tab-verification`} hidden={activeTab !== "verification"} tabIndex={0}>
      {activeTab === "verification" && <VerificationWorkspace
        key={`${projectId}:${auditId}`}
        projectId={projectId} auditId={auditId} baseline={audit?.commitHash ?? null}
        branch={audit?.branch ?? null} targetCommit={suiteTargetCommit}
        onTargetChange={(commit) => setSuiteTarget({ key: `${projectId}:${auditId}`, commit })}
        suite={suiteDefinition ?? suiteSummary} execution={suiteExecution}
        suiteScope={suiteScope} onSuiteScopeChange={setSuiteScope}
        available={suiteAvailable} enabled={!!audit && !pending && audit.reportAvailable && !!audit.commitHash}
        busy={suiteBusy} action={suiteAction} downloading={suiteDownloading}
        error={suiteError} reconnecting={suiteReconnecting}
        create={() => void runSuiteAction("create")} execute={() => void runSuiteAction("execute")}
        download={() => void downloadSuite()} />}
    </div>
    <div role="tabpanel" id={`${tabsId}-panel-findings`} aria-labelledby={`${tabsId}-tab-findings`} hidden={activeTab !== "findings"} tabIndex={0}>
      {activeTab === "findings" && (loading ? <Spinner /> : pending || (error !== null && audit === null) ? null : audit?.reportAvailable
        ? <>
            <div className="quality-audit-history-actions">
              <Button variant="secondary" disabled={exporting} onClick={() => void exportFindings()}>
                {exporting ? t("qualityAudits.exporting") : t("qualityAudits.exportJson")}
              </Button>
            </div>
            {exportError && <p role="alert">{exportError}</p>}
            <QualityAuditFindingsPanel resource={qualityResults} projectId={projectId} repositoryName={repositoryName ?? ""} />
          </>
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
    <div role="tabpanel" id={`${tabsId}-panel-chronology`} aria-labelledby={`${tabsId}-tab-chronology`} hidden={activeTab !== "chronology"} tabIndex={0}>
      {loading && activeTab === "chronology" && <Spinner />}
      {audit && <AuditChronologyTab key={`${projectId}-${auditId}`} audit={audit} revision={attempt}
        active={!loading && activeTab === "chronology"} />}
    </div>
    {!loading && <div><Button variant="secondary" onClick={retry}>{tCommon("ui.refresh")}</Button></div>}
  </Card></AuditEvidenceNavigation.Provider>
}
