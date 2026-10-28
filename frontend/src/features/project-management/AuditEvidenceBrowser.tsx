import { useId, useState } from "react"
import { useTranslation } from "react-i18next"
import { Badge, Button, Drawer } from "../../shared/ui-kit/index.ts"
import { evidenceDisplayKind, evidenceFilePath, findingsForEvidence, type AgentEvidence } from "./auditAgentEvidence.ts"
import { AuditEvidenceCode } from "./AuditEvidenceCode.tsx"
import { FindingDetails } from "./QualityAuditFindings.tsx"
import { ReportValue } from "./QualityAuditReport.tsx"

/** Selection over loaded evidence, with optional on-demand checkout file access. */
export function AuditEvidenceBrowser({ evidence, projectId = null, auditId, repositoryName, recordedOnly = false, auditedCommit,
  qualityResults, findingsStatus = "unavailable", onRetryFindings, requestedEvidenceId, onEvidenceSelect }: {
  evidence: AgentEvidence[], projectId?: number | null, auditId?: number, repositoryName?: string, recordedOnly?: boolean, auditedCommit?: string | null,
  qualityResults?: unknown, findingsStatus?: "loading" | "loaded" | "error" | "unavailable", onRetryFindings?: () => void
  requestedEvidenceId?: string, onEvidenceSelect?: (id: string) => void
}) {
  const { t } = useTranslation("auditEvidence")
  const id = useId()
  const [selection, setSelection] = useState<{ request?: string, id: string | null }>({ id: null })
  const selectedId = onEvidenceSelect ? requestedEvidenceId : selection.request === requestedEvidenceId ? selection.id : requestedEvidenceId
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set())
  const [findingId, setFindingId] = useState<string | null>(null)
  const selected = evidence.find((item) => item.id === selectedId)
    ?? evidence.find((item) => item.content !== null && item.content.trim().length > 0) ?? evidence[0]
  if (!selected) return null
  const linked = findingsForEvidence(qualityResults, selected.id)
  const finding = linked.find((item) => item.id === findingId)
  const findingsAvailable = qualityResults !== null && typeof qualityResults === "object"
    && Array.isArray((qualityResults as Record<string, unknown>).findings)
  const kind = evidenceDisplayKind(selected)
  const rangeLabel = (item: AgentEvidence) => item.startLine === null ? null
    : item.endLine !== null && item.endLine >= item.startLine ? t("lines", { start: item.startLine, end: item.endLine }) : t("line", { line: item.startLine })

  return <div className="audit-evidence-browser">
    <ul className="audit-evidence-list" aria-label={t("list")}>
      {evidence.map((item, index) => {
        const itemKind = evidenceDisplayKind(item)
        return <li key={`${item.id}-${index}`}><article className="audit-evidence-item">
          <button type="button" className="audit-evidence-choice" aria-pressed={selected.id === item.id}
            aria-controls={`${id}-viewer`} onClick={() => {
              if (onEvidenceSelect) onEvidenceSelect(item.id)
              else setSelection({ request: requestedEvidenceId, id: item.id })
            }}>
            <span className="audit-evidence-choice-heading"><strong title={item.id}>{item.id}</strong><Badge tone="neutral">{itemKind ? t(itemKind) : item.kind ?? t("notRecorded")}</Badge></span>
            <code>{item.source ?? t("notRecorded")}</code>
            {rangeLabel(item) && <span>{rangeLabel(item)}</span>}
          </button>
          <button type="button" className="audit-evidence-detail-toggle" aria-expanded={expanded.has(item.id)}
            aria-controls={`${id}-detail-${index}`} aria-label={`${t(expanded.has(item.id) ? "hideDetails" : "showDetails")} ${item.id}`}
            onClick={() => setExpanded((previous) => {
              const next = new Set(previous)
              if (next.has(item.id)) next.delete(item.id)
              else next.add(item.id)
              return next
            })}>{t(expanded.has(item.id) ? "hideDetails" : "showDetails")}</button>
          <dl id={`${id}-detail-${index}`} hidden={!expanded.has(item.id)}>
            {item.content === null && <div><dt>{t("contentUnavailable")}</dt><dd>{t("noContent")}</dd></div>}
            <div><dt>{t("execution")}</dt><dd><code>{item.invocationId ?? t("notRecorded")}</code></dd></div>
            {item.symbolIds.length > 0 && <div><dt>{t("symbol")}</dt><dd>{item.symbolIds.map((symbol) => <code key={symbol}>{symbol}</code>)}</dd></div>}
            {item.commit && <div><dt>{t("commit")}</dt><dd><code>{item.commit}</code></dd></div>}
            {item.toolCallId && <div><dt>{t("toolCall")}</dt><dd><code>{item.toolCallId}</code></dd></div>}
          </dl>
        </article></li>
      })}
    </ul>
    <section className="audit-evidence-code" id={`${id}-viewer`} aria-label={t("viewerTitle")}>
      <header><h4>{t("viewerTitle")}</h4><Badge tone="neutral">{kind ? t(kind) : selected.kind ?? t("notRecorded")}</Badge></header>
      <code>{selected.source ?? t("notRecorded")}</code>
      {rangeLabel(selected) && <p>{rangeLabel(selected)}</p>}
      <AuditEvidenceCode key={`${projectId}-${evidenceFilePath(selected.source, repositoryName)}`} evidence={selected} projectId={projectId}
        auditId={auditId} repositoryName={repositoryName} recordedOnly={recordedOnly} auditedCommit={auditedCommit} />
      {recordedOnly && <section aria-label={t("linkedFindings")}>
        <h4>{t("linkedFindings")}</h4>
        {findingsStatus === "loading" && <p role="status">{t("loadingFindings")}</p>}
        {findingsStatus === "error" && <div role="alert"><p>{t("findingsFailed")}</p>
          {onRetryFindings && <Button variant="secondary" onClick={onRetryFindings}>{t("retry")}</Button>}</div>}
        {(findingsStatus === "unavailable" || (findingsStatus === "loaded" && !findingsAvailable)) && <p>{t("findingsUnavailable")}</p>}
        {findingsStatus === "loaded" && findingsAvailable && (linked.length === 0 ? <p>{t("noLinkedFindings")}</p>
          : <ul>{linked.map((item) => <li key={String(item.id)}><Button variant="secondary" aria-haspopup="dialog"
            onClick={() => setFindingId(String(item.id))}>{String(item.id)}{typeof item.title === "string" ? ` — ${item.title}` : ""}</Button></li>)}</ul>)}
      </section>}
    </section>
    <Drawer open={finding !== undefined} title={typeof finding?.title === "string" ? finding.title : findingId ?? t("linkedFindings")} onClose={() => setFindingId(null)}>
      {finding && <FindingDetails key={String(finding.id)} finding={finding} renderDetails={(item) => <ReportValue value={item} />}
        onEvidenceNavigate={() => setFindingId(null)} />}
    </Drawer>
  </div>
}
