import type { ParseKeys } from "i18next"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { formatNumber } from "../../shared/i18n/format.ts"
import { Button, Spinner } from "../../shared/ui-kit/index.ts"
import { auditReportSections, type AuditReportSection } from "./qualityAuditReport.ts"
import { getQualityAuditReportSection } from "./qualityAuditApi.ts"
import { AuditFindingsSummary } from "./AuditFindingsSummary.tsx"
import { QualityAuditFindings } from "./QualityAuditFindings.tsx"
import type { AuditReportSectionResource } from "./useAuditReportSection.ts"

const fieldLabelKeys: Record<string, ParseKeys<"projects">> = {
  objective: "qualityAudits.report.fields.objective", evaluated_attributes: "qualityAudits.report.fields.evaluated_attributes",
  principal_results: "qualityAudits.report.fields.principal_results", conclusion: "qualityAudits.report.fields.conclusion",
  findings: "qualityAudits.report.fields.findings", total: "qualityAudits.report.fields.total", by_verification: "qualityAudits.report.fields.by_verification",
  verified: "qualityAudits.report.fields.verified", inconclusive: "qualityAudits.report.fields.inconclusive", discarded: "qualityAudits.report.fields.discarded",
  status: "qualityAudits.report.fields.status", limitations: "qualityAudits.report.fields.limitations", source_refs: "qualityAudits.report.fields.source_refs",
  title: "qualityAudits.report.fields.title", project_name: "qualityAudits.report.fields.project_name", revisions: "qualityAudits.report.fields.revisions",
  executed_at: "qualityAudits.report.fields.executed_at",
}

/** Preserve canonical report statements and provenance rather than interpreting them. */
function ReportValue({ value }: { value: unknown }) {
  const { t } = useTranslation("projects")
  if (value === null || value === undefined) return <span className="label">{t("qualityAudits.report.notRecorded")}</span>
  if (Array.isArray(value)) return value.length === 0 ? <span className="label">{t("qualityAudits.report.empty")}</span>
    : <ReportList items={value} />
  if (typeof value === "object") {
    const record = value as Record<string, unknown>
    if (typeof record.text === "string") return <>
      <p>{record.text}</p>
      {Array.isArray(record.source_refs) && record.source_refs.length > 0 && <SourceReferences items={record.source_refs} />}
    </>
    return <dl>{Object.entries(record).map(([key, child]) => <div key={key}>
      <dt>{fieldLabelKeys[key] ? t(fieldLabelKeys[key]) : key.replaceAll("_", " ")}</dt>
      <dd><ReportValue value={child} /></dd>
    </div>)}</dl>
  }
  return <span>{String(value)}</span>
}

function ReportList({ items }: { items: unknown[] }) {
  const { t } = useTranslation("projects")
  const [visible, setVisible] = useState(50)
  return <>
    <ul>{items.slice(0, visible).map((item, index) => <li key={index}><ReportValue value={item} /></li>)}</ul>
    {visible < items.length && <Button variant="secondary" onClick={() => setVisible((count) => count + 50)}>{t("qualityAudits.results.showMore", { remaining: formatNumber(items.length - visible) })}</Button>}
  </>
}

function SourceReferences({ items }: { items: unknown[] }) {
  const { t } = useTranslation("projects")
  const [open, setOpen] = useState(false)
  return <details onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary>{t("qualityAudits.report.sourceReferences", { count: items.length, formattedCount: formatNumber(items.length) })}</summary>
    {open && <ReportList items={items} />}
  </details>
}

type SectionState = { status: "loading" } | { status: "loaded", data: unknown } | { status: "error" }

function QualityResultsReport({ data }: { data: unknown }) {
  if (!data || typeof data !== "object" || Array.isArray(data)) return <ReportValue value={data} />
  const { findings, ...rest } = data as Record<string, unknown>
  return <>
    <QualityAuditFindings findings={findings} renderDetails={(finding) => <ReportValue value={finding} />} />
    {Object.keys(rest).length > 0 && <ReportValue value={rest} />}
  </>
}

