import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { Button, Spinner } from "../../shared/ui-kit/index.ts"
import { getQualityAudit, type QualityAuditSummary } from "./qualityAuditApi.ts"
import { executedEvidenceAgents } from "./auditEvidenceAgents.ts"
import { useAuditEvidenceAgents } from "./useAuditEvidenceAgents.ts"
import { useAuditReportSection, type AuditReportSectionResource } from "./useAuditReportSection.ts"
import { usePublishedAuditEvidence } from "./usePublishedAuditEvidence.ts"
import { auditEvidenceOwner, readAgentEvidence } from "./auditAgentEvidence.ts"
import { AuditEvidenceInventory } from "./AuditEvidenceInventory.tsx"
import "./AuditAgentEvidence.css"

export function AuditEvidenceTab({ projectId, auditId, repositoryName, audit, active, revision, findings, onAuditChange,
  requestedEvidenceId, onClearEvidenceTarget, onEvidenceSelect }: {
  projectId: number, auditId: number, repositoryName?: string, audit: QualityAuditSummary, active: boolean, revision: number,
  findings: AuditReportSectionResource, onAuditChange: (audit: QualityAuditSummary) => void
  requestedEvidenceId?: string, onClearEvidenceTarget: () => void, onEvidenceSelect: (id: string) => void
}) {
  const { t } = useTranslation("auditEvidence")
  const [selectedId, setSelectedId] = useState("")
  const pending = ["Waiting", "Running"].includes(audit.executionStatus)
  const agents = useAuditEvidenceAgents(projectId, auditId, active, pending, revision)
  const options = agents.history ? executedEvidenceAgents(agents.history) : []
  const manualAgent = options.find((agent) => agent.id === selectedId)
  const resource = useAuditReportSection(projectId, auditId, "annexes_and_traceability",
    active && (manualAgent !== undefined || Boolean(requestedEvidenceId)) && audit.reportAvailable && !pending, revision)
  const published = usePublishedAuditEvidence(projectId, auditId, active && pending && (manualAgent !== undefined || Boolean(requestedEvidenceId)))
  const evidenceState = pending ? published.state : resource.state
  const owner = requestedEvidenceId && evidenceState.status === "loaded" ? auditEvidenceOwner(evidenceState.data, requestedEvidenceId) : null
  const selected = requestedEvidenceId ? options.find((agent) => agent.id === owner) : manualAgent
  // Receipt identity is authoritative even if the selected invocation produced
  // no evidence; collect all other invocations of that same recorded agent.
  const candidate = selected && evidenceState.status === "loaded"
    ? readAgentEvidence(evidenceState.data, selected.invocationId, selected.id) : null
  const result = candidate?.agentId === selected?.id ? candidate : null
  const targetUnavailable = Boolean(requestedEvidenceId && agents.history && evidenceState.status === "loaded"
    && (!pending || published.value?.available !== false)
    && (!selected || !result?.evidence.some((item) => item.id === requestedEvidenceId)))
  const sectionFailed = pending ? published.failed : resource.state.status === "error"

  useEffect(() => {
    if (!active || !pending || published.value?.partial !== false) return
    const controller = new AbortController()
    getQualityAudit(projectId, auditId, controller.signal).then((row) => {
      if (!controller.signal.aborted) onAuditChange(row)
    }, () => {})
    return () => controller.abort()
  }, [active, pending, published.value, projectId, auditId, onAuditChange])

  return <div className="audit-evidence quality-audit-evidence-tab">
    <h3>{t("title")}</h3>
    <p>{t("executedAgentsNotice")}</p>
    {agents.failed && <div role="alert"><p>{t("agentsFailed")}</p><Button variant="secondary" onClick={agents.retry}>{t("retry")}</Button></div>}
    {!agents.history && !agents.failed && <div role="status"><Spinner /><span>{t("loadingAgents")}</span></div>}
    {agents.history && (options.length === 0 ? <p role="status">{t("noExecutedAgents")}</p> : <div className="quality-audit-findings-controls">
      <label>{t("selectAgent")}
        <select value={selected?.id ?? ""} onChange={(event) => { setSelectedId(event.currentTarget.value); onClearEvidenceTarget() }}>
          <option value="">{t("chooseAgent")}</option>
          {options.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}{agent.name !== agent.id ? ` (${agent.id})` : ""}</option>)}
        </select>
      </label>
    </div>)}
    {agents.history && options.length > 0 && !selected && !requestedEvidenceId && <p role="status">{t("chooseAgentNotice")}</p>}
    {requestedEvidenceId && agents.history && (pending || audit.reportAvailable) && evidenceState.status === "loading"
      && <div role="status"><Spinner /><span>{t("loading")}</span></div>}
    {requestedEvidenceId && sectionFailed && !selected && <div role="alert"><p>{t("loadFailed")}</p>
      <Button variant="secondary" onClick={pending ? published.retry : resource.retry}>{t("retry")}</Button></div>}
    {requestedEvidenceId && !pending && !audit.reportAvailable && <p role="status">{t("noReport")}</p>}
    {requestedEvidenceId && !selected && pending && <p role="status">{t("pending")}</p>}
    {requestedEvidenceId && !selected && pending && published.value?.available === false && <p role="status">{t("notPublished")}</p>}
    {targetUnavailable && requestedEvidenceId && <p role="alert">{t("targetUnavailable", { id: requestedEvidenceId })}</p>}
    {selected && <>
      <h4>{selected.name}</h4>
      {pending && <p role="status">{t("pending")}</p>}
      {pending && published.value?.available === false && <p role="status">{t("notPublished")}</p>}
      {!pending && !audit.reportAvailable ? <p role="status">{t("noReport")}</p> : <>
        {evidenceState.status === "loading" && <div role="status"><Spinner /><span>{t("loading")}</span></div>}
        {sectionFailed && <div role="alert"><p>{t("loadFailed")}</p><Button variant="secondary" onClick={pending ? published.retry : resource.retry}>{t("retry")}</Button></div>}
        {evidenceState.status === "loaded" && !pending && !result?.inventoryAvailable && <p role="status">{t("unavailable")}</p>}
        {result?.inventoryAvailable && !targetUnavailable && <AuditEvidenceInventory result={result} projectId={projectId} auditId={auditId} repositoryName={repositoryName}
          auditedCommit={audit.commitHash} findings={findings} pending={pending} requestedEvidenceId={requestedEvidenceId} onEvidenceSelect={onEvidenceSelect} />}
      </>}
    </>}
  </div>
}
