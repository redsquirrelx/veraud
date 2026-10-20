import type { PrismaClient, Prisma } from "../../generated/prisma/client.js"
import { InvalidAgentAssignmentError } from "./agent-settings.errors.js"
import { AgentConfigurationError, configurationFingerprint, type AgentVerification, type PreparedAgentConfiguration } from "./agent-configuration.js"
import { parseAgentCatalog, type AgentCatalog } from "./agent-catalog.js"

export interface AgentConfiguration {
  model: { id: number, name: string, providerId: number, providerName: string }
  credential: { id: number, name: string, providerId: number, providerName: string }
  temperature: number | null
  maxTokens: number | null
  tokenBudget?: number | null
  absoluteTokenLimit?: number | null
}

export interface StoredAgentSettings {
  agentType: string
  name: string
  role: string
  requiresModel: boolean
  modelConfigurationAgentType: string | null
  executionModes: string[]
  qualityAttributes: string[]
  workflowIds: string[]
  availability: string
  parentAgentTypes: string[]
  childAgentTypes: string[]
  configuration: AgentConfiguration | null
  verification: AgentVerification
}

export interface AgentExecutionOptions {
  temperature?: number | null
  maxTokens?: number | null
  tokenBudget?: number | null
  absoluteTokenLimit?: number | null
}

export interface AgentSettingsStore {
  listDeclared(): Promise<StoredAgentSettings[]>
  synchronizeCatalog(catalog: AgentCatalog): Promise<void>
  saveAssignments(agentType: string, modelId: number, credentialId: number, options?: AgentExecutionOptions): Promise<void>
  saveCategoryAssignments(attribute: string, modelId: number, credentialId: number): Promise<void>
  prepare(agentType: string, tx?: Prisma.TransactionClient): Promise<PreparedAgentConfiguration>
  recordVerification(prepared: PreparedAgentConfiguration, message: string | null): Promise<void>
}

export class AgentSettingsRepository implements AgentSettingsStore {
  constructor(private db: PrismaClient) {}

  /** Atomic metadata refresh; selections, verification and execution history survive. */
  async synchronizeCatalog(input: AgentCatalog): Promise<void> {
    const catalog = parseAgentCatalog(input)
    await this.db.$transaction(async (tx) => {
      await tx.agentSettings.updateMany({ data: { catalogDeclared: false } })
      for (const agent of catalog.agents) {
        const metadata = { catalogDeclared: true, catalogName: agent.name, catalogRole: agent.role,
          requiresModel: agent.requires_model, modelConfigurationAgentType: agent.model_configuration_id,
          executionModes: JSON.stringify(agent.execution_modes), availability: agent.availability,
          qualityAttributes: JSON.stringify(agent.quality_attributes), workflowIds: JSON.stringify(agent.workflow_ids) }
        await tx.agentSettings.upsert({ where: { agentType: agent.agent_id },
          create: { agentType: agent.agent_id, ...metadata }, update: metadata })
      }
      await tx.agentHierarchy.deleteMany()
      for (const agent of catalog.agents) {
        for (const child of agent.child_ids) {
          await tx.agentHierarchy.create({ data: { parentAgentType: agent.agent_id, childAgentType: child } })
        }
      }
    })
  }

  async saveAssignments(agentType: string, modelId: number, credentialId: number, options: AgentExecutionOptions = {}): Promise<void> {
    await this.db.$transaction(async (tx) => {
      const model = await tx.aiModel.findUnique({ where: { id: modelId }, select: { aiProviderId: true } })
      const credential = await tx.aiCredential.findUnique({ where: { id: credentialId }, select: { aiProviderId: true } })
      if (!model) throw new InvalidAgentAssignmentError("The selected model no longer exists")
      if (!credential) throw new InvalidAgentAssignmentError("The selected credential no longer exists")
      if (model.aiProviderId !== credential.aiProviderId) {
        throw new InvalidAgentAssignmentError("Model and credential must belong to the same provider")
      }
      const existing = await tx.agentSettings.findUnique({ where: { agentType } })
      if (!existing?.catalogDeclared) throw new InvalidAgentAssignmentError("Agent is not declared by the agent-server")
      if (!existing.requiresModel || existing.modelConfigurationAgentType !== agentType || existing.availability !== "available") {
        throw new InvalidAgentAssignmentError("This agent does not have an independent model configuration")
      }
      validateTokenLimits(
        options.tokenBudget === undefined ? existing?.tokenBudget ?? null : options.tokenBudget,
        options.absoluteTokenLimit === undefined ? existing?.absoluteTokenLimit ?? null : options.absoluteTokenLimit,
      )
      await tx.agentSettings.update({
        where: { agentType },
        data: { aiModelId: modelId, aiCredentialId: credentialId, ...options },
      })
    })
  }

