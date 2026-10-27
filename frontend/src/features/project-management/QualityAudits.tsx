import { useEffect, useId, useState } from "react"
import { Link } from "react-router-dom"
import type { ParseKeys } from "i18next"
import { useTranslation } from "react-i18next"
import { Accordion, Badge, Button, Card, Checkbox, Drawer } from "../../shared/ui-kit/index.ts"
import { formatDateTime, formatNumber } from "../../shared/i18n/format.ts"
import { ApiError } from "../../infrastructure/http-client/httpClient.ts"
import { executionStatusLabelKeys, statusLabelKey } from "./projectStatus.ts"
import { downloadQualityAuditReport, getQualityAuditReport, listQualityAudits, startQualityAudit, type QualityAuditSummary } from "./qualityAuditApi.ts"
import "./QualityAudits.css"
import { MaintainabilityConfiguration } from "./MaintainabilityConfiguration.tsx"
import { AuditAttributeSummary } from "./AuditAttributeSummary.tsx"
import { AuditConfigurationDetails } from "./AuditConfigurationDetails.tsx"
import { ReuseAuditConfiguration } from "./ReuseAuditConfiguration.tsx"
import type { ReusedAuditSelection } from "./reuseAuditSelection.ts"
import { availableSubcharacteristics, isAvailable, useAuditAgentCatalog } from "./auditAgentCatalog.ts"

const sections = [
  ["identification", "qualityAudits.report.sections.identification"],
  ["executive_summary", "qualityAudits.report.sections.executive_summary"],
  ["objectives_and_scope", "qualityAudits.report.sections.objectives_and_scope"],
  ["methodology_and_criteria", "qualityAudits.report.sections.methodology_and_criteria"],
  ["software_description", "qualityAudits.report.sections.software_description"],
  ["quality_results", "qualityAudits.report.sections.quality_results"],
  ["consolidated_risks", "qualityAudits.report.sections.consolidated_risks"],
  ["general_conclusions", "qualityAudits.report.sections.general_conclusions"],
  ["recommendations_and_improvement_plan", "qualityAudits.report.sections.recommendations_and_improvement_plan"],
  ["annexes_and_traceability", "qualityAudits.report.sections.annexes_and_traceability"],
] as const

const fieldLabelKeys: Record<string, ParseKeys<"projects">> = {
  objective: "qualityAudits.report.fields.objective",
  evaluated_attributes: "qualityAudits.report.fields.evaluated_attributes",
  principal_results: "qualityAudits.report.fields.principal_results",
  conclusion: "qualityAudits.report.fields.conclusion",
  findings: "qualityAudits.report.fields.findings",
  total: "qualityAudits.report.fields.total",
  by_verification: "qualityAudits.report.fields.by_verification",
  verified: "qualityAudits.report.fields.verified",
  inconclusive: "qualityAudits.report.fields.inconclusive",
  discarded: "qualityAudits.report.fields.discarded",
  status: "qualityAudits.report.fields.status",
  limitations: "qualityAudits.report.fields.limitations",
  source_refs: "qualityAudits.report.fields.source_refs",
  title: "qualityAudits.report.fields.title",
  project_name: "qualityAudits.report.fields.project_name",
  revisions: "qualityAudits.report.fields.revisions",
  executed_at: "qualityAudits.report.fields.executed_at",
}

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

