import { useEffect, useState } from "react"
import { listAgentSettings, type AgentSettings } from "../../infrastructure/http-client/httpClient.ts"

export const subcharacteristics = ["modularity", "reusability", "analyzability", "modifiability", "testability"] as const
export type Subcharacteristic = typeof subcharacteristics[number]

export function isAvailable(agent: AgentSettings) {
  return agent.availability === undefined || agent.availability === "available"
}

export function investigatorsFor(agents: AgentSettings[], id: Subcharacteristic) {
  const children = agents.find((agent) => agent.agentType === id)?.childAgentTypes ?? []
  return agents.filter((agent) => agent.role === "investigator"
    && (children.includes(agent.agentType) || agent.parentAgentTypes?.includes(id)))
}

export function availableSubcharacteristics(agents: AgentSettings[]) {
  return subcharacteristics.filter((id) => agents.some((agent) => agent.agentType === id
    && agent.qualityAttributes.includes("maintainability") && isAvailable(agent)))
}

export function useAuditAgentCatalog(enabled = true) {
  const [agents, setAgents] = useState<AgentSettings[]>([])
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    listAgentSettings(controller.signal).then((agents) => {
      if (controller.signal.aborted) return
      setAgents(agents)
      setLoading(false)
    }, () => {
      if (controller.signal.aborted) return
      setFailed(true)
      setLoading(false)
    })
    return () => controller.abort()
  }, [enabled, attempt])

  return { agents, loading, failed, retry: () => { setFailed(false); setLoading(true); setAttempt((value) => value + 1) } }
}

export type AuditAgentCatalog = ReturnType<typeof useAuditAgentCatalog>
