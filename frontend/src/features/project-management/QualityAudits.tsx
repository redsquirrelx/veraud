import { useEffect, useState } from "react"
import { Link } from "react-router-dom"
import type { ParseKeys } from "i18next"
import { useTranslation } from "react-i18next"
import { Accordion, Badge, Button, Card, Checkbox, Drawer, DotsIcon, FilterTabs, Pagination, Spinner } from "../../shared/ui-kit/index.ts"
import { useDropdownDisclosure } from "../../shared/ui-kit/useDropdownDisclosure.ts"
import { formatDateTime, formatNumber } from "../../shared/i18n/format.ts"
import { ApiError } from "../../infrastructure/http-client/httpClient.ts"
import { executionStatusLabelKeys, statusLabelKey } from "./projectStatus.ts"
import { auditStateFrom, stateTone, type AuditRunState } from "../../shared/audit-monitor/auditStatus.ts"
import { useAuditStateLabel } from "../../shared/audit-monitor/monitorLabels.ts"
import { publicErrorText } from "../../infrastructure/http-client/publicErrors.ts"
import { useAuditCancellationRevision } from "../../shared/agent-monitor/useAgentExecutions.ts"
import { downloadQualityAuditReport, listQualityAudits, listQualityAuditPage, startQualityAudit, type QualityAuditSummary } from "./qualityAuditApi.ts"
import "./QualityAudits.css"
import { MaintainabilityConfiguration } from "./MaintainabilityConfiguration.tsx"
import { AuditAttributeSummary } from "./AuditAttributeSummary.tsx"
import { AuditConfigurationDetails } from "./AuditConfigurationDetails.tsx"
import { ReuseAuditConfiguration } from "./ReuseAuditConfiguration.tsx"
import type { ReusedAuditSelection } from "./reuseAuditSelection.ts"
import { useAuditAgentCatalog } from "./auditAgentCatalog.ts"
import { auditReadiness } from "./auditReadiness.ts"
import { useAuditStartMessages } from "./auditStartMessages.ts"
import { useAuditHistoryLabels } from "./auditHistoryLabels.ts"
import { AuditAttributeConfiguration } from "./AuditAttributeConfiguration.tsx"
import { auditDraftValues, type AuditAttributeDraft } from "./auditOperatingSettingsApi.ts"
import { FUNCTIONAL_AUDIT_MODES } from "./functionalAuditUi.ts"
import { useArchitectureContextAvailability } from "./useArchitectureContextAvailability.ts"

const attributeLabelKeys: Record<string, ParseKeys<"projects">> = {
  maintainability: "auditStatus.pipelines.maintainability",
  security: "auditStatus.pipelines.security",
  functional_adequacy: "auditStatus.pipelines.functionalAdequacy",
}

const evaluationLabelKeys: Record<string, ParseKeys<"projects">> = {
  partial: "qualityAudits.evaluation.partial",
  completed: "qualityAudits.evaluation.completed",
  failed: "qualityAudits.evaluation.failed",
}

type QualityAuditError = { key: ParseKeys<"projects"> } | { detail: string }

function qualityAuditError(cause: unknown, key: ParseKeys<"projects">): QualityAuditError {
  return cause instanceof ApiError && cause.messageSource !== "client" ? { detail: cause.message } : { key }
}

/** Blackboard access; the full run ID stays on the audit detail page. */
function AuditBlackboardLink({ audit, menuItem = false }: { audit: QualityAuditSummary, menuItem?: boolean }) {
  const { t } = useTranslation("projects")
  const id = audit.runId
  const label = t("qualityAudits.runId.openBlackboard")
  if (menuItem) {
    if (!id) return <button type="button" className="quality-audit-row-menu-item" disabled title={t("qualityAudits.runId.unavailable")}>{label}</button>
    const serverUrl = (import.meta.env.VITE_AGENT_SERVER_URL ?? "http://localhost:7502").replace(/\/+$/, "")
    return <a className="quality-audit-row-menu-item" href={`${serverUrl}/blackboard?run_id=${encodeURIComponent(id)}`} target="_blank" rel="noreferrer">{label}</a>
  }
  if (!id) {
    return <Button variant="secondary" disabled title={t("qualityAudits.runId.unavailable")}>
      {label}
    </Button>
  }
  const serverUrl = (import.meta.env.VITE_AGENT_SERVER_URL ?? "http://localhost:7502").replace(/\/+$/, "")
  return <a className="ui-button ui-button-secondary" href={`${serverUrl}/blackboard?run_id=${encodeURIComponent(id)}`} target="_blank" rel="noreferrer">{label}</a>
}

