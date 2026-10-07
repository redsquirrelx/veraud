import type { PrismaClient } from "../../generated/prisma/client.js"

export interface StoredAiProvider {
  id: number
  name: string
}

export interface StoredAiModel {
  id: number
  aiProviderId: number
  name: string
}

export interface StoredAiCredential {
  id: number
  aiProviderId: number
  name: string
  apiKey: string
}

export interface AiProviderStore {
  listProviders(): Promise<StoredAiProvider[]>
  findProviderById(id: number): Promise<StoredAiProvider | null>
  listModels(aiProviderId: number): Promise<StoredAiModel[]>
  findModelById(id: number): Promise<StoredAiModel | null>
  findModelByName(aiProviderId: number, name: string): Promise<StoredAiModel | null>
  createModel(aiProviderId: number, name: string): Promise<StoredAiModel>
  deleteModel(id: number): Promise<void>
  listCredentials(aiProviderId: number): Promise<StoredAiCredential[]>
  findCredentialById(id: number): Promise<StoredAiCredential | null>
  findCredentialByName(aiProviderId: number, name: string): Promise<StoredAiCredential | null>
  createCredential(aiProviderId: number, name: string, apiKey: string): Promise<StoredAiCredential>
  deleteCredential(id: number): Promise<void>
  countSettingsForModel(modelId: number): Promise<number>
  countSettingsForCredential(credentialId: number): Promise<number>
  ensureSeeded(names: Array<string>): Promise<void>
}

export class AiProviderRepository implements AiProviderStore {
  constructor(private db: PrismaClient) {}

  async listProviders(): Promise<StoredAiProvider[]> {
    const providers = await this.db.aiProvider.findMany({ orderBy: { name: "asc" } })
    return providers.map((provider) => ({ id: provider.id, name: provider.name }))
  }

  async findProviderById(id: number): Promise<StoredAiProvider | null> {
    const provider = await this.db.aiProvider.findUnique({ where: { id } })

    if (provider === null) {
      return null
    }

    return { id: provider.id, name: provider.name }
  }

  async findModelById(id: number): Promise<StoredAiModel | null> {
    const model = await this.db.aiModel.findUnique({ where: { id } })

    if (model === null) {
      return null
    }

    return { id: model.id, aiProviderId: model.aiProviderId, name: model.name }
  }

  async findModelByName(aiProviderId: number, name: string): Promise<StoredAiModel | null> {
    const model = await this.db.aiModel.findFirst({ where: { aiProviderId, name } })

    if (model === null) {
      return null
    }

    return { id: model.id, aiProviderId: model.aiProviderId, name: model.name }
  }

  async createModel(aiProviderId: number, name: string): Promise<StoredAiModel> {
    const model = await this.db.aiModel.create({ data: { aiProviderId, name } })
    return { id: model.id, aiProviderId: model.aiProviderId, name: model.name }
  }

  async deleteModel(id: number): Promise<void> {
    await this.db.aiModel.delete({ where: { id } })
  }

  async findCredentialById(id: number): Promise<StoredAiCredential | null> {
    const credential = await this.db.aiCredential.findUnique({ where: { id } })

    if (credential === null) {
      return null
    }

    return { id: credential.id, aiProviderId: credential.aiProviderId, name: credential.name, apiKey: credential.apiKey }
  }

  async findCredentialByName(aiProviderId: number, name: string): Promise<StoredAiCredential | null> {
    const credential = await this.db.aiCredential.findFirst({ where: { aiProviderId, name } })

    if (credential === null) {
      return null
    }

    return { id: credential.id, aiProviderId: credential.aiProviderId, name: credential.name, apiKey: credential.apiKey }
  }

  async createCredential(aiProviderId: number, name: string, apiKey: string): Promise<StoredAiCredential> {
    const credential = await this.db.aiCredential.create({ data: { aiProviderId, name, apiKey } })
    return { id: credential.id, aiProviderId: credential.aiProviderId, name: credential.name, apiKey: credential.apiKey }
  }

  async deleteCredential(id: number): Promise<void> {
    await this.db.aiCredential.delete({ where: { id } })
  }

  async countSettingsForModel(modelId: number): Promise<number> {
    return this.db.agentSettings.count({ where: { aiModelId: modelId } })
  }

  async countSettingsForCredential(credentialId: number): Promise<number> {
    return this.db.agentSettings.count({ where: { aiCredentialId: credentialId } })
  }

  async listModels(aiProviderId: number): Promise<StoredAiModel[]> {
    const models = await this.db.aiModel.findMany({ where: { aiProviderId }, orderBy: { name: "asc" } })
    return models.map((model) => ({ id: model.id, aiProviderId: model.aiProviderId, name: model.name }))
  }

  async listCredentials(aiProviderId: number): Promise<StoredAiCredential[]> {
    const credentials = await this.db.aiCredential.findMany({ where: { aiProviderId }, orderBy: { name: "asc" } })
    return credentials.map((credential) => ({ id: credential.id, aiProviderId: credential.aiProviderId, name: credential.name, apiKey: credential.apiKey }))
  }

  async ensureSeeded(names: Array<string>): Promise<void> {
    for (const name of names) {
      const existing = await this.db.aiProvider.findFirst({ where: { name } })

      if (existing !== null) {
        continue
      }

      await this.db.aiProvider.create({ data: { name } })
    }
  }
}