/** Render the canonical report as data, preserving statements and traceability. */
function ReportValue({ value }: { value: unknown }) {
  const { t } = useTranslation("projects")
  if (value === null || value === undefined) return <span className="label">{t("qualityAudits.report.notRecorded")}</span>
  if (Array.isArray(value)) return value.length === 0 ? <span className="label">{t("qualityAudits.report.empty")}</span>
    : <ul>{value.map((item, index) => <li key={index}><ReportValue value={item} /></li>)}</ul>
  if (typeof value === "object") {
    const record = value as Record<string, unknown>
    if (typeof record.text === "string") return <>
      <p>{record.text}</p>
      {Array.isArray(record.source_refs) && record.source_refs.length > 0 && <details>
        <summary>{t("qualityAudits.report.sourceReferences", {
          count: record.source_refs.length, formattedCount: formatNumber(record.source_refs.length),
        })}</summary>
        <pre>{JSON.stringify(record.source_refs, null, 2)}</pre>
      </details>}
    </>
    return <dl>{Object.entries(record).map(([key, child]) => <div key={key}>
      <dt>{fieldLabelKeys[key] ? t(fieldLabelKeys[key]) : key.replaceAll("_", " ")}</dt>
      <dd><ReportValue value={child} /></dd>
    </div>)}</dl>
  }
  return <span>{String(value)}</span>
}

function reportRunId(document: Record<string, unknown>): string | null {
  const identification = document.identification
  if (!identification || typeof identification !== "object") return null
  const id = (identification as Record<string, unknown>).audit_id
  return typeof id === "string" && id.length > 0 ? id : null
}

function AuditRunId({ projectId, audit }: { projectId: number, audit: QualityAuditSummary }) {
  const { t } = useTranslation("projects")
  const { t: tCommon } = useTranslation("common")
  const [runId, setRunId] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    if (audit.runId || !audit.reportAvailable) return
    let alive = true
    getQualityAuditReport(projectId, audit.id).then(
      (document) => { if (alive) setRunId(reportRunId(document)) },
      () => { if (alive) setRunId(null) },
    ).finally(() => { if (alive) setLoaded(true) })
    return () => { alive = false }
  }, [projectId, audit.id, audit.reportAvailable, audit.runId])

  const id = audit.runId ?? runId
  const serverUrl = (import.meta.env.VITE_AGENT_SERVER_URL ?? "http://localhost:7502").replace(/\/+$/, "")
  const pending = audit.reportAvailable && !loaded ? tCommon("ui.loading")
    : ["Waiting", "Running"].includes(audit.executionStatus) ? t("qualityAudits.runId.initializing") : t("qualityAudits.runId.unavailable")
  return <p className="audit-run-id">{t("qualityAudits.runId.label")}: {id
    ? <><code>{id}</code>{" · "}<a className="ui-button ui-button-secondary" href={`${serverUrl}/blackboard?run_id=${encodeURIComponent(id)}`} target="_blank" rel="noreferrer">{t("qualityAudits.runId.openBlackboard")}</a></>
    : <span>{pending}</span>}</p>
}