type AuditStatusFilter = "all" | "completed" | "partial" | "failed"

function matchesAuditStatusFilter(audit: QualityAuditSummary, filter: AuditStatusFilter): boolean {
  if (filter === "all") return true
  return auditStateFrom(audit.executionStatus, audit.auditStatus) === (filter as AuditRunState)
}

function AuditRowMenu({ audit, downloading, onDownload, onViewConfiguration }: {
  audit: QualityAuditSummary
  downloading: number | null
  onDownload: (id: number) => void
  onViewConfiguration: () => void
}) {
  const { t } = useTranslation("projects")
  const configAvailable = audit.configurationAvailable === true
  const { id, root, trigger, expanded, close, toggle, onKeyDown, onBlur } = useDropdownDisclosure({
    inactive: false,
    initialSelector: "button:not(:disabled), a[href]",
    navigationSelector: "button:not(:disabled), a[href]",
  })
  const label = t("qualityAudits.moreActions", { id: audit.id })
  return <div className="quality-audit-row-menu" ref={root} onKeyDown={onKeyDown} onBlur={onBlur}>
    <button
      id={`${id}-trigger`}
      ref={trigger}
      type="button"
      className="ui-icon-button ui-icon-button-ghost ui-icon-button-sm quality-audit-row-menu-trigger"
      aria-expanded={expanded}
      aria-haspopup="menu"
      aria-label={label}
      title={label}
      aria-controls={`${id}-menu`}
      onClick={toggle}
    >
      <DotsIcon size={16} />
    </button>
    {expanded && <div id={`${id}-menu`} className="quality-audit-row-menu-panel ui-menu-surface" data-align="end" role="menu" aria-labelledby={`${id}-trigger`}>
      <ul>
        <li><button type="button" className="quality-audit-row-menu-item" disabled={!configAvailable}
          title={!configAvailable ? t("qualityAudits.configurationHistory.unavailable") : undefined}
          onClick={() => { close(false); onViewConfiguration() }}>{t("qualityAudits.configurationHistory.view")}</button></li>
        <li onClick={() => close(true)}><AuditBlackboardLink audit={audit} menuItem /></li>
        {audit.reportAvailable && <li><button type="button" className="quality-audit-row-menu-item" disabled={downloading !== null}
          onClick={() => { close(false); onDownload(audit.id) }}>{downloading === audit.id ? t("qualityAudits.downloading") : t("qualityAudits.downloadWord")}</button></li>}
      </ul>
    </div>}
  </div>
}

