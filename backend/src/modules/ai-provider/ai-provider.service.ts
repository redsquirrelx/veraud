import type { AiProviderStore } from "./ai-provider.repository.js"

export class AiProviderNotFoundError extends Error {}
export class AiModelNotFoundError extends Error {}
export class AiCredentialNotFoundError extends Error {}
export class InvalidAiRequestError extends Error {}
export class DuplicateAiError extends Error {}
export class AiInUseError extends Error {}

export const SEEDED_AI_PROVIDERS: Array<string> = ["OpenAI", "Anthropic", "Google"]

export interface AiModelView {
  id: number
  name: string
  inUse: boolean
}

export interface AiCredentialView {
  id: number
  name: string
  apiKeyPreview: string
  inUse: boolean
}

export interface AiProviderDetail {
  id: number
  name: string
  models: Array<AiModelView>
  credentials: Array<AiCredentialView>
}

const MODEL_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._/:-]*$/
const CREDENTIAL_PATTERN = /^[A-Za-z0-9][A-Za-z0-9 _-]*$/

export function maskApiKey(apiKey: string): string {
  if (apiKey.length <= 4) {
    return "****"
  }

  return `****${apiKey.slice(-4)}`
}

export class AiProviderService {
  constructor(private providers: AiProviderStore) {}

  async listProviders(): Promise<Array<AiProviderDetail>> {
    const rows = await this.providers.listProviders()
    const details: Array<AiProviderDetail> = []

    for (const row of rows) {
      details.push(await this.toDetail(row.id, row.name))
    }

    return details
  }

  async getProvider(id: number): Promise<AiProviderDetail> {
    const provider = await this.providers.findProviderById(id)

    if (provider === null) {
      throw new AiProviderNotFoundError(`AI provider ${id} does not exist`)
    }

    return this.toDetail(provider.id, provider.name)
  }

  async createModel(aiProviderId: number, name: string): Promise<AiModelView> {
    const provider = await this.providers.findProviderById(aiProviderId)

    if (provider === null) {
      throw new AiProviderNotFoundError(`AI provider ${aiProviderId} does not exist`)
    }

    const cleanName = assertValidModelName(name)
    const existing = await this.providers.findModelByName(aiProviderId, cleanName)

    if (existing !== null) {
      throw new DuplicateAiError(`Model ${cleanName} is already registered for ${provider.name}`)
    }

    const created = await this.providers.createModel(aiProviderId, cleanName)
    return { id: created.id, name: created.name, inUse: false }
  }

  async deleteModel(aiProviderId: number, modelId: number): Promise<void> {
    const provider = await this.providers.findProviderById(aiProviderId)

    if (provider === null) {
      throw new AiProviderNotFoundError(`AI provider ${aiProviderId} does not exist`)
    }

    const model = await this.providers.findModelById(modelId)

    if (model === null || model.aiProviderId !== aiProviderId) {
      throw new AiModelNotFoundError(`Model ${modelId} does not exist for provider ${aiProviderId}`)
    }

    const inUse = await this.providers.countSettingsForModel(modelId)

    if (inUse > 0) {
      throw new AiInUseError(`Model ${model.name} is assigned to an agent and cannot be deleted`)
    }

    await this.providers.deleteModel(modelId)
  }

  async createCredential(aiProviderId: number, name: string, apiKey: string): Promise<AiCredentialView> {
    const provider = await this.providers.findProviderById(aiProviderId)

    if (provider === null) {
      throw new AiProviderNotFoundError(`AI provider ${aiProviderId} does not exist`)
    }

    const cleanName = assertValidCredentialName(name)
    const cleanKey = assertValidApiKey(apiKey)
    const existing = await this.providers.findCredentialByName(aiProviderId, cleanName)

    if (existing !== null) {
      throw new DuplicateAiError(`Credential ${cleanName} is already registered for ${provider.name}`)
    }

    const created = await this.providers.createCredential(aiProviderId, cleanName, cleanKey)
    return { id: created.id, name: created.name, apiKeyPreview: maskApiKey(created.apiKey), inUse: false }
  }

  async deleteCredential(aiProviderId: number, credentialId: number): Promise<void> {
    const provider = await this.providers.findProviderById(aiProviderId)

    if (provider === null) {
      throw new AiProviderNotFoundError(`AI provider ${aiProviderId} does not exist`)
    }

    const credential = await this.providers.findCredentialById(credentialId)

    if (credential === null || credential.aiProviderId !== aiProviderId) {
      throw new AiCredentialNotFoundError(`Credential ${credentialId} does not exist for provider ${aiProviderId}`)
    }

    const inUse = await this.providers.countSettingsForCredential(credentialId)

    if (inUse > 0) {
      throw new AiInUseError(`Credential ${credential.name} is assigned to an agent and cannot be deleted`)
    }

    await this.providers.deleteCredential(credentialId)
  }

  private async toDetail(id: number, name: string): Promise<AiProviderDetail> {
    const models = await this.providers.listModels(id)
    const credentials = await this.providers.listCredentials(id)
    const modelViews: Array<AiModelView> = []
    const credentialViews: Array<AiCredentialView> = []

    for (const model of models) {
      const settings = await this.providers.countSettingsForModel(model.id)
      modelViews.push({ id: model.id, name: model.name, inUse: settings > 0 })
    }

    for (const credential of credentials) {
      const settings = await this.providers.countSettingsForCredential(credential.id)
      credentialViews.push({ id: credential.id, name: credential.name, apiKeyPreview: maskApiKey(credential.apiKey), inUse: settings > 0 })
    }

    return { id, name, models: modelViews, credentials: credentialViews }
  }
}

function assertValidModelName(name: string): string {
  const trimmed = name.trim()

  if (trimmed.length === 0 || trimmed.length > 128 || MODEL_PATTERN.test(trimmed) === false) {
    throw new InvalidAiRequestError("Model name must use letters, numbers, dot, underscore, dash, slash or colon")
  }

  if (trimmed.includes("..")) {
    throw new InvalidAiRequestError("Model name is not valid")
  }

  return trimmed
}

function assertValidCredentialName(name: string): string {
  const trimmed = name.trim()

  if (trimmed.length === 0 || trimmed.length > 100 || CREDENTIAL_PATTERN.test(trimmed) === false) {
    throw new InvalidAiRequestError("Credential name must use letters, numbers, space, underscore or dash")
  }

  return trimmed
}

function assertValidApiKey(apiKey: string): string {
  const trimmed = apiKey.trim()

  if (trimmed.length === 0 || trimmed.length > 2000 || /\s/.test(trimmed)) {
    throw new InvalidAiRequestError("API key must be a non-empty token without spaces")
  }

  return trimmed
}
