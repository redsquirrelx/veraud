import type { PrismaClient, Prisma } from "../../generated/prisma/client.js"
import { InvalidAgentAssignmentError } from "./agent-settings.errors.js"
import { AgentConfigurationError, configurationFingerprint, type AgentVerification, type PreparedAgentConfiguration } from "./agent-configuration.js"

export interface AgentConfiguration {
  model: { id: number, name: string, providerId: number, providerName: string }
  credential: { id: number, name: string, providerId: number, providerName: string }
  temperature: number | null
  maxTokens: number | null
}

export interface StoredAgentSettings {
  agentType: string
  configuration: AgentConfiguration | null
  verification: AgentVerification
}

export interface AgentExecutionOptions {
  temperature?: number | null
  maxTokens?: number | null
}

export interface AgentSettingsStore {
  listByAgentTypes(agentTypes: string[]): Promise<StoredAgentSettings[]>
  saveAssignments(agentType: string, modelId: number, credentialId: number, options?: AgentExecutionOptions): Promise<void>
  prepare(agentType: string, tx?: Prisma.TransactionClient): Promise<PreparedAgentConfiguration>
  recordVerification(prepared: PreparedAgentConfiguration, message: string | null): Promise<void>
}

export class AgentSettingsRepository implements AgentSettingsStore {
  constructor(private db: PrismaClient) {}

  /** Create only missing rows; never replace an auditor's existing selections. */
  async ensureSeeded(agentTypes: readonly string[]): Promise<void> {
    await this.db.$transaction(agentTypes.map((agentType) => this.db.agentSettings.upsert({
      where: { agentType },
      create: { agentType },
      update: {},
    })))
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
      await tx.agentSettings.upsert({
        where: { agentType },
        create: { agentType, aiModelId: modelId, aiCredentialId: credentialId, ...options },
        update: { aiModelId: modelId, aiCredentialId: credentialId, ...options },
      })
    })
  }

  async listByAgentTypes(agentTypes: string[]): Promise<StoredAgentSettings[]> {
    const rows = await this.db.agentSettings.findMany({
      where: { agentType: { in: agentTypes } },
      select: {
        agentType: true,
        temperature: true,
        maxTokens: true,
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
        && row.verificationFingerprint === configurationFingerprint(row.aiModel, row.aiCredential, row.temperature === null ? null : Number(row.temperature), row.maxTokens)
      return {
        agentType: row.agentType,
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
        } : null,
      }
    })
  }

  async prepare(agentType: string, tx: Prisma.TransactionClient = this.db): Promise<PreparedAgentConfiguration> {
    const row = await tx.agentSettings.findUnique({ where: { agentType }, include: {
      aiModel: { include: { aiProvider: true } }, aiCredential: { include: { aiProvider: true } },
    } })
    const invalid = (reason: string): never => { throw new AgentConfigurationError([{ agentType, reason }]) }
    if (!row?.aiModel || !row.aiCredential) return invalid("Assign a model and credential before starting")
    if (row.aiModel.aiProviderId !== row.aiCredential.aiProviderId) return invalid("Model and credential must belong to the same provider")
    if (!row.aiCredential.apiKey.trim()) return invalid("The credential has no API key")
    const temperature = row.temperature === null ? null : Number(row.temperature)
    if (temperature !== null && (!Number.isFinite(temperature) || temperature < 0 || temperature > 2)) return invalid("Temperature must be between 0 and 2")
    if (row.maxTokens !== null && (!Number.isInteger(row.maxTokens) || row.maxTokens < 1)) return invalid("Maximum tokens must be a positive integer")
    const snapshot: AgentConfiguration = {
      model: { id: row.aiModel.id, name: row.aiModel.name, providerId: row.aiModel.aiProviderId, providerName: row.aiModel.aiProvider.name },
      credential: { id: row.aiCredential.id, name: row.aiCredential.name, providerId: row.aiCredential.aiProviderId, providerName: row.aiCredential.aiProvider.name },
      temperature: temperature ?? 0.2, maxTokens: row.maxTokens ?? 1000,
    }
    return {
      agentType, snapshot,
      fingerprint: configurationFingerprint(row.aiModel, row.aiCredential, temperature, row.maxTokens),
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
