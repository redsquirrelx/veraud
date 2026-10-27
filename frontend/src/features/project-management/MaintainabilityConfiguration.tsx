import { useState } from "react"
import { useTranslation } from "react-i18next"
import type { ParseKeys } from "i18next"
import { Badge, Button, Checkbox } from "../../shared/ui-kit/index.ts"
import { availableSubcharacteristics, investigatorsFor, isAvailable, subcharacteristics, useAuditAgentCatalog, type AuditAgentCatalog } from "./auditAgentCatalog.ts"

const investigatorDescriptions: Record<string, ParseKeys<"projects">> = {
  architecture_boundary: "qualityAudits.configuration.investigators.architectureBoundary",
  responsibility: "qualityAudits.configuration.investigators.responsibility",
  dependency_impact: "qualityAudits.configuration.investigators.dependencyImpact",
  abstraction: "qualityAudits.configuration.investigators.abstraction",
  reuse_opportunity: "qualityAudits.configuration.investigators.reuseOpportunity",
  component_adaptability: "qualityAudits.configuration.investigators.componentAdaptability",
}

/** Select the investigator scope; managers and coordinators are implicit dependencies. */
export function MaintainabilityConfiguration(props: {
  value?: Record<string, string[]>, onChange?: (selection: Record<string, string[]>) => void,
  catalog?: AuditAgentCatalog,
}) {
  const { value, onChange } = props
  const { t } = useTranslation("projects")
  const [localSelection, setLocalSelection] = useState<Record<string, string[]> | undefined>()
  const [retained, setRetained] = useState<Record<string, string[]>>({})
  const localCatalog = useAuditAgentCatalog(props.catalog === undefined)
  const { agents, loading, failed, retry } = props.catalog ?? localCatalog
  const available = availableSubcharacteristics(agents)

  // An explicitly supplied undefined value resets a controlled form to server defaults.
  const selection = value ?? ("value" in props ? undefined : localSelection) ?? Object.fromEntries(available.map((id) =>
    [id, investigatorsFor(agents, id).filter(isAvailable).map((agent) => agent.agentType)]))
  const selected = Object.keys(selection)
  function update(selection: Record<string, string[]>) {
    setLocalSelection(selection)
    onChange?.(selection)
  }
  const partial = !loading && !failed && available.some((id) =>
    !selected.includes(id) || investigatorsFor(agents, id).some((agent) =>
      isAvailable(agent) && !(selection[id] ?? []).includes(agent.agentType)))

  return <fieldset className="quality-audit-subcharacteristics" aria-busy={loading}>
    <legend>{t("qualityAudits.configuration.maintainability.legend")}</legend>
    {partial && <p className="quality-audit-partial-notice" role="status">{t("qualityAudits.configuration.investigators.partialNotice")}</p>}
    {loading && <p className="label" role="status">{t("qualityAudits.configuration.maintainability.loading")}</p>}
    {failed && <div role="alert">
      <p>{t("qualityAudits.configuration.maintainability.loadFailed")}</p>
      <Button variant="secondary" onClick={retry}>{t("qualityAudits.configuration.maintainability.retry")}</Button>
    </div>}
    {subcharacteristics.map((id) => {
      const enabled = !loading && !failed && available.includes(id)
      const investigators = investigatorsFor(agents, id)
      const dimensionPartial = enabled && selected.includes(id)
        && investigators.some((agent) => isAvailable(agent) && !(selection[id] ?? []).includes(agent.agentType))
      return <div key={id} className="quality-audit-subcharacteristic">
      <div className="quality-audit-subcharacteristic-heading">
      <Checkbox
        label={t(`qualityAudits.configuration.maintainability.${id}`)}
        checked={enabled && selected.includes(id)}
        disabled={!enabled}
        description={loading || failed ? undefined : t(enabled
          ? "qualityAudits.configuration.maintainability.available"
          : "qualityAudits.configuration.maintainability.unavailable")}
        onChange={(checked) => {
          const next = { ...selection }
          if (checked) next[id] = retained[id] ?? investigatorsFor(agents, id).filter(isAvailable).map((agent) => agent.agentType)
          else { setRetained((current) => ({ ...current, [id]: selection[id] ?? [] })); delete next[id] }
          update(next)
        }}
      />
      {dimensionPartial && <Badge tone="warning">{t("qualityAudits.evaluation.partial")}</Badge>}
      </div>
      <details className="quality-audit-investigators">
        <summary>{t("qualityAudits.configuration.investigators.view")}</summary>
        <div className="quality-audit-investigator-list">
          {investigators.length === 0 && <p className="label">{t(loading
            ? "qualityAudits.configuration.maintainability.loading"
            : failed ? "qualityAudits.configuration.maintainability.loadFailed"
              : "qualityAudits.configuration.investigators.empty")}</p>}
          {investigators.map((agent) => <div key={agent.agentType}>
            <Checkbox label={agent.name ?? agent.agentType}
              checked={enabled && selected.includes(id) && (selection[id] ?? []).includes(agent.agentType)}
              disabled={!enabled || !selected.includes(id) || !isAvailable(agent)}
              description={t(investigatorDescriptions[agent.agentType] ?? "qualityAudits.configuration.investigators.noDescription")}
              onChange={(checked) => {
                const next = { ...selection }
                const investigators = checked ? [...(selection[id] ?? []), agent.agentType]
                  : (selection[id] ?? []).filter((value) => value !== agent.agentType)
                if (investigators.length) next[id] = investigators
                else {
                  delete next[id]
                  setRetained((current) => {
                    const next = { ...current }
                    delete next[id]
                    return next
                  })
                }
                update(next)
              }}
            />
            {!isAvailable(agent) && <p className="label">{t("qualityAudits.configuration.maintainability.unavailable")}</p>}
          </div>)}
        </div>
      </details>
      </div>
    })}
  </fieldset>
}