  async listDeclared(): Promise<StoredAgentSettings[]> {
    const rows = await this.db.agentSettings.findMany({
      where: { catalogDeclared: true }, orderBy: { agentType: "asc" },
      select: {
        agentType: true,
        catalogName: true, catalogRole: true, requiresModel: true, modelConfigurationAgentType: true,
        executionModes: true, availability: true,
        qualityAttributes: true, workflowIds: true,
        parentLinks: { select: { parentAgentType: true }, orderBy: { parentAgentType: "asc" } },
        childLinks: { select: { childAgentType: true }, orderBy: { childAgentType: "asc" } },
        temperature: true,
        maxTokens: true,
        tokenBudget: true,
        absoluteTokenLimit: true,
        verificationFingerprint: true,
        verificationCheckedAt: true,
        verificationError: true,
        aiModel: { select: { id: true, name: true, revision: true, aiProviderId: true, aiProvider: { select: { id: true, name: true } } } },
        // This query never reads the API key.
        aiCredential: { select: { id: true, name: true, revision: true, aiProviderId: true, aiProvider: { select: { id: true, name: true } } } },
      },
    })
    return rows.map((row) => {
      const current = row.aiModel !== null && row.aiCredential !== null
        && row.verificationFingerprint === configurationFingerprint(row.aiModel, row.aiCredential, row.temperature === null ? null : Number(row.temperature), row.maxTokens, row.tokenBudget, row.absoluteTokenLimit)
      return {
        agentType: row.agentType,
        name: row.catalogName ?? row.agentType, role: row.catalogRole ?? "unknown",
        requiresModel: row.requiresModel, modelConfigurationAgentType: row.modelConfigurationAgentType,
        executionModes: JSON.parse(row.executionModes) as string[], availability: row.availability,
        qualityAttributes: JSON.parse(row.qualityAttributes) as string[], workflowIds: JSON.parse(row.workflowIds) as string[],
        parentAgentTypes: row.parentLinks.map((link) => link.parentAgentType),
        childAgentTypes: row.childLinks.map((link) => link.childAgentType),
        verification: {
          status: !current || !row.verificationCheckedAt ? "not_verified" as const : row.verificationError ? "failed" as const : "verified" as const,
          checkedAt: current ? row.verificationCheckedAt?.toISOString() ?? null : null,
          message: current ? row.verificationError : null,
        },
        configuration: row.aiModel !== null && row.aiCredential !== null ? {
          model: { id: row.aiModel.id, name: row.aiModel.name, providerId: row.aiModel.aiProvider.id, providerName: row.aiModel.aiProvider.name },
          credential: { id: row.aiCredential.id, name: row.aiCredential.name, providerId: row.aiCredential.aiProvider.id, providerName: row.aiCredential.aiProvider.name },
          temperature: row.temperature === null ? null : Number(row.temperature),
          maxTokens: row.maxTokens,
          tokenBudget: row.tokenBudget,
          absoluteTokenLimit: row.absoluteTokenLimit,
        } : null,
      }
    })
  }

  /** Resolve membership and model owners inside the same transaction as the write. */
  async saveCategoryAssignments(attribute: string, modelId: number, credentialId: number): Promise<void> {
    await this.db.$transaction(async (tx) => {
      const model = await tx.aiModel.findUnique({ where: { id: modelId } })
      const credential = await tx.aiCredential.findUnique({ where: { id: credentialId } })
      if (!model || !credential || model.aiProviderId !== credential.aiProviderId) {
        throw new InvalidAgentAssignmentError("Select an existing model and credential from the same provider")
      }
      const agents = await tx.agentSettings.findMany({ where: { catalogDeclared: true } })
      const members = agents.filter((agent) => (JSON.parse(agent.qualityAttributes) as string[]).includes(attribute))
      if (!members.length) throw new InvalidAgentAssignmentError("Quality category is not declared by the agent-server")
      const owners = new Set(members.filter((agent) => agent.requiresModel && agent.availability === "available")
        .map((agent) => agent.modelConfigurationAgentType).filter((id): id is string => id !== null))
      if (!owners.size) throw new InvalidAgentAssignmentError("This quality category has no configurable model agents")
      for (const id of owners) {
        const owner = agents.find((agent) => agent.agentType === id)
        if (!owner?.requiresModel || owner.modelConfigurationAgentType !== id || owner.availability !== "available") {
          throw new InvalidAgentAssignmentError("Category contains an unavailable model configuration owner")
        }
      }
      await tx.agentSettings.updateMany({ where: { agentType: { in: [...owners] } }, data: {
        aiModelId: modelId, aiCredentialId: credentialId,
        verificationFingerprint: null, verificationCheckedAt: null, verificationError: null,
      } })
    })
  }

