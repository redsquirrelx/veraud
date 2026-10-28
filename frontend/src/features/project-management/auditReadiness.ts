import type { AgentSettings } from "../../infrastructure/http-client/httpClient.ts"
import { isAvailable } from "./auditAgentCatalog.ts"

export type AuditReadinessIssue = { attribute: string, reason: "unavailable" | "unconfigured" | "verificationFailed" }

/** Mirror the model owners checked by the backend; a fresh access check still happens on start. */
export function auditReadiness(agents: AgentSettings[], attributes: string[]): AuditReadinessIssue[] {
  return attributes.flatMap((attribute): AuditReadinessIssue[] => {
    const id = attribute === "maintainability" ? "maintainability_manager" : attribute
    const root = agents.find((agent) => agent.agentType === id)
    if (!root || !isAvailable(root)) return [{ attribute, reason: "unavailable" }]
    if (root.requiresModel === false) return []
    const owner = agents.find((agent) => agent.agentType === root.modelConfigurationAgentType) ?? root
    if (!owner.configured) return [{ attribute, reason: "unconfigured" }]
    if (owner.verification?.status === "failed") return [{ attribute, reason: "verificationFailed" }]
    return []
  })
}
