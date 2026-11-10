import { useContext, useCallback, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { AuditEvidenceNavigation, auditEvidenceLink } from "./auditEvidenceNavigation.ts"
import type { ParseKeys } from "i18next"
import { useTranslation } from "react-i18next"
import { Badge, Button, ChevronRightIcon, CodeIcon, Drawer, Pagination, PencilIcon } from "../../shared/ui-kit/index.ts"
import { formatNumber } from "../../shared/i18n/format.ts"
import { ArchitectureContextEvidenceViewer } from "./ArchitectureContextEvidenceViewer.tsx"
import { architectureContextConstraintLabelKeys } from "./architectureContextView.ts"
import type { ArchitectureContextCategorySource } from "./architectureContextView.ts"

type Finding = Record<string, unknown>
const severityOrder = ["critical", "high", "medium", "low", "info"]
function severityRank(finding: Finding) {
  const index = severityOrder.indexOf(typeof finding.severity === "string" ? finding.severity : "")
  return index < 0 ? severityOrder.length : index
}
const attributeLabels: Record<string, ParseKeys<"projects">> = {
  maintainability: "qualityAudits.findingsSummary.maintainability", security: "qualityAudits.findingsSummary.security",
  performance_efficiency: "qualityAudits.findingsSummary.performance_efficiency", functional_adequacy: "qualityAudits.findingsList.functionalAdequacy",
}
const severityLabels: Record<string, ParseKeys<"projects">> = {
  critical: "qualityAudits.findingsSummary.critical", high: "qualityAudits.findingsSummary.high", medium: "qualityAudits.findingsSummary.medium",
  low: "qualityAudits.findingsSummary.low", info: "qualityAudits.findingsSummary.info",
}
const subcharacteristicLabels: Record<string, ParseKeys<"projects">> = {
  modularity: "qualityAudits.configuration.maintainability.modularity",
  reusability: "qualityAudits.configuration.maintainability.reusability",
  analyzability: "qualityAudits.configuration.maintainability.analyzability",
  modifiability: "qualityAudits.configuration.maintainability.modifiability",
  testability: "qualityAudits.configuration.maintainability.testability",
}
const validationLabels: Record<string, ParseKeys<"projects">> = {
  verified: "qualityAudits.findingsList.verified", inconclusive: "qualityAudits.findingsList.inconclusive", discarded: "qualityAudits.findingsList.discarded", unreviewed: "qualityAudits.findingsList.unreviewed",
}

function isRecord(value: unknown): value is Finding {
  return value !== null && typeof value === "object" && !Array.isArray(value)
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0) : []
}

function cleanString(value: unknown): string {
  return typeof value === "string" ? value.trim() : ""
}

function lineNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : null
}

function fileName(filePath: string): string {
  const parts = filePath.split("/").filter((part) => part !== "")
  return parts.at(-1) ?? filePath
}

function rangeLabel(source: ArchitectureContextCategorySource): string {
  if (source.startLine === null) return ""
  return `L${source.startLine}–L${source.endLine ?? source.startLine}`
}

function severityTone(severity: string): "danger" | "warning" | "info" | "neutral" {
  if (severity === "critical") return "danger"
  if (severity === "high") return "warning"
  if (severity === "medium") return "warning"
  if (severity === "low" || severity === "info") return "info"
  return "neutral"
}

function constraintTone(value: string): "success" | "warning" | "info" | "neutral" {
  if (value === "prohibited") return "warning"
  if (value === "required") return "info"
  if (value === "allowed") return "success"
  return "neutral"
}

