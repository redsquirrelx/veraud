import type { ParseKeys } from "i18next"
import { useTranslation } from "react-i18next"
import type { AgentSettings } from "../../infrastructure/http-client/httpClient.ts"
import { Badge, Button, Spinner } from "../../shared/ui-kit/index.ts"
import { availableSubcharacteristics, investigatorsFor, isAvailable, type AuditAgentCatalog } from "./auditAgentCatalog.ts"

const titles: Record<string, ParseKeys<"projects">> = {
  architecture_boundary: "qualityAudits.summary.titles.architectureBoundary",
  responsibility: "qualityAudits.summary.titles.responsibility",
  dependency_impact: "qualityAudits.summary.titles.dependencyImpact",
  abstraction: "qualityAudits.summary.titles.abstraction",
  reuse_opportunity: "qualityAudits.summary.titles.reuseOpportunity",
  component_adaptability: "qualityAudits.summary.titles.componentAdaptability",
  sast_scanner: "qualityAudits.summary.titles.sast",
  secret_scanner: "qualityAudits.summary.titles.secrets",
  sca_dependency: "qualityAudits.summary.titles.dependencies",
  knowledge_enrichment: "qualityAudits.summary.titles.enrichment",
  remediation_synthesizer: "qualityAudits.summary.titles.remediation",
  patch_validator: "qualityAudits.summary.titles.validation",
  security_verifier: "qualityAudits.summary.titles.verification",
  functional_adequacy: "qualityAudits.summary.titles.functional",
}

/** Compact read-only projection of the same catalog and scope used by the drawer. */
export function AuditAttributeSummary({ attribute, catalog, selection }: {
  attribute: string, catalog: AuditAgentCatalog, selection?: Record<string, string[]>,
}) {
  const { t } = useTranslation("projects")
  const { agents, loading, failed, retry } = catalog
  if (loading) return <span className="quality-attribute-summary-loading"><Spinner size={12} /></span>
  if (failed) return <div className="quality-attribute-summary-error">
    <span className="label">{t("qualityAudits.summary.unavailable")}</span>
    <Button variant="secondary" onClick={retry}>{t("qualityAudits.configuration.maintainability.retry")}</Button>
  </div>

  function chips(members: AgentSettings[]) {
    return <ul className="quality-attribute-investigator-chips">{members.map((agent) => <li key={agent.agentType}>
      <Badge tone="neutral">{titles[agent.agentType] ? t(titles[agent.agentType]) : agent.name ?? agent.agentType}</Badge>
    </li>)}</ul>
  }

  if (attribute === "maintainability") {
    const dimensions = availableSubcharacteristics(agents).filter((id) => selection === undefined || id in selection)
    return dimensions.length ? <ul className="quality-attribute-summary-tree">{dimensions.map((id) => <li key={id}>
      <h4>{t(`qualityAudits.configuration.maintainability.${id}`)}</h4>
      {chips(investigatorsFor(agents, id).filter((agent) => isAvailable(agent)
        && (selection === undefined || selection[id]?.includes(agent.agentType))))}
    </li>)}</ul> : <span className="label">—</span>
  }

  const root = agents.find((agent) => agent.agentType === attribute)
  const children = agents.filter((agent) => isAvailable(agent)
    && (root?.childAgentTypes?.includes(agent.agentType) || agent.parentAgentTypes?.includes(attribute)))
  const members = children.length ? children : root && isAvailable(root) ? [root] : []
  return members.length ? chips(members) : <span className="label">—</span>
}
