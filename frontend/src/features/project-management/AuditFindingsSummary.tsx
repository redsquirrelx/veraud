import { useTranslation } from "react-i18next"
import { formatNumber } from "../../shared/i18n/format.ts"

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : null
}

const attributes = ["maintainability", "security", "performance_efficiency"] as const
const severities = ["critical", "high", "medium", "low", "info"] as const

export function AuditFindingsSummary({ summary }: { summary: unknown }) {
  const { t } = useTranslation("projects")
  const findings = record(record(summary)?.findings)
  const byAttribute = record(findings?.by_attribute)
  const bySeverity = record(findings?.by_severity)
  const display = (value: number | null) => value === null ? t("qualityAudits.report.notRecorded") : formatNumber(value)
  const entryCount = (values: Record<string, unknown> | null, key: string) => values === null ? null
    : Object.hasOwn(values, key) ? count(values[key]) : 0
  const otherCount = (values: Record<string, unknown> | null, known: readonly string[]) =>
    Object.entries(values ?? {}).reduce((sum, [key, value]) => sum + (known.includes(key) ? 0 : count(value) ?? 0), 0)
  const otherAttributes = otherCount(byAttribute, attributes)
  const otherSeverities = otherCount(bySeverity, severities)

  return <section className="quality-audit-findings-summary" aria-label={t("qualityAudits.findingsSummary.title")}>
    <h3>{t("qualityAudits.findingsSummary.title")}</h3>
    {count(findings?.total) === 0 && <p role="status">{t("qualityAudits.results.noFindings")}</p>}
    <dl className="quality-audit-findings-total"><div>
      <dt>{t("qualityAudits.findingsSummary.total")}</dt><dd>{display(count(findings?.total))}</dd>
    </div></dl>
    <div className="quality-audit-findings-groups">
      <section aria-label={t("qualityAudits.findingsSummary.byAttribute")}>
        <h4>{t("qualityAudits.findingsSummary.byAttribute")}</h4>
        <dl>{attributes.map((attribute) => <div key={attribute}>
          <dt>{t(`qualityAudits.findingsSummary.${attribute}`)}</dt>
          <dd>{display(entryCount(byAttribute, attribute))}</dd>
        </div>)}
          {otherAttributes > 0 && <div><dt>{t("qualityAudits.findingsSummary.otherAttributes")}</dt><dd>{display(otherAttributes)}</dd></div>}
        </dl>
      </section>
      <section aria-label={t("qualityAudits.findingsSummary.bySeverity")}>
        <h4>{t("qualityAudits.findingsSummary.bySeverity")}</h4>
        <dl>{severities.map((severity) => <div key={severity}>
          <dt>{t(`qualityAudits.findingsSummary.${severity}`)}</dt><dd>{display(entryCount(bySeverity, severity))}</dd>
        </div>)}
          {otherSeverities > 0 && <div><dt>{t("qualityAudits.findingsSummary.otherSeverities")}</dt><dd>{display(otherSeverities)}</dd></div>}
        </dl>
      </section>
    </div>
    <p className="label">{t("qualityAudits.findingsSummary.notice")}</p>
  </section>
}
