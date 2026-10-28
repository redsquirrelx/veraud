import { useId } from "react"
import { useTranslation } from "react-i18next"
import type { readAgentEvidence } from "./auditAgentEvidence.ts"
import type { AuditReportSectionResource } from "./useAuditReportSection.ts"
import { AuditEvidenceBrowser } from "./AuditEvidenceBrowser.tsx"

/** Shared by the standalone agent page and the embedded results tab. */
export function AuditEvidenceInventory({ result, projectId, auditId, repositoryName, auditedCommit, findings, pending, requestedEvidenceId, onEvidenceSelect }: {
  result: NonNullable<ReturnType<typeof readAgentEvidence>>, projectId: number, auditId: number,
  repositoryName?: string, auditedCommit?: string | null, findings: AuditReportSectionResource, pending: boolean
  requestedEvidenceId?: string, onEvidenceSelect?: (id: string) => void
}) {
  const { t } = useTranslation("auditEvidence")
  const titleId = useId()
  return <section aria-labelledby={titleId}>
    <h3 id={titleId}>{t("list")} ({result.evidence.length})</h3>
    <p>{t("allInvocations")}</p>
    {!result.found ? <p role="status">{t("notFound")}</p> : result.evidence.length === 0 && <p role="status">{t("empty")}</p>}
    <AuditEvidenceBrowser key={`${projectId}-${auditId}-${result.agentId}`} evidence={result.evidence} projectId={projectId} repositoryName={repositoryName}
      auditId={auditId} recordedOnly auditedCommit={auditedCommit} qualityResults={findings.state.status === "loaded" ? findings.state.data : undefined}
      findingsStatus={pending ? "unavailable" : findings.state.status} onRetryFindings={findings.retry}
      requestedEvidenceId={requestedEvidenceId} onEvidenceSelect={onEvidenceSelect} />
  </section>
}