export function QualityAuditFindingsPanel({ resource }: { resource: AuditReportSectionResource }) {
  const { t } = useTranslation("projects")
  if (resource.state.status === "loading") return <Spinner />
  if (resource.state.status === "error") return <div role="alert">
    <p>{t("qualityAudits.results.sectionFailed")}</p>
    <Button variant="secondary" onClick={resource.retry}>{t("qualityAudits.results.retry")}</Button>
  </div>
  const data = resource.state.data
  const findings = data && typeof data === "object" && !Array.isArray(data) ? (data as Record<string, unknown>).findings : null
  return <div className="quality-report"><QualityAuditFindings findings={findings} renderDetails={(finding) => <ReportValue value={finding} />} /></div>
}

function QualityResultsSection({ resource, onOpenChange, title }: { resource: AuditReportSectionResource, onOpenChange: (open: boolean) => void, title: string }) {
  const { t } = useTranslation("projects")
  const [open, setOpen] = useState(false)
  return <details open={open} onToggle={(event) => {
    setOpen(event.currentTarget.open)
    onOpenChange(event.currentTarget.open)
  }}>
    <summary>{title}</summary>
    {open && (resource.state.status === "loaded" ? <QualityResultsReport data={resource.state.data} />
      : resource.state.status === "loading" ? <Spinner /> : <div role="alert">
        <p>{t("qualityAudits.results.sectionFailed")}</p>
        <Button variant="secondary" onClick={resource.retry}>{t("qualityAudits.results.retry")}</Button>
      </div>)}
  </details>
}

function ReportSection({ projectId, auditId, section, title, onExecutiveSummaryLoaded }: { projectId: number, auditId: number, section: AuditReportSection, title: string, onExecutiveSummaryLoaded: (data: unknown) => void }) {
  const { t } = useTranslation("projects")
  const [open, setOpen] = useState(section === "executive_summary")
  const [resource, setResource] = useState<SectionState>({ status: "loading" })

  useEffect(() => {
    if (!open || resource.status !== "loading") return
    const controller = new AbortController()
    getQualityAuditReportSection(projectId, auditId, section, controller.signal).then((result) => {
      if (!controller.signal.aborted) {
        setResource({ status: "loaded", data: result.data })
        if (section === "executive_summary") onExecutiveSummaryLoaded(result.data)
      }
    }, () => { if (!controller.signal.aborted) setResource({ status: "error" }) })
    return () => controller.abort()
  }, [projectId, auditId, section, open, resource.status, onExecutiveSummaryLoaded])

  return <details open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary>{title}</summary>
    {open && (resource.status === "loading" ? <Spinner /> : resource.status === "error" ? <div role="alert">
      <p>{t("qualityAudits.results.sectionFailed")}</p>
      <Button variant="secondary" onClick={() => setResource({ status: "loading" })}>{t("qualityAudits.results.retry")}</Button>
    </div> : <ReportValue value={resource.data} />)}
  </details>
}

export function QualityAuditReport({ projectId, auditId, qualityResults, onQualityResultsOpenChange }: {
  projectId: number, auditId: number, qualityResults: AuditReportSectionResource, onQualityResultsOpenChange: (open: boolean) => void,
}) {
  const { t } = useTranslation("projects")
  const [summary, setSummary] = useState<{ data: unknown } | null>(null)
  const handleExecutiveSummaryLoaded = useCallback((data: unknown) => setSummary({ data }), [])
  return <>
    {summary && <AuditFindingsSummary summary={summary.data} />}
    <section>
    <h3>{t("qualityAudits.report.title", { id: auditId })}</h3>
    <p className="label">{t("qualityAudits.report.originalNotice")}</p>
    <div className="quality-report">{auditReportSections.map(([key, titleKey]) => key === "quality_results"
      ? <QualityResultsSection key={`${auditId}-${key}`} resource={qualityResults} onOpenChange={onQualityResultsOpenChange} title={t(titleKey)} />
      : <ReportSection key={`${auditId}-${key}`} projectId={projectId} auditId={auditId} section={key} title={t(titleKey)} onExecutiveSummaryLoaded={handleExecutiveSummaryLoaded} />)}</div>
    </section>
  </>
}
