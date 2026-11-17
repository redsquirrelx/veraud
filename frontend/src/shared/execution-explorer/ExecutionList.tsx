import { useTranslation } from "react-i18next"
import { useAuditStateLabel } from "../audit-monitor/monitorLabels.ts"
import { formatDateTime } from "../i18n/format.ts"
import { auditProgress, progressText } from "../audit-monitor/auditStatus.ts"
import { auditExplorerTitle, countAgents } from "./explorerPresentation.ts"
import type { ExplorerRow } from "./useExplorerExecutions.ts"

interface ExecutionListProps {
  rows: ExplorerRow[]
  selectedId: string | null
  onSelect: (id: string) => void
}

/** Compact, independently scrollable selection list of executions. Presentational:
 *  the parent owns filtering and selection state. */
export function ExecutionList({ rows, selectedId, onSelect }: ExecutionListProps) {
  const { t } = useTranslation("executionExplorer")
  const { t: tProjects } = useTranslation("projects")
  const stateLabel = useAuditStateLabel()

  if (rows.length === 0) {
    return <p className="execution-explorer-list-empty label">{t("list.empty")}</p>
  }

  return (
    <ul className="execution-explorer-items" aria-label={t("list.label")}>
      {rows.map(({ kind, model: audit }) => {
        const selected = String(audit.id) === selectedId
        const agents = countAgents(audit)
        const isAudit = kind === "audit"
        return (
          <li key={`${kind}-${audit.id}`}>
            <button
              type="button"
              className="execution-explorer-item"
              data-state={audit.state}
              data-selected={selected}
              aria-current={selected ? "true" : undefined}
              onClick={() => onSelect(String(audit.id))}
            >
              <span className="execution-explorer-item-title">{auditExplorerTitle(audit, tProjects)}</span>
              <span className="execution-explorer-item-meta">
                <span className="execution-explorer-state" data-state={audit.state}>
                  <span className="execution-explorer-state-dot" aria-hidden="true" />
                  {stateLabel(audit.state)}
                </span>
                {isAudit && <span className="label">{progressText(tProjects, auditProgress(audit))}</span>}
                {isAudit && agents > 1 && <span className="label">{t("list.agents", { count: agents })}</span>}
                <time className="mono" dateTime={audit.createdAt}>{formatDateTime(audit.createdAt, { dateStyle: "short", timeStyle: "short" })}</time>
              </span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}