export function QualityAudits({ projectId, branch, commitHash, canRun, cardLayout = "plain", cardPadding = "default" }: {
  projectId: number, branch: string | null, commitHash: string | null, canRun: boolean,
  cardLayout?: "plain" | "stack", cardPadding?: "default" | "responsive",
}) {
  const { t } = useTranslation("projects")
  const { t: tCommon } = useTranslation("common")
  const attributeId = useId()
  const agentCatalog = useAuditAgentCatalog()
  const [selected, setSelected] = useState(true)
  const [securitySelected, setSecuritySelected] = useState(true)
  const [functionalSelected, setFunctionalSelected] = useState(false)
  const [configurationOpen, setConfigurationOpen] = useState(false)
  const [expandedAttributes, setExpandedAttributes] = useState<Record<string, boolean>>({ maintainability: true, security: true, functional_adequacy: false })
  const [maintainabilitySelection, setMaintainabilitySelection] = useState<Record<string, string[]> | undefined>()
  const invalidMaintainability = selected && maintainabilitySelection !== undefined && Object.keys(maintainabilitySelection).length === 0
  const [requirementsText, setRequirementsText] = useState("")
  const requirements = requirementsText.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
  const invalidRequirements = functionalSelected && (requirements.length === 0 || requirements.length > 100
    || requirements.some((description) => description.length > 10000))
  const [audits, setAudits] = useState<QualityAuditSummary[]>([])
  const [starting, setStarting] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [error, setError] = useState<QualityAuditError | null>(null)
  const [report, setReport] = useState<{ id: number, document: Record<string, unknown> } | null>(null)
  const [loadingReport, setLoadingReport] = useState<number | null>(null)
  const [downloading, setDownloading] = useState<number | null>(null)
  const [reuseNotice, setReuseNotice] = useState<"loaded" | "adjusted" | null>(null)

  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    async function load() {
      try {
        const rows = await listQualityAudits(projectId)
        if (!alive) return
        setAudits(rows)
        if (rows.some((row) => ["Waiting", "Running"].includes(row.executionStatus))) {
          timer = setTimeout(() => void load(), 3000)
        }
      } catch (cause) {
        if (alive) {
          setError(qualityAuditError(cause, "qualityAudits.errors.load"))
          timer = setTimeout(() => void load(), 5000)
        }
      }
    }
    void load()
    return () => { alive = false; clearTimeout(timer) }
  }, [projectId, refresh])

  const running = audits.some((row) => ["Waiting", "Running"].includes(row.executionStatus))
  const configurationAttributes = [
    { id: "maintainability", selected, label: "auditStatus.pipelines.maintainability" },
    { id: "security", selected: securitySelected, label: "auditStatus.pipelines.security" },
    { id: "functional_adequacy", selected: functionalSelected, label: "auditStatus.pipelines.functionalAdequacy" },
  ] as const

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
    const maintainability = availableSubcharacteristics(agentCatalog.agents).length > 0
    const security = agentCatalog.agents.some((agent) => agent.agentType === "security" && isAvailable(agent))
    setMaintainabilitySelection(undefined)
    setSelected(maintainability)
    setSecuritySelected(security)
    setFunctionalSelected(false)
    setExpandedAttributes({ maintainability, security, functional_adequacy: false })
  }

  function reuseConfiguration(selection: ReusedAuditSelection) {
    const maintainability = Object.keys(selection.maintainability).length > 0
    setMaintainabilitySelection(selection.maintainability)
    setSelected(maintainability)
    setSecuritySelected(selection.security)
    setFunctionalSelected(selection.functionalAdequacy)
    setExpandedAttributes({ maintainability, security: selection.security, functional_adequacy: selection.functionalAdequacy })
    setReuseNotice(selection.adjusted ? "adjusted" : "loaded")
    setConfigurationOpen(true)
  }

  async function start() {
    if (!branch || !commitHash || (!selected && !securitySelected && !functionalSelected) || invalidRequirements || invalidMaintainability || starting) return
    setStarting(true)
    setError(null)
    try {
      const selectionOptions = selected && maintainabilitySelection !== undefined
        ? { maintainability_selection: maintainabilitySelection } : {}
      const attributes = [
        ...(selected ? ["maintainability"] : []), ...(securitySelected ? ["security"] : []),
        ...(functionalSelected ? ["functional_adequacy"] : []),
      ]
      if (functionalSelected) {
        await startQualityAudit(projectId, branch, commitHash, attributes, {
          ...selectionOptions,
          functional_requirements: requirements.map((description, index) => ({ requirement_id: `REQ-${String(index + 1).padStart(3, "0")}`, description })),
        })
      } else if (Object.keys(selectionOptions).length) await startQualityAudit(projectId, branch, commitHash, attributes, selectionOptions)
      else await startQualityAudit(projectId, branch, commitHash, attributes)
      setRefresh((value) => value + 1)
    } catch (cause) { setError(qualityAuditError(cause, "qualityAudits.errors.start")) }
    finally { setStarting(false) }
  }

  async function view(id: number) {
    setLoadingReport(id)
    setError(null)
    try { setReport({ id, document: await getQualityAuditReport(projectId, id) }) }
    catch (cause) { setError(qualityAuditError(cause, "qualityAudits.errors.report")) }
    finally { setLoadingReport(null) }
  }

  async function download(id: number) {
    setDownloading(id)
    setError(null)
    try { await downloadQualityAuditReport(projectId, id) }
    catch (cause) { setError(qualityAuditError(cause, "qualityAudits.errors.download")) }
    finally { setDownloading(null) }
  }

  return <div className="quality-audits">
    <Card layout={cardLayout} gap="sm" align={cardLayout === "stack" ? "stretch" : "start"} padding={cardPadding}>
      <div className="quality-audit-heading">
        <div><h2>{t("qualityAudits.title")}</h2><p>{t("qualityAudits.description")}</p></div>
        <span className="quality-audit-revision mono">{branch ?? "—"} @ {commitHash?.slice(0, 7) ?? t("qualityAudits.revisionPending")}</span>
      </div>
      <fieldset className="quality-attributes">
        <legend>{t("qualityAudits.attributesLegend")}</legend>
        {configurationAttributes.map((attribute) => <section key={attribute.id} className="quality-attribute" data-selected={attribute.selected} aria-label={t(attribute.label)}>
          <div className="quality-attribute-copy">
            <div className="quality-attribute-status"><strong>{t(attribute.label)}</strong>
              <Badge tone={attribute.selected ? "success" : "neutral"}>{t(attribute.selected ? "qualityAudits.configuration.active" : "qualityAudits.configuration.inactive")}</Badge>
            </div>
            {attribute.selected && <AuditAttributeSummary attribute={attribute.id} catalog={agentCatalog} selection={maintainabilitySelection} />}
          </div>
        </section>)}
      </fieldset>
      {functionalSelected && <div className="quality-functional-requirements">
        <label htmlFor={`${attributeId}-requirements`}>{t("qualityAudits.requirements.label")}</label>
        <p id={`${attributeId}-requirements-help`} className="label">{t("qualityAudits.requirements.help", { minimum: 1, maximum: 100 })}</p>
        <textarea id={`${attributeId}-requirements`} rows={6} value={requirementsText}
          aria-describedby={`${attributeId}-requirements-help`} aria-invalid={invalidRequirements}
          onChange={(event) => setRequirementsText(event.target.value)} />
      </div>}
      <div className="quality-audit-actions">
        <Button disabled={!canRun || (!selected && !securitySelected && !functionalSelected) || invalidRequirements || invalidMaintainability || starting || running} onClick={() => void start()}>{starting ? t("qualityAudits.starting") : t("qualityAudits.start")}</Button>
        <Button onClick={() => setRefresh((value) => value + 1)}>{tCommon("ui.refresh")}</Button>
        <Button variant="secondary" onClick={() => setConfigurationOpen(true)}>{t("qualityAudits.configuration.title")}</Button>
        <Link className="ui-button ui-button-secondary" to="/settings">{t("qualityAudits.configureAgents")}</Link>
      </div>
      {invalidMaintainability && <p role="status">{t("qualityAudits.configuration.maintainability.selectDimension")}</p>}
      {running && <p role="status">{t("qualityAudits.runningNotice")}</p>}
      {error && <p role="alert">{"detail" in error ? error.detail : t(error.key)}</p>}
    </Card>
    <Card layout={cardLayout} gap="sm" align={cardLayout === "stack" ? "stretch" : "start"} padding={cardPadding}>
      <div className="quality-audit-heading"><h3>{t("qualityAudits.historyTitle")}</h3><Badge tone="neutral">{formatNumber(audits.length)}</Badge></div>
      {audits.length === 0 && <p className="quality-audits-empty">{t("qualityAudits.empty")}</p>}
      {audits.map((audit) => <article className="quality-audit-run" key={audit.id}>
        <div className="quality-audit-run-heading">
        <h4>{audit.attributes?.map((attribute) => attributeLabelKeys[attribute] ? t(attributeLabelKeys[attribute]) : attribute).join(" + ") || t("auditStatus.pipelines.maintainability")} · #{audit.id} · {audit.branch} @ {audit.commitHash?.slice(0, 7)}</h4>
        <Badge tone={audit.auditStatus === "partial" || audit.executionStatus === "Failed" || audit.auditStatus === "failed" ? "warning" : "info"}>
          {audit.auditStatus !== null && evaluationLabelKeys[audit.auditStatus]
            ? t(evaluationLabelKeys[audit.auditStatus]!)
            : statusLabelKey(executionStatusLabelKeys, audit.executionStatus)
              ? t(statusLabelKey(executionStatusLabelKeys, audit.executionStatus)!) : audit.auditStatus ?? audit.executionStatus}
        </Badge>
        </div>
        <div className="quality-audit-run-meta">
        <AuditRunId key={`${projectId}-${audit.id}`} projectId={projectId} audit={audit} />
        <p className="label">{Number.isNaN(new Date(audit.createdAt).getTime())
          ? t("qualityAudits.report.notRecorded") : formatDateTime(audit.createdAt)}</p>
        </div>
        {audit.error && <p role="alert">{audit.error}</p>}
        <div className="quality-audit-history-actions">
          <AuditConfigurationDetails projectId={projectId} auditId={audit.id} available={audit.configurationAvailable === true} />
          <ReuseAuditConfiguration key={`${projectId}-${audit.id}`} projectId={projectId} auditId={audit.id}
            available={audit.configurationAvailable === true} catalog={agentCatalog} disabled={starting} onReuse={reuseConfiguration} />
        {audit.reportAvailable && <>
          <Button disabled={loadingReport !== null} onClick={() => void view(audit.id)}>{loadingReport === audit.id ? tCommon("ui.loading") : t("qualityAudits.viewReport")}</Button>
          <Button disabled={downloading !== null} onClick={() => void download(audit.id)}>{downloading === audit.id ? t("qualityAudits.downloading") : t("qualityAudits.downloadWord")}</Button>
        </>}
        </div>
      </article>)}
    </Card>
    {report && <Card layout={cardLayout} gap={cardLayout === "stack" ? "md" : "sm"} align={cardLayout === "stack" ? "stretch" : "start"} padding={cardPadding}>
      <h2>{t("qualityAudits.report.title", { id: report.id })}</h2>
      {reportRunId(report.document) && <p>{t("qualityAudits.runId.label")}: <code>{reportRunId(report.document)}</code></p>}
      <p>{t("qualityAudits.report.originalNotice")}</p>
      <div className="quality-report">{sections.map(([key, titleKey]) => <details key={`${report.id}-${key}`} open={key === "executive_summary"}>
        <summary>{t(titleKey)}</summary>
        <ReportValue value={report.document[key]} />
      </details>)}</div>
    </Card>}
    <Drawer
      open={configurationOpen}
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
         {configurationAttributes.map((attribute) => <Accordion key={attribute.id} title={t(attribute.label)}
           open={Boolean(expandedAttributes[attribute.id])} disabled={!attribute.selected}
           onOpenChange={(open) => setExpandedAttributes((current) => ({ ...current, [attribute.id]: open }))}
           headerAction={<Checkbox label={t("qualityAudits.configuration.enableAttribute", { attribute: t(attribute.label) })} checked={attribute.selected}
             onChange={(checked) => setAttributeEnabled(attribute.id, checked)} />}>
          {attribute.id === "maintainability" ? <MaintainabilityConfiguration catalog={agentCatalog} value={maintainabilitySelection} onChange={(selection) => {
            setMaintainabilitySelection(selection)
            setSelected(Object.keys(selection).length > 0)
            if (!Object.keys(selection).length) setExpandedAttributes((current) => ({ ...current, maintainability: false }))
          }} /> : <p className="label">{t("qualityAudits.configuration.optionsPending")}</p>}
         </Accordion>)}
        {!configurationAttributes.some((attribute) => attribute.selected) && <p className="label">{t("qualityAudits.configuration.noAttributes")}</p>}
      </div>
    </Drawer>
  </div>
}
