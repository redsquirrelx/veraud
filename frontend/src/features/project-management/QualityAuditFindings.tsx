import { useContext, useMemo, useState, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { AuditEvidenceNavigation, auditEvidenceLink } from "./auditEvidenceNavigation.ts"
import type { ParseKeys } from "i18next"
import { useTranslation } from "react-i18next"
import { Badge, CodeIcon, Drawer, Pagination } from "../../shared/ui-kit/index.ts"
import { formatNumber } from "../../shared/i18n/format.ts"

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
  verified: "qualityAudits.findingsList.verified", inconclusive: "qualityAudits.findingsList.inconclusive", discarded: "qualityAudits.findingsList.discarded",
}

function isRecord(value: unknown): value is Finding {
  return value !== null && typeof value === "object" && !Array.isArray(value)
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0) : []
}

function FindingBadges({ finding }: { finding: Finding }) {
  const { t } = useTranslation("projects")
  const missing = t("qualityAudits.report.notRecorded")
  const attribute = typeof finding.quality_attribute === "string" ? finding.quality_attribute.trim() : ""
  const subcharacteristic = typeof finding.subcharacteristic === "string" && finding.subcharacteristic.trim()
    ? finding.subcharacteristic.trim() : typeof finding.analysis_type === "string" ? finding.analysis_type.trim() : ""
  const validation = typeof finding.verification_status === "string" ? finding.verification_status.trim() : ""
  return <div className="quality-audit-finding-badges">
      <Badge tone="info">{t("qualityAudits.findingsList.attribute")}: {attributeLabels[attribute]
        ? t(attributeLabels[attribute]) : attribute.replaceAll("_", " ") || missing}</Badge>
      <Badge tone="neutral">{t("qualityAudits.findingsList.subcharacteristic")}: {subcharacteristicLabels[subcharacteristic]
        ? t(subcharacteristicLabels[subcharacteristic]) : subcharacteristic.replaceAll("_", " ") || missing}</Badge>
      <Badge tone={validation === "verified" ? "success" : validation === "inconclusive" ? "warning" : "neutral"}>
        {t("qualityAudits.findingsList.validation")}: {validationLabels[validation] ? t(validationLabels[validation]) : validation.replaceAll("_", " ") || missing}
      </Badge>
  </div>
}

function FindingSeverity({ finding }: { finding: Finding }) {
  const { t } = useTranslation("projects")
  const severity = typeof finding.severity === "string" ? finding.severity : ""
  return <Badge tone={severity === "critical" || severity === "high" ? "warning" : "info"}>
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

export function FindingDetails({ finding, renderDetails, onEvidenceNavigate }: {
  finding: Finding, renderDetails: (finding: Finding) => ReactNode, onEvidenceNavigate?: () => void
}) {
  const { t } = useTranslation("projects")
  const { t: tEvidence } = useTranslation("auditEvidence")
  const evidenceBasePath = useContext(AuditEvidenceNavigation)
  const [originalOpen, setOriginalOpen] = useState(false)
  const missing = t("qualityAudits.report.notRecorded")
  const text = (value: unknown) => typeof value === "string" && value.trim() ? value : missing
  const agents = [...new Set((Array.isArray(finding.source_refs) ? finding.source_refs : [])
    .filter(isRecord).filter((ref) => ref.record_type === "finding" && ref.record_id === finding.id)
    .flatMap((ref) => typeof ref.agent_id === "string" && ref.agent_id.trim() ? [ref.agent_id] : []))]
  return <div className="quality-audit-finding-detail">
    <FindingSeverity finding={finding} />
    <FindingBadges finding={finding} />
    <dl>
      <div><dt>{t("qualityAudits.findingsList.identifier")}</dt><dd><code>{text(finding.id)}</code></dd></div>
      <div><dt>{t("qualityAudits.findingsList.description")}</dt><dd>{text(finding.description)}</dd></div>
      <div><dt>{t("qualityAudits.findingsList.impact")}</dt><dd>{text(finding.impact)}</dd></div>
      <div><dt>{t("qualityAudits.findingsList.recommendation")}</dt><dd>{text(finding.recommendation)}</dd></div>
      <div><dt>{t("qualityAudits.findingsList.components")}</dt><dd>{strings(finding.components).join(", ") || missing}</dd></div>
      <div><dt>{t("qualityAudits.findingsList.agent")}</dt><dd>{agents.join(", ") || missing}</dd></div>
      <div><dt>{tEvidence("findingEvidence")}</dt><dd>
        {Array.isArray(finding.evidence_ids) ? strings(finding.evidence_ids).length > 0
          ? <ul className="quality-audit-finding-evidence-links">{[...new Set(strings(finding.evidence_ids))].map((id) => <li key={id}>
            {evidenceBasePath ? <Link className="ui-button ui-button-secondary quality-audit-evidence-link"
              to={auditEvidenceLink(evidenceBasePath, id)} aria-label={tEvidence("openEvidence", { id })} title={id}
              onClick={(event) => { if (event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) onEvidenceNavigate?.() }}>
                <CodeIcon size={12} /><code>{id}</code>
              </Link>
              : <code>{id}</code>}
          </li>)}</ul> : tEvidence("findingNoEvidence") : missing}
      </dd></div>
    </dl>
    <details onToggle={(event) => setOriginalOpen(event.currentTarget.open)}>
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

export function QualityAuditFindings({ findings, renderDetails }: { findings: unknown, renderDetails: (finding: Finding) => ReactNode }) {
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
      onClose={() => setDrawerOpen(false)}>
      {selected && <FindingDetails key={typeof selected.id === "string" ? selected.id : undefined} finding={selected} renderDetails={renderDetails}
        onEvidenceNavigate={() => setDrawerOpen(false)} />}
    </Drawer>
  </section>
}