export function QualityAudits({ projectId, branch, commitHash, canRun, cardLayout = "plain", cardPadding = "default", view = "all", onConfigure }: {
  projectId: number, branch: string | null, commitHash: string | null, canRun: boolean,
  cardLayout?: "plain" | "stack", cardPadding?: "default" | "responsive",
  view?: "all" | "configuration" | "history", onConfigure?: () => void,
}) {
  const { t } = useTranslation("projects")
  const { t: tCommon } = useTranslation("common")
  const agentCatalog = useAuditAgentCatalog(view !== "history")
  const startMessages = useAuditStartMessages()
  const historyLabels = useAuditHistoryLabels()
  const auditStateLabel = useAuditStateLabel()
  const cancellationRevision = useAuditCancellationRevision(projectId)
  // Defaults follow executable roots; explicit user selections remain authoritative
  // even if a later catalog refresh makes an agent unavailable.
  const [maintainabilityEnabled, setSelected] = useState<boolean | undefined>()
  const [securityEnabled, setSecuritySelected] = useState<boolean | undefined>()
  const selected = maintainabilityEnabled ?? (auditReadiness(agentCatalog.agents, ["maintainability"]).length === 0)
  const securitySelected = securityEnabled ?? (auditReadiness(agentCatalog.agents, ["security"]).length === 0)
  const [functionalSelected, setFunctionalSelected] = useState(false)
  const [configurationOpen, setConfigurationOpen] = useState(false)
  const [expandedAttributes, setExpandedAttributes] = useState<Record<string, boolean>>({ maintainability: true, security: true, functional_adequacy: false })
  const [maintainabilitySelection, setMaintainabilitySelection] = useState<Record<string, string[]> | undefined>()
  const invalidMaintainability = selected && maintainabilitySelection !== undefined && Object.keys(maintainabilitySelection).length === 0
  const [attributeDrafts, setAttributeDrafts] = useState<Record<string, AuditAttributeDraft>>({})
  const [configurationRevision, setConfigurationRevision] = useState(0)
  const [audits, setAudits] = useState<QualityAuditSummary[]>([])
  const [loadingAudits, setLoadingAudits] = useState(true)
  const [totalAudits, setTotalAudits] = useState(0)
  const [hasRunning, setHasRunning] = useState(false)
  const [pageSize, setPageSize] = useState(5)
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState<AuditStatusFilter>("all")
  const [configAuditId, setConfigAuditId] = useState<number | null>(null)
  const pageCount = Math.max(1, Math.ceil(totalAudits / pageSize))
  const currentPage = Math.min(page, pageCount)
  const visibleAudits = audits
  const [starting, setStarting] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [actionError, setError] = useState<QualityAuditError | null>(null)
  const [loadError, setLoadError] = useState<QualityAuditError | null>(null)
  const error = actionError ?? loadError
  const [downloading, setDownloading] = useState<number | null>(null)
  const [reuseNotice, setReuseNotice] = useState<"loaded" | "adjusted" | null>(null)
  const context = useArchitectureContextAvailability(projectId, commitHash, view !== "history", `${canRun}:${refresh}`)
  const contextMessage = t(context.status === "loading" ? "analyze.pipeline.contextChecking"
    : context.status === "failed" ? "analyze.pipeline.contextCheckFailed"
    : !context.available ? "analyze.pipeline.contextRequired"
    : context.executionStatus === "partial" ? "analyze.pipeline.context_partial" : "analyze.pipeline.context_complete")

  useEffect(() => {
    let alive = true
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    async function load() {
      setLoadingAudits(true)
      try {
        // The paginated endpoint has no status query, so a specific filter must
        // fetch the lightweight summaries once and filter before paginating.
        // "All" keeps the efficient single-page server request.
        if (statusFilter !== "all") {
          const rows = await listQualityAudits(projectId, controller.signal)
          if (!alive) return
          const filtered = rows.filter((audit) => matchesAuditStatusFilter(audit, statusFilter))
          const filteredPageCount = Math.max(1, Math.ceil(filtered.length / pageSize))
          const safePage = Math.min(page, filteredPageCount)
          setAudits(filtered.slice((safePage - 1) * pageSize, safePage * pageSize))
          setTotalAudits(filtered.length)
          setHasRunning(rows.some((row) => ["Waiting", "Running"].includes(row.executionStatus)))
          setLoadError(null)
          if (safePage !== page) setPage(safePage)
          if (rows.some((row) => ["Waiting", "Running"].includes(row.executionStatus))) {
            timer = setTimeout(() => void load(), 3000)
          }
          return
        }
        const result = await listQualityAuditPage(projectId, pageSize, (page - 1) * pageSize, controller.signal)
        if (!alive) return
        setAudits(result.items)
        setTotalAudits(result.total)
        setHasRunning(result.hasRunning)
        setLoadError(null)
        const landedPage = Math.floor(result.offset / pageSize) + 1
        if (landedPage !== page) setPage(landedPage)
        if (result.hasRunning) {
          timer = setTimeout(() => void load(), 3000)
        }
      } catch (cause) {
        if (alive) {
          setLoadError(qualityAuditError(cause, "qualityAudits.errors.load"))
          timer = setTimeout(() => void load(), 5000)
        }
      } finally {
        if (alive) setLoadingAudits(false)
      }
    }
    void load()
    return () => { alive = false; controller.abort(); clearTimeout(timer) }
  }, [projectId, refresh, cancellationRevision, page, pageSize, statusFilter])

  const running = hasRunning
  const configurationAttributes = [
    { id: "maintainability", selected, label: "auditStatus.pipelines.maintainability" },
    { id: "security", selected: securitySelected, label: "auditStatus.pipelines.security" },
    { id: "functional_adequacy", selected: functionalSelected, label: FUNCTIONAL_AUDIT_MODES.exploratory.labelKey },
  ] as const
  const selectedAttributes = configurationAttributes.filter((attribute) => attribute.selected).map((attribute) => attribute.id)
  const readinessIssues = auditReadiness(agentCatalog.agents, selectedAttributes).filter((issue) =>
    issue.attribute !== "functional_adequacy" || issue.reason === "unavailable")
  const ready = !agentCatalog.loading && !agentCatalog.failed && readinessIssues.length === 0
  let invalidOptions = false
  const attributeOptions: Record<string, Record<string, unknown>> = {}
  for (const attribute of selectedAttributes) {
    if (attribute === "maintainability") continue
    try {
      const values = auditDraftValues(attribute, attributeDrafts[attribute])
      if (Object.keys(values).length) attributeOptions[attribute] = values
    } catch { invalidOptions = true }
  }
  const startBlocked = !canRun || !branch || !commitHash || !ready || !selectedAttributes.length
    || (selected && !context.available) || invalidMaintainability || invalidOptions || starting || running
  const startBlocker = !branch || !commitHash ? startMessages.revision
    : !canRun ? startMessages.project
    : selected && !context.available ? contextMessage
    : agentCatalog.loading ? tCommon("ui.loading")
    : !agentCatalog.failed && !selectedAttributes.length ? startMessages.selection
    : starting ? t("qualityAudits.starting") : null

  function setAttributeEnabled(id: string, checked: boolean) {
    setExpandedAttributes((current) => ({ ...current, [id]: checked }))
    if (id === "maintainability") {
      setSelected(checked)
      setMaintainabilitySelection(checked ? undefined : {})
    } else if (id === "security") setSecuritySelected(checked)
    else setFunctionalSelected(checked)
  }

  function restoreSelectionDefaults() {
    setReuseNotice(null)
    setAttributeDrafts({})
    setConfigurationRevision((value) => value + 1)
    const maintainability = auditReadiness(agentCatalog.agents, ["maintainability"]).length === 0
    const security = auditReadiness(agentCatalog.agents, ["security"]).length === 0
    setMaintainabilitySelection(undefined)
    setSelected(maintainability)
    setSecuritySelected(security)
    setFunctionalSelected(false)
    setExpandedAttributes({ maintainability, security, functional_adequacy: false })
  }

  function reuseConfiguration(selection: ReusedAuditSelection) {
    setAttributeDrafts({})
    setConfigurationRevision((value) => value + 1)
    const maintainability = Object.keys(selection.maintainability).length > 0
    setMaintainabilitySelection(selection.maintainability)
    setSelected(maintainability)
    setSecuritySelected(selection.security)
    setFunctionalSelected(selection.functionalAdequacy)
    setExpandedAttributes({ maintainability, security: selection.security, functional_adequacy: selection.functionalAdequacy })
    setReuseNotice(selection.adjusted ? "adjusted" : "loaded")
    setConfigurationOpen(true)
    onConfigure?.()
  }

  async function start() {
    if (startBlocked || !branch || !commitHash) return
    setStarting(true)
    setError(null)
    try {
      const selectionOptions = selected && maintainabilitySelection !== undefined
        ? { maintainability_selection: maintainabilitySelection } : {}
      const operatingOptions = { ...(Object.keys(attributeOptions).length ? { attribute_options: attributeOptions } : {}) }
      const attributes = [
        ...(selected ? ["maintainability"] : []), ...(securitySelected ? ["security"] : []),
        ...(functionalSelected ? ["functional_adequacy"] : []),
      ]
      if (functionalSelected) {
        await startQualityAudit(projectId, branch, commitHash, attributes, {
          ...selectionOptions,
          ...operatingOptions,
          functional_requirements: [],
        })
      } else if (Object.keys(selectionOptions).length || Object.keys(operatingOptions).length) await startQualityAudit(projectId, branch, commitHash, attributes, { ...selectionOptions, ...operatingOptions })
      else await startQualityAudit(projectId, branch, commitHash, attributes)
      setRefresh((value) => value + 1)
    } catch (cause) { setError(qualityAuditError(cause, "qualityAudits.errors.start")) }
    finally { setStarting(false) }
  }

  async function download(id: number) {
    setDownloading(id)
    setError(null)
    try { await downloadQualityAuditReport(projectId, id) }
    catch (cause) { setError(qualityAuditError(cause, "qualityAudits.errors.download")) }
    finally { setDownloading(null) }
  }

  const historyPagination = audits.length > 0 && <div className="quality-audit-pagination">
    <label>{historyLabels.pageSize}
      <select value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1) }}>
        {[5, 10, 15, 20].map((size) => <option key={size} value={size}>{formatNumber(size)}</option>)}
      </select>
    </label>
    <Pagination page={currentPage} pageCount={pageCount} onChange={setPage} label={historyLabels.pagination} />
  </div>

  return <div className="quality-audits">
    {view !== "history" && <Card layout={cardLayout} gap="sm" align={cardLayout === "stack" ? "stretch" : "start"} padding={cardPadding}>
      <div className="quality-audit-heading">
        <div><h2>{t("qualityAudits.title")}</h2><p>{t("qualityAudits.description")}</p></div>
        <span className="quality-audit-revision mono">{branch ?? "—"} @ {commitHash?.slice(0, 7) ?? t("qualityAudits.revisionPending")}</span>
      </div>
      <fieldset className="quality-attributes">
        <legend>{t("qualityAudits.attributesLegend")}</legend>
         {configurationAttributes.map((attribute) => <section key={attribute.id} className="quality-attribute" data-selected={attribute.selected} aria-label={t(attribute.label)}
           aria-disabled={attribute.id === "maintainability" && !context.available}>
          <div className="quality-attribute-copy">
            <div className="quality-attribute-status"><strong>{t(attribute.label)}</strong>
              <Badge tone={attribute.selected && (attribute.id !== "maintainability" || context.available) ? "success" : "neutral"}>{t(attribute.selected && (attribute.id !== "maintainability" || context.available) ? "qualityAudits.configuration.active" : "qualityAudits.configuration.inactive")}</Badge>
            </div>
            {attribute.selected && <AuditAttributeSummary attribute={attribute.id} catalog={agentCatalog} selection={maintainabilitySelection}
               functionalMode={attribute.id === "functional_adequacy" ? "exploratory" : undefined} />}
            {attribute.id === "maintainability" && <p className="label">{contextMessage}</p>}
          </div>
        </section>)}
      </fieldset>
      <div className="quality-audit-actions">
        <Button disabled={startBlocked} title={startBlocker ?? undefined} onClick={() => void start()}>{starting ? t("qualityAudits.starting") : t("qualityAudits.start")}</Button>
        <Button variant="secondary" onClick={() => setRefresh((value) => value + 1)}>{tCommon("ui.refresh")}</Button>
        <Button variant="secondary" onClick={() => setConfigurationOpen(true)}>{t("qualityAudits.configuration.title")}</Button>
        <Link className="ui-button ui-button-secondary" to="/settings">{t("qualityAudits.configureAgents")}</Link>
      </div>
      {startBlocker && <p role="status">{startBlocker}</p>}
      {!agentCatalog.loading && (agentCatalog.failed || readinessIssues.length > 0 || !selectedAttributes.length) && <div role="status">
        {agentCatalog.failed ? <p>{t("qualityAudits.setup.catalogFailed")}</p> : readinessIssues.map((issue) => <p key={issue.attribute}>
          {t(attributeLabelKeys[issue.attribute]!)}: {t(`qualityAudits.setup.${issue.reason}`)}
        </p>)}
        <Button variant="secondary" onClick={agentCatalog.retry}>{t("qualityAudits.setup.checkAgain")}</Button>
      </div>}
      {invalidOptions && <p role="status">{t("qualityAudits.setup.invalidOptions")}</p>}
      {invalidMaintainability && <p role="status">{t("qualityAudits.configuration.maintainability.selectDimension")}</p>}
      {running && <p role="status">{t("qualityAudits.runningNotice")}</p>}
      {error && <p role="alert">{"detail" in error ? error.detail : t(error.key)}</p>}
    </Card>}
    {view !== "configuration" && <Card layout={cardLayout} gap="sm" align={cardLayout === "stack" ? "stretch" : "start"} padding={cardPadding}>
      <div className="quality-audit-heading">
        <div className="quality-audit-history-title"><h3>{t("qualityAudits.historyTitle")}</h3><Badge tone="neutral">{formatNumber(totalAudits)}</Badge></div>
        {view === "history" && <Button variant="secondary" disabled={loadingAudits} onClick={() => setRefresh((value) => value + 1)}>{tCommon("ui.refresh")}</Button>}
      </div>
      {view === "history" && error && <p role="alert">{"detail" in error ? error.detail : t(error.key)}</p>}
      <div className="quality-audit-history-filters">
        <FilterTabs
          label={t("qualityAudits.historyFilter.label")}
          value={statusFilter}
          onChange={(id) => { setStatusFilter(id as AuditStatusFilter); setPage(1) }}
          options={[
            { id: "all", label: t("qualityAudits.historyFilter.all"), count: 0 },
            { id: "completed", label: t("qualityAudits.historyFilter.completed"), count: 0 },
            { id: "partial", label: t("qualityAudits.historyFilter.partial"), count: 0 },
            { id: "failed", label: t("qualityAudits.historyFilter.failed"), count: 0 },
          ]}
        />
      </div>
      {historyPagination}
      {loadingAudits && <div className="quality-audits-loading" role="status" aria-label={t("qualityAudits.loading")}>
        <Spinner />
        <span className="label">{t("qualityAudits.loading")}</span>
      </div>}
      {!loadingAudits && !error && audits.length === 0 && <p className="quality-audits-empty">{statusFilter !== "all" ? t("qualityAudits.historyFilter.empty") : t("qualityAudits.empty")}</p>}
      {!loadingAudits && <div className="quality-audits-explorer">
      {visibleAudits.map((audit) => {
        const state = auditStateFrom(audit.executionStatus, audit.auditStatus)
        const statusLabel = audit.auditStatus === "cancelling" || audit.auditStatus === "cancelled" ? auditStateLabel(audit.auditStatus)
          : audit.auditStatus !== null && evaluationLabelKeys[audit.auditStatus]
            ? t(evaluationLabelKeys[audit.auditStatus]!)
            : statusLabelKey(executionStatusLabelKeys, audit.executionStatus)
              ? t(statusLabelKey(executionStatusLabelKeys, audit.executionStatus)!) : audit.auditStatus ?? audit.executionStatus
        return <article className="quality-audit-run quality-audit-run-row" key={audit.id}>
          <div className="quality-audit-run-row-top">
            <h4>{audit.attributes?.map((attribute) => attributeLabelKeys[attribute] ? t(attributeLabelKeys[attribute]) : attribute).join(" + ") || t("auditStatus.pipelines.maintainability")} · #{audit.id}</h4>
            <Badge tone={stateTone(state)}>{statusLabel}</Badge>
          </div>
          <div className="quality-audit-run-row-bottom">
            <p className="quality-audit-run-meta-label">
              <span className="mono">{audit.branch ?? "—"} @ {audit.commitHash?.slice(0, 7) ?? t("qualityAudits.revisionPending")}</span>
              {" · "}
              <span>{Number.isNaN(new Date(audit.createdAt).getTime())
                ? t("qualityAudits.report.notRecorded") : formatDateTime(audit.createdAt)}</span>
            </p>
            <div className="quality-audit-run-row-actions">
              <Link className="ui-button ui-button-secondary" to={`/projects/${projectId}/audits/${audit.id}`}>{t("qualityAudits.viewDetails")}</Link>
              <ReuseAuditConfiguration key={`${projectId}-${audit.id}`} projectId={projectId} auditId={audit.id}
                available={audit.configurationAvailable === true} catalog={agentCatalog} lazyCatalog={view === "history"} disabled={starting} onReuse={reuseConfiguration} />
              <AuditRowMenu audit={audit}
                downloading={downloading} onDownload={(id) => void download(id)}
                onViewConfiguration={() => setConfigAuditId(audit.id)} />
            </div>
          </div>
          {audit.error && <p role="alert">{publicErrorText(audit.error)}</p>}
          <AuditConfigurationDetails projectId={projectId} auditId={audit.id} available={audit.configurationAvailable === true}
            hideTrigger open={configAuditId === audit.id} onOpenChange={(open) => { if (!open) setConfigAuditId(null) }} />
        </article>
      })}
      </div>}
      {historyPagination}
    </Card>}
    <Drawer
      open={configurationOpen && view !== "history"}
      title={t("qualityAudits.configuration.title")}
      description={t("qualityAudits.configuration.description")}
      onClose={() => setConfigurationOpen(false)}
      footer={<Button variant="secondary" disabled={agentCatalog.loading || agentCatalog.failed} onClick={restoreSelectionDefaults}>
        {t("qualityAudits.configuration.restoreDefaults")}
      </Button>}
    >
      <div className="quality-audit-configuration">
        {reuseNotice && <p role="status" className="label">{t(reuseNotice === "adjusted" ? "qualityAudits.configurationHistory.reuseAdjusted" : "qualityAudits.configurationHistory.reuseLoaded")}</p>}
         <p className="label">{t("qualityAudits.configuration.previewNotice")}</p>
         <p role="status">{contextMessage}</p>
         {configurationAttributes.map((attribute) => <Accordion key={attribute.id} title={t(attribute.label)}
            open={Boolean(expandedAttributes[attribute.id])} disabled={!attribute.selected || (attribute.id === "maintainability" && !context.available)}
           onOpenChange={(open) => setExpandedAttributes((current) => ({ ...current, [attribute.id]: open }))}
            headerAction={<Checkbox label={t("qualityAudits.configuration.enableAttribute", { attribute: t(attribute.label) })} checked={attribute.selected}
              disabled={attribute.id === "maintainability" && !context.available && !attribute.selected}
             onChange={(checked) => setAttributeEnabled(attribute.id, checked)} />}>
            {attribute.id === "maintainability" ? <fieldset disabled={!context.available}><MaintainabilityConfiguration catalog={agentCatalog} value={maintainabilitySelection} onChange={(selection) => {
            setMaintainabilitySelection(selection)
            setSelected(Object.keys(selection).length > 0)
            if (!Object.keys(selection).length) setExpandedAttributes((current) => ({ ...current, maintainability: false }))
            }} />
            </fieldset> : <>
             <AuditAttributeConfiguration key={`${configurationRevision}-${attribute.id}`} attribute={attribute.id} catalog={agentCatalog}
               draft={attributeDrafts[attribute.id] ?? { form: {} }}
               onChange={(draft) => setAttributeDrafts((current) => ({ ...current, [attribute.id]: draft }))} />
           </>}
         </Accordion>)}
        {!configurationAttributes.some((attribute) => attribute.selected) && <p className="label">{t("qualityAudits.configuration.noAttributes")}</p>}
      </div>
    </Drawer>
  </div>
}
