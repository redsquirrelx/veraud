import { useEffect, useId, useMemo, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { useTranslation } from "react-i18next"
import { ActivityIcon, FilterTabs, XIcon, IconButton } from "../ui-kit/index.ts"
import { useExplorerExecutions, type ExplorerRowKind } from "./useExplorerExecutions.ts"
import { useAuditStateLabel } from "../audit-monitor/monitorLabels.ts"
import { pipelineLabelKey, type AuditRunState } from "../audit-monitor/auditStatus.ts"
import { auditExplorerTitle } from "./explorerPresentation.ts"
import { ExecutionList } from "./ExecutionList.tsx"
import { ExecutionInspector } from "./ExecutionInspector.tsx"
import { useFocusTrap } from "./useFocusTrap.ts"
import "./ExecutionExplorerModal.css"

export interface ExecutionExplorerModalProps {
  open: boolean
  /** Optional audit id (execution id) to preselect on open. */
  initialExecutionId?: string | null
  onClose: () => void
}

const TYPE_FILTERS: Array<"all" | ExplorerRowKind> = ["all", "audit", "agent"]
const STATUS_FILTERS: Array<"all" | AuditRunState> = ["all", "running", "waiting", "cancelling", "completed", "partial", "failed", "cancelled", "unknown"]

/** Global Execution Explorer. Currently shows quality audits and architecture-context
 *  executions, read live and read-only from the shared execution feed — no new
 *  endpoints or polling. Mounted once by the provider. */
export function ExecutionExplorerModal({ open, initialExecutionId = null, onClose }: ExecutionExplorerModalProps) {
  const { t } = useTranslation("executionExplorer")
  const { t: tProjects } = useTranslation("projects")
  const { t: tCommon } = useTranslation("common")
  const stateLabel = useAuditStateLabel()
  const titleId = useId()
  const descriptionId = useId()
  const dialog = useRef<HTMLElement>(null)
  const closeButton = useRef<HTMLButtonElement>(null)

  const [typeFilter, setTypeFilter] = useState<"all" | ExplorerRowKind>("all")
  const [statusFilter, setStatusFilter] = useState<"all" | AuditRunState>("all")
  const [query, setQuery] = useState("")
  const [selectedId, setSelectedId] = useState<string | null>(() => initialExecutionId)
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set())
  const [mobileView, setMobileView] = useState<"list" | "detail">("list")

  const executions = useExplorerExecutions()

  const typeFiltered = useMemo(
    () => (typeFilter === "all" ? executions : executions.filter((row) => row.kind === typeFilter)),
    [executions, typeFilter],
  )

  const trimmedQuery = query.trim().toLowerCase()
  const filtered = useMemo(
    () => typeFiltered.filter(({ model: audit }) => {
      if (statusFilter !== "all" && audit.state !== statusFilter) return false
      if (trimmedQuery === "") return true
      const pipelineNeedles = audit.pipelines.flatMap((pipeline) => {
        const key = pipelineLabelKey(pipeline.id)
        return key === null ? [pipeline.id] : [pipeline.id, tProjects(key)]
      })
      const projectNeedle = audit.project ? `${audit.project.repositoryOwner}/${audit.project.repositoryName}` : ""
      const haystack = [auditExplorerTitle(audit, tProjects), String(audit.id), audit.branch, audit.commitHash, projectNeedle, ...pipelineNeedles]
        .filter(Boolean).join(" ").toLowerCase()
      return haystack.includes(trimmedQuery)
    }),
    [typeFiltered, statusFilter, trimmedQuery, tProjects],
  )

  // Falls back to the first visible row so filters never strand the inspector.
  const selected = filtered.find((row) => String(row.model.id) === selectedId) ?? filtered[0] ?? null

  const statusCounts = useMemo(() => {
    const map = new Map<string, number>([["all", typeFiltered.length]])
    for (const { model: audit } of typeFiltered) {
      map.set(audit.state, (map.get(audit.state) ?? 0) + 1)
    }
    return map
  }, [typeFiltered])

  const typeCounts = useMemo(() => {
    const map = new Map<string, number>([["all", executions.length]])
    for (const row of executions) {
      map.set(row.kind, (map.get(row.kind) ?? 0) + 1)
    }
    return map
  }, [executions])

  useFocusTrap(dialog, open, onClose)

  // Restore focus to whatever opened the explorer, and park it on the close
  // button while open. Unmount-on-close tears the dialog down in the same
  // commit, so restoration happens before the portal disappears.
  useEffect(() => {
    if (!open) return
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    closeButton.current?.focus({ preventScroll: true })
    return () => {
      if (previous?.isConnected) previous.focus({ preventScroll: true })
    }
  }, [open])

  if (!open) return null

  function selectExecution(auditId: string) {
    setSelectedId(auditId)
    setSelectedAgentId(null)
    setMobileView("detail")
  }

  function toggleNode(agentId: string) {
    setCollapsed((current) => {
      const next = new Set(current)
      if (next.has(agentId)) next.delete(agentId)
      else next.add(agentId)
      return next
    })
  }

  const typeOptions = TYPE_FILTERS.map((id) => ({
    id,
    label: id === "all" ? t("filters.type.all") : t(`filters.type.${id}`),
    count: typeCounts.get(id) ?? 0,
  }))
  const statusOptions = STATUS_FILTERS.map((id) => ({
    id,
    label: id === "all" ? t("filters.status.all") : stateLabel(id as AuditRunState),
    count: statusCounts.get(id) ?? 0,
  }))

  return createPortal(
    <div className="execution-explorer-overlay" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose()
    }}>
      <section
        ref={dialog}
        className="execution-explorer-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        tabIndex={-1}
        data-mobile-view={mobileView}
      >
        <header className="execution-explorer-header">
          <span className="execution-explorer-icon" aria-hidden="true"><ActivityIcon size={18} /></span>
          <div className="execution-explorer-heading">
            <h2 id={titleId}>{t("title")}</h2>
            <p id={descriptionId}>{t("description")}</p>
          </div>
          <IconButton className="execution-explorer-close" variant="ghost" size="sm" ariaLabel={tCommon("ui.close")} onClick={onClose} ref={closeButton}>
            <XIcon size={16} />
          </IconButton>
        </header>

        <div className="execution-explorer-filters">
          <FilterTabs options={typeOptions} value={typeFilter} onChange={(id) => setTypeFilter(id as typeof typeFilter)} label={t("filters.type.label")} />
          <FilterTabs compact options={statusOptions} value={statusFilter} onChange={(id) => setStatusFilter(id as typeof statusFilter)} label={t("filters.status.label")} />
          <input
            type="search"
            className="ui-input execution-explorer-search"
            value={query}
            placeholder={t("filters.search.placeholder")}
            aria-label={t("filters.search.label")}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>

        <div className="execution-explorer-main">
          <div className="execution-explorer-list-pane">
            <ExecutionList rows={filtered} selectedId={selected ? String(selected.model.id) : null} onSelect={selectExecution} />
          </div>
          <ExecutionInspector
            row={selected}
            selectedAgentId={selectedAgentId}
            collapsed={collapsed}
            onToggleNode={toggleNode}
            onSelectNode={setSelectedAgentId}
            onBack={() => setMobileView("list")}
          />
        </div>
      </section>
    </div>,
    document.body,
  )
}
