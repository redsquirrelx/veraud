import type { AgentConfiguration, AgentSettingsStore, AgentExecutionOptions } from "./agent-settings.repository.js"
import { InvalidAgentAssignmentError, UnknownAgentTypeError } from "./agent-settings.errors.js"
import { AgentConfigurationError, type AgentVerification, type ModelAccessVerifier, type PreparedAgentConfiguration } from "./agent-configuration.js"
import { AgentCatalogError, type AgentCatalogSource } from "./agent-catalog.js"

export interface AgentSettingsView {
  agentType: string
  name: string
  role: string
  requiresModel: boolean
  modelConfigurationAgentType: string | null
  executionModes: string[]
  availability: string
  parentAgentTypes: string[]
  childAgentTypes: string[]
  configured: boolean
  configuration: AgentConfiguration | null
  verification: AgentVerification
}

export class AgentSettingsService {
  constructor(private settings: AgentSettingsStore, private verifier: ModelAccessVerifier, private catalog?: AgentCatalogSource) {}

  async synchronize(): Promise<AgentSettingsView[]> {
    if (!this.catalog) throw new AgentCatalogError("No agent-server catalog source is configured")
    const catalog = await this.catalog.getAgentCatalog()
    await this.settings.synchronizeCatalog(catalog)
    return this.list()
  }

  /** Model transport keys come from the synchronized hierarchy, not a local agent list. */
  async modelParticipants(rootAgentType: string): Promise<string[]> {
    const agents = new Map((await this.settings.listDeclared()).map((agent) => [agent.agentType, agent]))
    const root = agents.get(rootAgentType)
    if (!root) throw new AgentConfigurationError([{ agentType: rootAgentType, reason: "Agent is not declared by the agent-server" }])
    const visited = new Set<string>()
    const models = new Set<string>()
    const visit = (id: string): void => {
      if (visited.has(id)) return
      visited.add(id)
      const agent = agents.get(id)
      if (!agent || agent.availability !== "available") return
      if (agent.requiresModel && agent.modelConfigurationAgentType) models.add(agent.modelConfigurationAgentType)
      for (const child of agent.childAgentTypes) visit(child)
    }
    visit(rootAgentType)
    return [...models]
  }

  async verify(agentType: string): Promise<AgentSettingsView> {
    await this.check(agentType)
    return (await this.list()).find((agent) => agent.agentType === agentType)!
  }

  private async check(agentType: string): Promise<{ prepared: PreparedAgentConfiguration, error: string | null }> {
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
    const agent = (await this.settings.listDeclared()).find((row) => row.agentType === agentType)
    if (!agent) throw new UnknownAgentTypeError(`Agent type ${agentType} is not declared by the agent-server`)
    if (!agent.requiresModel || agent.modelConfigurationAgentType !== agentType || agent.availability !== "available") {
      throw new InvalidAgentAssignmentError("This agent does not have an independent model configuration")
    }
    await this.settings.saveAssignments(agentType, modelId, credentialId, options)
    return (await this.list()).find((agent) => agent.agentType === agentType)!
  }

  async list(): Promise<AgentSettingsView[]> {
    const stored = await this.settings.listDeclared()
    return stored.map((row) => {
      const configuration = row.configuration
      return {
        agentType: row.agentType, name: row.name, role: row.role, requiresModel: row.requiresModel,
        modelConfigurationAgentType: row.modelConfigurationAgentType, executionModes: row.executionModes,
        availability: row.availability, parentAgentTypes: row.parentAgentTypes, childAgentTypes: row.childAgentTypes,
        configured: configuration !== null && configuration.model.providerId === configuration.credential.providerId,
        configuration,
        verification: row.verification,
      }
    })
  }
}
