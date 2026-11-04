import { useEffect, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { Button, Card, Spinner } from "../../shared/ui-kit/index.ts"
import { useAgentExecutions } from "../../shared/agent-monitor/useAgentExecutions.ts"
import { getQualityAudit, type QualityAuditSummary } from "./qualityAuditApi.ts"
import { useAuditReportSection } from "./useAuditReportSection.ts"
import { usePublishedAuditEvidence } from "./usePublishedAuditEvidence.ts"
import { readAgentEvidence } from "./auditAgentEvidence.ts"
import { AuditEvidenceInventory } from "./AuditEvidenceInventory.tsx"
import { AuditEvidenceNavigation } from "./auditEvidenceNavigation.ts"
import "./AuditAgentEvidence.css"

/** Read-only view over the existing metadata and report-section APIs. */
export function AuditAgentEvidence({ projectId, auditId, invocationId, projectName, repositoryName }: {
  projectId: number, auditId: number, invocationId: string, projectName: string, repositoryName?: string
}) {
  const { t } = useTranslation("auditEvidence")
  const [search] = useSearchParams()
  const executions = useAgentExecutions()
  const [metadata, setMetadata] = useState<{ key: string, audit: QualityAuditSummary | null, failed: boolean } | null>(null)
  const [attempt, setAttempt] = useState(0)
  const key = `${projectId}-${auditId}-${attempt}`
  const loaded = metadata?.key === key
  const audit = loaded ? metadata.audit : null
  const failed = loaded && metadata.failed
  const pending = audit !== null && ["Waiting", "Running"].includes(audit.executionStatus)
  const resource = useAuditReportSection(projectId, auditId, "annexes_and_traceability", audit?.reportAvailable === true && !pending, attempt)
  const findings = useAuditReportSection(projectId, auditId, "quality_results", audit?.reportAvailable === true && !pending, attempt)
  const published = usePublishedAuditEvidence(projectId, auditId, pending)
  const evidenceState = pending ? published.state : resource.state
  const live = executions.find((execution) => execution.id === auditId && execution.monitorContext?.project?.id === projectId)
    ?.invocations?.find((invocation) => invocation.invocation_id === invocationId)
  const result = evidenceState.status === "loaded" ? readAgentEvidence(evidenceState.data, invocationId, live?.agent_id) : null
  const agentType = result?.agentId ?? live?.agent_id ?? null
  const agentName = agentType && search.get("agent") === agentType ? search.get("name") || agentType : agentType
  const loading = !loaded || ((pending || audit?.reportAvailable === true) && evidenceState.status === "loading")
  const sectionFailed = pending ? published.failed : audit?.reportAvailable === true && resource.state.status === "error"

  useEffect(() => {
    if (!pending || published.value?.partial !== false) return
    const controller = new AbortController()
    getQualityAudit(projectId, auditId, controller.signal).then((row) => {
      if (!controller.signal.aborted) setMetadata({ key, audit: row, failed: false })
    }, () => {
      if (!controller.signal.aborted) setMetadata((previous) => previous?.key === key ? { ...previous, failed: true } : previous)
    })
    return () => controller.abort()
  }, [pending, published.value, projectId, auditId, key])

  useEffect(() => {
    const controller = new AbortController()
    getQualityAudit(projectId, auditId, controller.signal).then((row) => {
      if (!controller.signal.aborted) setMetadata({ key, audit: row, failed: false })
    }, () => {
      if (!controller.signal.aborted) setMetadata({ key, audit: null, failed: true })
    })
    return () => controller.abort()
  }, [projectId, auditId, key])

  return <AuditEvidenceNavigation.Provider value={`/projects/${projectId}/audits/${auditId}`}>
    <Card className="audit-evidence" layout="stack" gap="md" align="stretch">
    <header className="audit-evidence-header">
      <div><h2>{t("title")}</h2><p>{projectName}</p></div>
      <Link className="ui-button ui-button-secondary" to={`/projects/${projectId}/audits/${auditId}`}>{t("back")}</Link>
    </header>
    <dl className="audit-evidence-meta">
      <div><dt>{t("agent")}</dt><dd>{agentName ?? t("unknownAgent")}{agentType && agentType !== agentName && <code>{agentType}</code>}</dd></div>
      <div><dt>{t("selectedExecution")}</dt><dd><code>{invocationId}</code></dd></div>
      <div><dt>{t("audit")}</dt><dd><Link to={`/projects/${projectId}/audits/${auditId}`}>{t("auditName", { id: auditId })}</Link></dd></div>
      <div><dt>{t("branch")}</dt><dd><code>{audit?.branch ?? t("notRecorded")}</code></dd></div>
      <div><dt>{t("auditedCommit")}</dt><dd><code>{audit?.commitHash ?? t("notRecorded")}</code></dd></div>
    </dl>
    {loading && <div role="status"><Spinner /><span>{t("loading")}</span></div>}
    {(failed || sectionFailed) && <div role="alert"><p>{t("loadFailed")}</p>
      <Button variant="secondary" onClick={() => failed ? setAttempt((value) => value + 1) : pending ? published.retry() : resource.retry()}>{t("retry")}</Button>
    </div>}
    {pending && <p role="status">{t("pending")}</p>}
    {pending && published.value?.available === false && <p role="status">{t("notPublished")}</p>}
    {!loading && audit && !pending && !audit.reportAvailable && <p role="status">{t("noReport")}</p>}
    {!loading && !pending && audit?.reportAvailable && !sectionFailed && (!result || !result.inventoryAvailable) && <p role="status">{t("unavailable")}</p>}
    {!loading && (pending || audit?.reportAvailable) && result?.inventoryAvailable && <AuditEvidenceInventory result={result}
      projectId={projectId} auditId={auditId} repositoryName={repositoryName} auditedCommit={audit?.commitHash} findings={findings} pending={pending} />}
    {!loading && <div><Button variant="secondary" onClick={() => pending ? published.retry() : setAttempt((value) => value + 1)}>{t("refresh")}</Button></div>}
  </Card></AuditEvidenceNavigation.Provider>
}