function FindingBadges({ finding }: { finding: Finding }) {
  const { t } = useTranslation("projects")
  const missing = t("qualityAudits.report.notRecorded")
  const attribute = typeof finding.quality_attribute === "string" ? finding.quality_attribute.trim() : ""
  const subcharacteristic = typeof finding.subcharacteristic === "string" && finding.subcharacteristic.trim()
    ? finding.subcharacteristic.trim() : typeof finding.analysis_type === "string" ? finding.analysis_type.trim() : ""
  const agents = [...new Set((Array.isArray(finding.source_refs) ? finding.source_refs : [])
    .filter(isRecord).filter((ref) => ref.record_type === "finding" && ref.record_id === finding.id)
    .flatMap((ref) => typeof ref.agent_id === "string" && ref.agent_id.trim() ? [ref.agent_id] : []))]
  return <div className="quality-audit-finding-badges">
      <Badge tone="info">{t("qualityAudits.findingsList.attribute")}: {attributeLabels[attribute]
        ? t(attributeLabels[attribute]) : attribute.replaceAll("_", " ") || missing}</Badge>
      <Badge tone="neutral">{t("qualityAudits.findingsList.subcharacteristic")}: {subcharacteristicLabels[subcharacteristic]
        ? t(subcharacteristicLabels[subcharacteristic]) : subcharacteristic.replaceAll("_", " ") || missing}</Badge>
      <Badge tone="neutral">{t("qualityAudits.findingsList.agent")}: {agents.join(", ") || missing}</Badge>
  </div>
}

export function FindingSeverity({ finding }: { finding: Finding }) {
  const { t } = useTranslation("projects")
  const severity = typeof finding.severity === "string" ? finding.severity : ""
  return <Badge tone={severityTone(severity)}>
    {t("qualityAudits.findingsList.severity")}: {severityLabels[severity] ? t(severityLabels[severity]) : severity || t("qualityAudits.report.notRecorded")}
  </Badge>
}

function FindingItem({ finding, onSelect }: { finding: Finding, onSelect: (finding: Finding) => void }) {
  const { t } = useTranslation("projects")
  const missing = t("qualityAudits.report.notRecorded")
  return <li className="quality-audit-finding">
    <div className="quality-audit-heading">
      <h5><button className="quality-audit-finding-select" type="button" aria-haspopup="dialog" onClick={() => onSelect(finding)}>
        {typeof finding.title === "string" && finding.title.trim() ? finding.title : missing}
      </button></h5>
      <FindingSeverity finding={finding} />
    </div>
    <FindingBadges finding={finding} />
    <p className="quality-audit-finding-description">{typeof finding.description === "string" && finding.description.trim() ? finding.description : missing}</p>
  </li>
}

interface InspectorEvidence extends ArchitectureContextCategorySource {
  subject: string
  statement: string
  constraint: string
  certainty: string
  category: string
  documentClaimId: string
}

function buildInspectorEvidence(finding: Finding): InspectorEvidence[] {
  const technical = isRecord(finding.technical_details) ? finding.technical_details : {}
  const documentary = Array.isArray(technical.documentary_references) ? technical.documentary_references.filter(isRecord) : []
  const out: InspectorEvidence[] = []
  for (const item of documentary) {
    const subject = cleanString(item.subject)
    const statement = cleanString(item.statement)
    const constraint = cleanString(item.constraint)
    const certainty = cleanString(item.certainty)
    const category = cleanString(item.category)
    const documentClaimId = cleanString(item.document_claim_id) || cleanString(item.id)
    const sectionPathsRecord = isRecord(item.section_paths) ? item.section_paths : {}
    const sectionPaths = Object.values(sectionPathsRecord).filter((value): value is string => typeof value === "string" && value.trim().length > 0).map((v) => v.trim())
    const quotes = Array.isArray(item.quotes) ? item.quotes.filter(isRecord) : []
    if (quotes.length > 0) {
      for (const quote of quotes) {
        const quotedPath = cleanString(quote.path) || (cleanString(quote.section_id) ? cleanString(sectionPathsRecord[cleanString(quote.section_id)]) : "") || sectionPaths[0] || ""
        const filePath = quotedPath || documentClaimId || ""
        if (!filePath) continue
        const startLine = lineNumber(quote.start_line)
        const endLine = lineNumber(quote.end_line)
        out.push({
          label: filePath,
          filePath,
          startLine,
          endLine,
          lines: startLine !== null ? `${startLine}–${endLine ?? startLine}` : "",
          quote: typeof quote.quote === "string" ? quote.quote : "",
          subject,
          statement,
          constraint,
          certainty,
          category,
          documentClaimId,
        })
      }
      continue
    }
    // No quotes: keep section paths navigable to the full document when possible.
    const paths = sectionPaths.length > 0 ? sectionPaths : (documentClaimId ? [documentClaimId] : [])
    for (const filePath of paths) {
      out.push({
        label: filePath,
        filePath,
        startLine: null,
        endLine: null,
        lines: "",
        quote: "",
        subject,
        statement,
        constraint,
        certainty,
        category,
        documentClaimId,
      })
    }
  }
  return out
}

