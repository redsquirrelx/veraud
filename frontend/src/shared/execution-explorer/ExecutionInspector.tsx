import { useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { Badge, ChevronLeftIcon, FolderIcon } from "../ui-kit/index.ts"
import { localStorage } from "../../infrastructure/storage/LocalStorage.ts"
import { formatDateTime } from "../i18n/format.ts"
import { useAuditStateLabel } from "../audit-monitor/monitorLabels.ts"
import { progressText, auditProgress, stateTone } from "../audit-monitor/auditStatus.ts"
import { auditExplorerTitle, findAgent, agentForest, flattenAgents } from "./explorerPresentation.ts"
import type { ExplorerRow } from "./useExplorerExecutions.ts"
import { ExecutionTree } from "./ExecutionTree.tsx"
import { ExecutionNodeDetail } from "./ExecutionNodeDetail.tsx"
import { AuditActions } from "../audit-monitor/AuditActions.tsx"

const STORAGE_KEY = "executionExplorer.splitWidthPx"
const SPLIT_MIN_WIDTH = 192
const SPLIT_MAX_WIDTH = 448
const SPLIT_DEFAULT_WIDTH = 304

function clampSplitWidth(value: unknown): number {
  const numeric = typeof value === "number" && Number.isFinite(value) ? value : SPLIT_DEFAULT_WIDTH
  return Math.min(SPLIT_MAX_WIDTH, Math.max(SPLIT_MIN_WIDTH, Math.round(numeric)))
}

interface ExecutionInspectorProps {
  row: ExplorerRow | null
  selectedAgentId: string | null
  collapsed: ReadonlySet<string>
  onToggleNode: (agentId: string) => void
  onSelectNode: (agentId: string) => void
  /** Mobile only: switch back to the list panel. */
  onBack: () => void
}

/** Right-hand panel: execution header, hierarchy (only when the receipts exist) and node
 *  detail, with reserved placeholders for events/traces/results. Read-only. */
export function ExecutionInspector({ row, selectedAgentId, collapsed, onToggleNode, onSelectNode, onBack }: ExecutionInspectorProps) {
  const { t } = useTranslation("executionExplorer")
  const { t: tProjects } = useTranslation("projects")
  const stateLabel = useAuditStateLabel()
  const [treeWidth, setTreeWidth] = useState<number>(() => clampSplitWidth(localStorage.get<number | null>(STORAGE_KEY, null)))
  const [dragging, setDragging] = useState(false)
  const dragOrigin = useRef<{ pointerId: number, startX: number, startWidth: number } | null>(null)

  useEffect(() => { localStorage.set(STORAGE_KEY, treeWidth) }, [treeWidth])

  if (!row) {
    return (
      <div className="execution-explorer-inspector-empty">
        <p className="label">{t("inspector.empty")}</p>
      </div>
    )
  }
  const audit = row.model
  const flattened = flattenAgents(audit)
  const hasTree = flattened.length > 1

  const selectedAgent = (selectedAgentId ? findAgent(audit, selectedAgentId) : null) ?? flattened[0] ?? null
  const repository = audit.project ? `${audit.project.repositoryOwner}/${audit.project.repositoryName}` : null
  const placeholderTabs = [
    { id: "events", label: t("inspector.placeholder.events") },
    { id: "traces", label: t("inspector.placeholder.traces") },
    { id: "results", label: t("inspector.placeholder.results") },
  ] as const

  const widthRatio = Math.round(((treeWidth - SPLIT_MIN_WIDTH) / (SPLIT_MAX_WIDTH - SPLIT_MIN_WIDTH)) * 100)

  return (
    <div className="execution-explorer-inspector">
      <header className="execution-explorer-inspector-header">
        <button type="button" className="execution-explorer-back" onClick={onBack}>
          <ChevronLeftIcon size={14} />
          <span>{t("inspector.backToList")}</span>
        </button>
        <div className="execution-explorer-inspector-heading">
          <h3>{auditExplorerTitle(audit, tProjects)}</h3>
          <span className="execution-explorer-inspector-badges">
            <Badge tone={stateTone(audit.state)}>{stateLabel(audit.state)}</Badge>
            {hasTree && <span className="label">{progressText(tProjects, auditProgress(audit))}</span>}
          </span>
          {row.kind === "audit" && <span className="execution-explorer-inspector-actions"><AuditActions audit={audit} /></span>}
        </div>
        <div className="execution-explorer-inspector-meta">
          {repository && audit.project && (
            <span className="execution-explorer-inspector-project">
              <FolderIcon size={12} />
              <span className="mono">{repository} · {audit.branch ?? "—"} @ {audit.commitHash?.slice(0, 7) ?? "—"}</span>
            </span>
          )}
          <span className="label">{t("inspector.createdAt")}: <time dateTime={audit.createdAt}>{formatDateTime(audit.createdAt)}</time></span>
          {audit.finishedAt && <span className="label">{t("inspector.finishedAt")}: <time dateTime={audit.finishedAt}>{formatDateTime(audit.finishedAt)}</time></span>}
        </div>
      </header>

      <div className="execution-explorer-inspector-body" data-layout={hasTree ? "tree" : "flat"}>
        {hasTree && (
          <>
            <div className="execution-explorer-tree-pane" style={{ width: `${treeWidth}px` }}>
              <h4 className="label execution-explorer-tree-title">{t("inspector.tree")}</h4>
              <ExecutionTree nodes={agentForest(audit)} selectedAgentId={selectedAgent ? String(selectedAgent.id) : null} collapsed={collapsed} onToggle={onToggleNode} onSelect={onSelectNode} />
            </div>
            <div
              className="execution-explorer-split"
              role="separator"
              tabIndex={0}
              aria-label={t("inspector.resizeTree")}
              aria-orientation="vertical"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={widthRatio}
              aria-valuetext={`${treeWidth}px`}
              data-dragging={dragging}
              onPointerDown={(event) => {
                if (event.button !== 0) return
                event.preventDefault()
                event.currentTarget.focus()
                event.currentTarget.setPointerCapture(event.pointerId)
                dragOrigin.current = { pointerId: event.pointerId, startX: event.clientX, startWidth: treeWidth }
                setDragging(true)
              }}
              onPointerMove={(event) => {
                const origin = dragOrigin.current
                if (!origin || !dragging) return
                setTreeWidth(clampSplitWidth(origin.startWidth + (event.clientX - origin.startX)))
              }}
              onPointerUp={(event) => { setDragging(false); dragOrigin.current = null; event.currentTarget.releasePointerCapture(event.pointerId) }}
              onPointerCancel={() => { setDragging(false); dragOrigin.current = null }}
              onLostPointerCapture={() => { setDragging(false); dragOrigin.current = null }}
              onKeyDown={(event) => {
                if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return
                event.preventDefault()
                if (event.key === "Home") return setTreeWidth(SPLIT_MIN_WIDTH)
                if (event.key === "End") return setTreeWidth(SPLIT_MAX_WIDTH)
                setTreeWidth(treeWidth + (event.key === "ArrowRight" ? 16 : -16))
              }}
            />
          </>
        )}
        {selectedAgent && <div className="execution-explorer-detail-pane"><ExecutionNodeDetail agent={selectedAgent} /></div>}
      </div>

      <div className="execution-explorer-placeholders" role="tablist" aria-label={t("inspector.placeholder.comingSoon")}>
        <span className="label execution-explorer-placeholders-note">{t("inspector.placeholder.comingSoon")}</span>
        {placeholderTabs.map((tab) => (
          <button key={tab.id} type="button" role="tab" className="execution-explorer-placeholder-tab" disabled aria-disabled="true" title={t("inspector.placeholder.comingSoon")}>
            {tab.label}
          </button>
        ))}
      </div>
    </div>
  )
}
