import type { AgentSettings } from "../../infrastructure/http-client/httpClient.ts"
import { availableSubcharacteristics, investigatorsFor, isAvailable } from "./auditAgentCatalog.ts"
import type { AuditRunConfiguration } from "./qualityAuditApi.ts"

export interface ReusedAuditSelection {
  maintainability: Record<string, string[]>
  security: boolean
  functionalAdequacy: boolean
  adjusted: boolean
}

/** Copy selections only; never restore historical revisions, models or operating options. */
export function reuseAuditSelection(configuration: AuditRunConfiguration, agents: AgentSettings[]): ReusedAuditSelection {
  const result: ReusedAuditSelection = { maintainability: {}, security: false, functionalAdequacy: false, adjusted: false }
  const dimensions = availableSubcharacteristics(agents)
  for (const attribute of configuration.attributes) {
    const scope = configuration.scopes.find((scope) => scope.id === attribute)
    if (!scope) { result.adjusted = true; continue }
    if (attribute === "maintainability") {
      for (const child of scope.subcharacteristics) {
        const dimension = dimensions.find((id) => id === child.id)
        if (!dimension) { result.adjusted = true; continue }
        const available = investigatorsFor(agents, dimension).filter(isAvailable).map((agent) => agent.agentType)
        const enabled = child.investigators.filter((agent) => available.includes(agent.id)).map((agent) => agent.id)
        if (enabled.length) result.maintainability[dimension] = enabled
        if (!enabled.length || enabled.length !== child.investigators.length) result.adjusted = true
      }
      if (!Object.keys(result.maintainability).length) result.adjusted = true
    } else if (attribute === "security" || attribute === "functional_adequacy") {
      const root = agents.find((agent) => agent.agentType === attribute && isAvailable(agent))
      if (!root) { result.adjusted = true; continue }
      if (attribute === "security") {
        const techniques = agents.filter((agent) => isAvailable(agent)
          && (root.childAgentTypes?.includes(agent.agentType) || agent.parentAgentTypes?.includes(root.agentType)))
          .map((agent) => agent.agentType)
        // Security has no per-technique overrides yet. Do not silently enable a different set.
        const matches = techniques.length === scope.techniques.length && scope.techniques.every((agent) => techniques.includes(agent.id))
        result.security = matches
        if (!matches) result.adjusted = true
      } else result.functionalAdequacy = true
    } else result.adjusted = true
  }
  return result
}
