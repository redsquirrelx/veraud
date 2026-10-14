import { createHash } from "node:crypto"
import type { AgentConfiguration } from "./agent-settings.repository.js"

export interface AgentVerification {
  status: "not_verified" | "verified" | "failed"
  checkedAt: string | null
  message: string | null
}

export interface AgentRunConfig {
  model: { provider: string, name: string, temperature: number | null, max_tokens: number | null }
  api_key: string
}

export interface PreparedAgentConfiguration {
  agentType: string
  fingerprint: string
  snapshot: AgentConfiguration
  transport: AgentRunConfig
}

export interface ModelAccessVerifier {
  verify(config: AgentRunConfig): Promise<void>
}

export class AgentConfigurationError extends Error {
  constructor(readonly agents: Array<{ agentType: string, reason: string }>) {
    super(`Agents require attention: ${agents.map((agent) => `${agent.agentType} ΓÇö ${agent.reason}`).join("; ")}`)
  }
}

/** Revision changes invalidate access checks without reading keys in list queries. */
export function configurationFingerprint(model: { id: number, revision: number, name: string, aiProviderId: number }, credential: { id: number, revision: number, aiProviderId: number }, temperature: number | null, maxTokens: number | null, tokenBudget: number | null = null, absoluteTokenLimit: number | null = null): string {
  const values = [model.id, model.revision, model.name, model.aiProviderId, credential.id, credential.revision, credential.aiProviderId, temperature, maxTokens]
  // Preserve access verification fingerprints for unchanged pre-migration settings.
  if (tokenBudget !== null || absoluteTokenLimit !== null) values.push(tokenBudget, absoluteTokenLimit)
  return createHash("sha256").update(JSON.stringify(values)).digest("hex")
}