  async prepare(agentType: string, tx: Prisma.TransactionClient = this.db): Promise<PreparedAgentConfiguration> {
    const row = await tx.agentSettings.findUnique({ where: { agentType }, include: {
      aiModel: { include: { aiProvider: true } }, aiCredential: { include: { aiProvider: true } },
    } })
    const invalid = (reason: string): never => { throw new AgentConfigurationError([{ agentType, reason }]) }
    if (!row?.catalogDeclared) return invalid("Agent is not declared by the agent-server")
    if (!row.requiresModel || row.modelConfigurationAgentType !== agentType || row.availability !== "available") {
      return invalid("This agent does not have an independent model configuration")
    }
    if (!row?.aiModel || !row.aiCredential) return invalid("Assign a model and credential before starting")
    if (row.aiModel.aiProviderId !== row.aiCredential.aiProviderId) return invalid("Model and credential must belong to the same provider")
    if (!row.aiCredential.apiKey.trim()) return invalid("The credential has no API key")
    const temperature = row.temperature === null ? null : Number(row.temperature)
    if (temperature !== null && (!Number.isFinite(temperature) || temperature < 0 || temperature > 2)) return invalid("Temperature must be between 0 and 2")
    if (row.maxTokens !== null && (!Number.isInteger(row.maxTokens) || row.maxTokens < 1)) return invalid("Maximum tokens must be a positive integer")
    try { validateTokenLimits(row.tokenBudget, row.absoluteTokenLimit) }
    catch (error) { return invalid(error instanceof Error ? error.message : "Invalid token budget") }
    const snapshot: AgentConfiguration = {
      model: { id: row.aiModel.id, name: row.aiModel.name, providerId: row.aiModel.aiProviderId, providerName: row.aiModel.aiProvider.name },
      credential: { id: row.aiCredential.id, name: row.aiCredential.name, providerId: row.aiCredential.aiProviderId, providerName: row.aiCredential.aiProvider.name },
      temperature: temperature ?? 0.2, maxTokens: row.maxTokens ?? 1000,
      tokenBudget: row.tokenBudget, absoluteTokenLimit: row.absoluteTokenLimit,
    }
    return {
      agentType, snapshot,
      fingerprint: configurationFingerprint(row.aiModel, row.aiCredential, temperature, row.maxTokens, row.tokenBudget, row.absoluteTokenLimit),
      transport: { model: { provider: snapshot.model.providerName, name: snapshot.model.name, temperature: snapshot.temperature, max_tokens: snapshot.maxTokens }, api_key: row.aiCredential.apiKey },
    }
  }

  async recordVerification(prepared: PreparedAgentConfiguration, message: string | null): Promise<void> {
    await this.db.$transaction(async (tx) => {
      const current = await this.prepare(prepared.agentType, tx)
      if (current.fingerprint !== prepared.fingerprint) throw new AgentConfigurationError([{ agentType: prepared.agentType, reason: "Configuration changed during verification; retry" }])
      await tx.agentSettings.update({ where: { agentType: prepared.agentType }, data: {
        verificationFingerprint: prepared.fingerprint, verificationCheckedAt: new Date(), verificationError: message,
      } })
    })
  }
}

/** Null means no explicit override; the runtime will resolve its own defaults. */
export function validateTokenLimits(tokenBudget: number | null, absoluteTokenLimit: number | null): void {
  if (tokenBudget !== null && (!Number.isInteger(tokenBudget) || tokenBudget < 1 || tokenBudget > 2147483647)) {
    throw new InvalidAgentAssignmentError("Token budget must be a positive 32-bit integer")
  }
  if (absoluteTokenLimit !== null && (!Number.isInteger(absoluteTokenLimit) || absoluteTokenLimit < 1 || absoluteTokenLimit > 2147483647)) {
    throw new InvalidAgentAssignmentError("Absolute token limit must be a positive 32-bit integer")
  }
  if (tokenBudget !== null && absoluteTokenLimit !== null && absoluteTokenLimit < tokenBudget) {
    throw new InvalidAgentAssignmentError("Absolute token limit must be greater than or equal to the initial token budget")
  }
}
