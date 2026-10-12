import { BACKEND_AGENT_TYPES } from "./agent-types.js"
import type { AgentConfiguration, AgentSettingsStore, AgentExecutionOptions } from "./agent-settings.repository.js"
import { UnknownAgentTypeError } from "./agent-settings.errors.js"
import { AgentConfigurationError, type AgentVerification, type ModelAccessVerifier, type PreparedAgentConfiguration } from "./agent-configuration.js"

export interface AgentSettingsView {
  agentType: string
  configured: boolean
  configuration: AgentConfiguration | null
  verification: AgentVerification
}

export class AgentSettingsService {
  constructor(private settings: AgentSettingsStore, private verifier: ModelAccessVerifier) {}

  async verify(agentType: string): Promise<AgentSettingsView> {
    await this.check(agentType)
    return (await this.list()).find((agent) => agent.agentType === agentType)!
  }

  private async check(agentType: string): Promise<{ prepared: PreparedAgentConfiguration, error: string | null }> {
    if (!BACKEND_AGENT_TYPES.some((type) => type === agentType)) throw new AgentConfigurationError([{ agentType, reason: "Agent type is not declared in the backend" }])
    const prepared = await this.settings.prepare(agentType)
    let error: string | null = null
    try {
      await this.verifier.verify(prepared.transport)
    } catch (failure) {
      // Verifiers return controlled messages; never propagate provider response bodies.
      error = failure instanceof Error ? failure.message : "Could not verify model access"
    }
    await this.settings.recordVerification(prepared, error)
    return { prepared, error }
  }

  /** All required agents must pass before the workflow creates any records. */
  async prepareExecution(agentTypes: readonly string[]): Promise<PreparedAgentConfiguration[]> {
    const prepared: PreparedAgentConfiguration[] = []
    const issues: Array<{ agentType: string, reason: string }> = []
    for (const agentType of new Set(agentTypes)) {
      try {
        const checked = await this.check(agentType)
        if (checked.error) issues.push({ agentType, reason: checked.error })
        else prepared.push(checked.prepared)
      } catch (error) {
        if (error instanceof AgentConfigurationError) issues.push(...error.agents)
        else throw error
      }
    }
    if (issues.length) throw new AgentConfigurationError(issues)
    return prepared
  }

  async save(agentType: string, modelId: number, credentialId: number, options: AgentExecutionOptions = {}): Promise<AgentSettingsView> {
    if (!BACKEND_AGENT_TYPES.some((type) => type === agentType)) {
      throw new UnknownAgentTypeError(`Agent type ${agentType} is not declared in the backend`)
    }
    await this.settings.saveAssignments(agentType, modelId, credentialId, options)
    return (await this.list()).find((agent) => agent.agentType === agentType)!
  }

  async list(): Promise<AgentSettingsView[]> {
    const agentTypes = [...BACKEND_AGENT_TYPES].sort()
    const stored = await this.settings.listByAgentTypes(agentTypes)
    const configurations = new Map(stored.map((row) => [row.agentType, row.configuration]))
    const verifications = new Map(stored.map((row) => [row.agentType, row.verification]))
    return agentTypes.map((agentType) => {
      const configuration = configurations.get(agentType) ?? null
      return {
        agentType,
        configured: configuration !== null && configuration.model.providerId === configuration.credential.providerId,
        configuration,
        verification: verifications.get(agentType) ?? { status: "not_verified", checkedAt: null, message: null },
      }
    })
  }
}