type InspectorView = "inspector" | "evidence"

export function FindingDetails({ finding, renderDetails, onEvidenceNavigate, projectId = null, repositoryName = "" }: {
  finding: Finding, renderDetails: (finding: Finding) => ReactNode, onEvidenceNavigate?: () => void
  projectId?: number | null, repositoryName?: string
}) {
  const { t } = useTranslation("projects")
  const { t: tEvidence } = useTranslation("auditEvidence")
  const evidenceBasePath = useContext(AuditEvidenceNavigation)
  const [view, setView] = useState<InspectorView>("inspector")
  const [selectedEvidence, setSelectedEvidence] = useState<InspectorEvidence | null>(null)
  const [copied, setCopied] = useState(false)
  const [originalOpen, setOriginalOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const findingScrollTop = useRef(0)
  const missing = t("qualityAudits.report.notRecorded")
  const text = (value: unknown) => typeof value === "string" && value.trim() ? value : missing
  const agents = [...new Set((Array.isArray(finding.source_refs) ? finding.source_refs : [])
    .filter(isRecord).filter((ref) => ref.record_type === "finding" && ref.record_id === finding.id)
    .flatMap((ref) => typeof ref.agent_id === "string" && ref.agent_id.trim() ? [ref.agent_id] : []))]
  const components = strings(finding.components)
  const documentaryEvidence = useMemo(() => buildInspectorEvidence(finding), [finding])
  const evidenceIds = useMemo(() => [...new Set(strings(finding.evidence_ids))], [finding])
  const validation = typeof finding.verification_status === "string" ? finding.verification_status.trim() : ""

  // Restore the inspector scroll position when returning from the evidence viewer.
  useLayoutEffect(() => {
    if (view !== "inspector") return
    const scroller = containerRef.current?.closest<HTMLElement>(".ui-drawer-body")
    if (scroller) scroller.scrollTop = findingScrollTop.current
  }, [view])

  const openEvidence = useCallback((evidence: InspectorEvidence) => {
    findingScrollTop.current = containerRef.current?.closest<HTMLElement>(".ui-drawer-body")?.scrollTop ?? 0
    setSelectedEvidence(evidence)
    setView("evidence")
  }, [])

  const backToInspector = useCallback(() => {
    setSelectedEvidence(null)
    setView("inspector")
  }, [])

  const copyId = useCallback(async () => {
    const id = typeof finding.id === "string" ? finding.id : ""
    if (!id) return
    try {
      await navigator.clipboard?.writeText(id)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
    }
  }, [finding])

  if (view === "evidence" && selectedEvidence !== null) {
    return <div className="quality-audit-finding-detail quality-audit-finding-inspector" ref={containerRef}>
      <ArchitectureContextEvidenceViewer
        projectId={projectId}
        repositoryName={repositoryName}
        evidence={selectedEvidence}
        onBack={backToInspector}
      />
    </div>
  }

  const optionalTechnical: Array<{ label: string, value: string }> = []
  for (const [key, labelKey] of [
    ["kind", "Kind"],
    ["classification", "Classification"],
    ["disposition", "Disposition"],
    ["lifecycle", "Lifecycle"],
    ["original_validation_status", "Original validation status"],
    ["verification_rationale", "Verification rationale"],
  ] as const) {
    const value = cleanString(finding[key])
    if (value) optionalTechnical.push({ label: labelKey, value })
  }

  return <div className="quality-audit-finding-detail quality-audit-finding-inspector" ref={containerRef}>
    <div className="quality-audit-finding-inspector-badges">
      <FindingBadges finding={finding} />
    </div>

    <section className="quality-audit-finding-section" aria-label={t("qualityAudits.findingsList.whatsWrong")}>
      <h4 className="quality-audit-finding-section-title">{t("qualityAudits.findingsList.whatsWrong")}</h4>
      <p className="quality-audit-finding-section-text">{text(finding.description)}</p>
      <div className="quality-audit-finding-components">
        <span className="quality-audit-finding-label">{t("qualityAudits.findingsList.components")}</span>
        {components.length > 0 ? (
          <ul className="quality-audit-finding-component-list" aria-label={t("qualityAudits.findingsList.components")}>
            {components.map((component) => <li key={component}><code>{component}</code></li>)}
          </ul>
        ) : <span className="quality-audit-finding-muted">{t("qualityAudits.findingsList.noComponents")}</span>}
      </div>
    </section>

    <section className="quality-audit-finding-section" aria-label={t("qualityAudits.findingsList.impact")}>
      <h4 className="quality-audit-finding-section-title">{t("qualityAudits.findingsList.impact")}</h4>
      <p className="quality-audit-finding-section-text">{text(finding.impact)}</p>
    </section>

    <section className="quality-audit-finding-section quality-audit-finding-recommendation" aria-label={t("qualityAudits.findingsList.recommendedFix")}>
      <h4 className="quality-audit-finding-section-title"><PencilIcon size={14} /><span>{t("qualityAudits.findingsList.recommendedFix")}</span></h4>
      <p className="quality-audit-finding-section-text">{text(finding.recommendation)}</p>
    </section>

    <section className="quality-audit-finding-section" aria-label={t("qualityAudits.findingsList.evidenceReferences")}>
      <h4 className="quality-audit-finding-section-title">{t("qualityAudits.findingsList.evidenceReferences")}</h4>

      {documentaryEvidence.length > 0 ? (
        <ul className="quality-audit-finding-ref-list">
          {documentaryEvidence.map((evidence, index) => {
            const range = rangeLabel(evidence)
            const constraintLabelKey = evidence.constraint ? architectureContextConstraintLabelKeys[evidence.constraint] : undefined
            return <li key={`${evidence.filePath}-${evidence.startLine ?? ""}-${evidence.endLine ?? ""}-${index}`}>
              <button
                type="button"
                className="quality-audit-finding-ref-row"
                aria-label={range === "" ? fileName(evidence.filePath) : `${fileName(evidence.filePath)} ${range}`}
                onClick={() => openEvidence(evidence)}
              >
                <span className="quality-audit-finding-ref-icon"><CodeIcon size={14} /></span>
                <span className="quality-audit-finding-ref-main">
                  <span className="quality-audit-finding-ref-head">
                    <span className="quality-audit-finding-ref-name">{fileName(evidence.filePath)}</span>
                    {range !== "" && <span className="quality-audit-finding-ref-range">{range}</span>}
                    {evidence.constraint && evidence.constraint !== "unspecified" && (
                      <Badge tone={constraintTone(evidence.constraint)}>
                        {constraintLabelKey ? t(constraintLabelKey) : evidence.constraint.replaceAll("_", " ")}
                      </Badge>
                    )}
                  </span>
                  <span className="quality-audit-finding-ref-path mono">{evidence.filePath}</span>
                  {(evidence.subject || evidence.statement) && (
                    <span className="quality-audit-finding-ref-subject">
                      {evidence.subject}{evidence.statement ? `: ${evidence.statement}` : ""}
                    </span>
                  )}
                  {evidence.quote !== "" && <span className="quality-audit-finding-ref-excerpt">{evidence.quote}</span>}
                </span>
                <span className="quality-audit-finding-ref-chevron"><ChevronRightIcon size={14} /></span>
              </button>
            </li>
          })}
        </ul>
      ) : (
        <p className="quality-audit-finding-muted">{t("qualityAudits.findingsList.noDocumentaryReferences")}</p>
      )}

      <div className="quality-audit-finding-evidence-ids">
        <span className="quality-audit-finding-label">{tEvidence("findingEvidence")}</span>
        {evidenceIds.length > 0 ? (
          <ul className="quality-audit-finding-evidence-links">{evidenceIds.map((id) => <li key={id}>
            {evidenceBasePath ? <Link className="ui-button ui-button-secondary quality-audit-evidence-link"
              to={auditEvidenceLink(evidenceBasePath, id)} aria-label={tEvidence("openEvidence", { id })} title={id}
              onClick={(event) => { if (event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) onEvidenceNavigate?.() }}>
                <CodeIcon size={12} /><code>{id}</code>
              </Link>
              : <code>{id}</code>}
          </li>)}</ul>
        ) : <span className="quality-audit-finding-muted">{evidenceIds.length > 0 ? missing : tEvidence("findingNoEvidence")}</span>}
      </div>
    </section>

    <section className="quality-audit-finding-section quality-audit-finding-technical" aria-label={t("qualityAudits.findingsList.technicalMetadata")}>
      <details>
        <summary>{t("qualityAudits.findingsList.technicalMetadata")}</summary>
        <dl className="quality-audit-finding-technical-dl">
          <div>
            <dt>{t("qualityAudits.findingsList.identifier")}</dt>
            <dd className="quality-audit-finding-id-row">
              <code>{text(finding.id)}</code>
              {typeof finding.id === "string" && finding.id.trim() !== "" && (
                <Button variant="secondary" onClick={() => void copyId()} aria-label={t("qualityAudits.findingsList.copyId")}>
                  {copied ? t("qualityAudits.findingsList.copied") : t("qualityAudits.findingsList.copyId")}
                </Button>
              )}
            </dd>
          </div>
          <div><dt>{t("qualityAudits.findingsList.agent")}</dt><dd>{agents.join(", ") || missing}</dd></div>
          <div><dt>{t("qualityAudits.findingsList.validation")}</dt><dd>{validationLabels[validation] ? t(validationLabels[validation]) : validation.replaceAll("_", " ") || missing}</dd></div>
          {optionalTechnical.map((item) => (
            <div key={item.label}><dt>{item.label}</dt><dd>{item.value}</dd></div>
          ))}
        </dl>
      </details>
    </section>

    <details className="quality-audit-finding-original" onToggle={(event) => setOriginalOpen(event.currentTarget.open)}>
      <summary>{t("qualityAudits.findingsList.original")}</summary>
      {originalOpen && <div className="quality-report">{renderDetails(finding)}</div>}
    </details>
  </div>
}

function FindingGroup({ attribute, findings, onSelect }: { attribute: string, findings: Finding[], onSelect: (finding: Finding) => void }) {
  const { t } = useTranslation("projects")
  return <section className="quality-audit-finding-group">
    <h4>{attributeLabels[attribute] ? t(attributeLabels[attribute]) : attribute.replaceAll("_", " ") || t("qualityAudits.report.notRecorded")} ({formatNumber(findings.length)})</h4>
    <ul className="quality-audit-findings-list">{findings.map((finding, index) =>
      <FindingItem key={typeof finding.id === "string" ? `${finding.id}-${index}` : index} finding={finding} onSelect={onSelect} />)}</ul>
  </section>
}

export function QualityAuditFindings({ findings, renderDetails, projectId = null, repositoryName = "" }: {
  findings: unknown, renderDetails: (finding: Finding) => ReactNode, projectId?: number | null, repositoryName?: string
}) {
  const { t } = useTranslation("projects")
  const [selected, setSelected] = useState<Finding | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [pagination, setPagination] = useState({ source: findings, page: 1 })
  const [pageSize, setPageSize] = useState(10)
  const [sortDirection, setSortDirection] = useState<"descending" | "ascending">("descending")
  const ordered = useMemo(() => Array.isArray(findings)
    ? findings.filter(isRecord).sort((left, right) => {
      const leftRank = severityRank(left)
      const rightRank = severityRank(right)
      // Unknown severities stay at the end in either direction.
      if (leftRank === severityOrder.length || rightRank === severityOrder.length) return leftRank - rightRank
      return (leftRank - rightRank) * (sortDirection === "descending" ? 1 : -1)
    }) : [], [findings, sortDirection])
  const pageCount = Math.max(1, Math.ceil(ordered.length / pageSize))
  const page = pagination.source === findings ? Math.min(pagination.page, pageCount) : 1
  if (!Array.isArray(findings)) return <p className="label">{t("qualityAudits.report.notRecorded")}</p>
  if (findings.length === 0) return <p className="label" role="status">{t("qualityAudits.results.noFindings")}</p>
  // Keep adjacent attributes together without changing the selected severity order.
  const groups: Array<{ attribute: string, findings: Finding[] }> = []
  for (const finding of ordered.slice((page - 1) * pageSize, page * pageSize)) {
    const attribute = typeof finding.quality_attribute === "string" ? finding.quality_attribute : ""
    const previous = groups.at(-1)
    if (previous?.attribute === attribute) previous.findings.push(finding)
    else groups.push({ attribute, findings: [finding] })
  }
  return <section aria-label={t("qualityAudits.findingsList.title")}>
    <h3>{t("qualityAudits.findingsList.title")}</h3>
    <div className="quality-audit-findings-controls">
      <label>{t("qualityAudits.findingsList.perPage")}
        <select value={pageSize} onChange={(event) => {
          setPageSize(Number(event.currentTarget.value))
          setPagination({ source: findings, page: 1 })
        }}>
          {[10, 20, 50].map((size) => <option key={size} value={size}>{formatNumber(size)}</option>)}
        </select>
      </label>
      <label>{t("qualityAudits.findingsList.sortOrder")}
        <select value={sortDirection} onChange={(event) => {
          setSortDirection(event.currentTarget.value === "ascending" ? "ascending" : "descending")
          setPagination({ source: findings, page: 1 })
        }}>
          <option value="descending">{t("qualityAudits.findingsList.severityDescending")}</option>
          <option value="ascending">{t("qualityAudits.findingsList.severityAscending")}</option>
        </select>
      </label>
    </div>
    <p className="label" role="status">{t("qualityAudits.findingsList.pageRange", {
      start: formatNumber(ordered.length === 0 ? 0 : (page - 1) * pageSize + 1),
      end: formatNumber(Math.min(page * pageSize, ordered.length)), total: formatNumber(ordered.length),
      order: t(sortDirection === "descending" ? "qualityAudits.findingsList.severityDescending" : "qualityAudits.findingsList.severityAscending"),
    })}</p>
    {groups.map(({ attribute, findings: items }, index) => <FindingGroup key={`${page}-${attribute}-${index}`} attribute={attribute} findings={items} onSelect={(finding) => {
      setSelected(finding)
      setDrawerOpen(true)
    }} />)}
    <Pagination page={page} pageCount={pageCount} onChange={(next) => setPagination({ source: findings, page: next })} />
    <Drawer open={drawerOpen} title={typeof selected?.title === "string" && selected.title.trim() ? selected.title : t("qualityAudits.report.notRecorded")}
      size="inspector" headerExtra={selected ? <FindingSeverity finding={selected} /> : undefined}
      onClose={() => setDrawerOpen(false)}>
      {selected && <FindingDetails key={typeof selected.id === "string" ? selected.id : undefined} finding={selected} renderDetails={renderDetails}
        projectId={projectId} repositoryName={repositoryName}
        onEvidenceNavigate={() => setDrawerOpen(false)} />}
    </Drawer>
  </section>
}
