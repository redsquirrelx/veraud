import type { AgentSettingsView } from "../agent-settings/agent-settings.service.js"

export interface AuditParticipant { id: string, name: string }
export interface AuditAttributeScope {
  id: string
  requiredAgents: AuditParticipant[]
  subcharacteristics: { id: string, name: string, investigators: AuditParticipant[] }[]
  techniques: AuditParticipant[]
  investigators: AuditParticipant[]
}
export interface AuditRunConfiguration {
  version: 1
  branch: string
  commitHash: string
  attributes: string[]
  scopes: AuditAttributeScope[]
}

/** Immutable selection metadata only: never copy credentials or transport options. */
export function auditRunConfiguration(agents: AgentSettingsView[], branch: string, commitHash: string,
  attributes: string[], selection?: Record<string, string[]>): AuditRunConfiguration {
  const available = agents.filter((agent) => agent.availability === "available")
  const participant = (agent: AgentSettingsView): AuditParticipant => ({ id: agent.agentType, name: agent.name })
  const children = (agent?: AgentSettingsView) => available.filter((child) => agent?.childAgentTypes.includes(child.agentType))
  return { version: 1, branch, commitHash, attributes: [...attributes], scopes: attributes.map((id) => {
    const root = available.find((agent) => agent.agentType === (id === "maintainability" ? "maintainability_manager" : id))
    const scope: AuditAttributeScope = { id, requiredAgents: root ? [participant(root)] : [], subcharacteristics: [], techniques: [], investigators: [] }
    if (id === "maintainability") {
      const coordinators = children(root).filter((agent) => agent.role === "coordinator" && (selection === undefined || agent.agentType in selection))
      scope.requiredAgents.push(...coordinators.map(participant))
      scope.subcharacteristics = coordinators.map((agent) => ({ id: agent.agentType, name: agent.name,
        investigators: children(agent).filter((child) => child.role === "investigator"
          && (selection === undefined || selection[agent.agentType]?.includes(child.agentType))).map(participant) }))
    } else if (id === "security") scope.techniques = children(root).map(participant)
    else if (root) scope.investigators = [participant(root)]
    return scope
  }) }
}
