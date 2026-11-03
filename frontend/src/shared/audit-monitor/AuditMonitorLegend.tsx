import { useTranslation } from "react-i18next"
import type projects from "../i18n/locales/en/projects.json"
import { stateLabelKey } from "./auditStatus.ts"
import { graphPhases, useMonitorLabels } from "./monitorLabels.ts"

export function AuditMonitorLegend() {
  const { t } = useTranslation("projects")
  const labels = useMonitorLabels()
  return <div className="audit-monitor-legend">
    <div role="group" aria-label={labels.states}>
      <span className="label">{labels.states}</span>
      <ul>{(["running", "waiting", "completed", "partial", "failed"] as const).map((state) =>
        <li key={state} data-state={state}><span className="audit-legend-state" aria-hidden="true" />{t(stateLabelKey(state))}</li>)}</ul>
    </div>
    <div role="group" aria-label={labels.phases}>
      <span className="label">{labels.phases}</span>
      <ul>{graphPhases.map((phase) => <li key={phase}>
        <span className="audit-agent-phase" data-phase={phase} aria-hidden="true" />
        {t(`auditStatus.phases.${phase}` as `auditStatus.phases.${keyof typeof projects.auditStatus.phases}`,
          { defaultValue: phase.replaceAll("_", " ") })}
      </li>)}</ul>
    </div>
  </div>
}
