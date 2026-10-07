import { describe, it } from "node:test"
import assert from "node:assert/strict"
import type { AiProviderStore, StoredAiCredential, StoredAiModel, StoredAiProvider } from "./ai-provider.repository.js"
import { AiCredentialNotFoundError, AiInUseError, AiModelNotFoundError, AiProviderNotFoundError, DuplicateAiError, InvalidAiRequestError, AiProviderService, maskApiKey } from "./ai-provider.service.js"

function makeStore(options: {
  providers?: Array<StoredAiProvider>
  models?: Array<StoredAiModel>
  credentials?: Array<StoredAiCredential>
  settingsForModel?: number
  settingsForCredential?: number
} = {}) {
  const state = {
    providers: options.providers ?? [{ id: 1, name: "OpenAI" }],
    models: options.models ?? [],
    credentials: options.credentials ?? [],
    deletedModels: [] as Array<number>,
    deletedCredentials: [] as Array<number>,
  }

  const store: AiProviderStore = {
    async listProviders(): Promise<StoredAiProvider[]> {
      return state.providers
    },
    async findProviderById(id: number): Promise<StoredAiProvider | null> {
      return state.providers.find((provider) => provider.id === id) ?? null
    },
    async listModels(aiProviderId: number): Promise<StoredAiModel[]> {
      return state.models.filter((model) => model.aiProviderId === aiProviderId)
    },
    async findModelById(id: number): Promise<StoredAiModel | null> {
      return state.models.find((model) => model.id === id) ?? null
    },
    async findModelByName(aiProviderId: number, name: string): Promise<StoredAiModel | null> {
      return state.models.find((model) => model.aiProviderId === aiProviderId && model.name === name) ?? null
    },
    async createModel(aiProviderId: number, name: string): Promise<StoredAiModel> {
      const created = { id: state.models.length + 10, aiProviderId, name }
      state.models.push(created)
      return created
    },
    async deleteModel(id: number): Promise<void> {
      state.deletedModels.push(id)
    },
    async listCredentials(aiProviderId: number): Promise<StoredAiCredential[]> {
      return state.credentials.filter((credential) => credential.aiProviderId === aiProviderId)
    },
    async findCredentialById(id: number): Promise<StoredAiCredential | null> {
      return state.credentials.find((credential) => credential.id === id) ?? null
    },
    async findCredentialByName(aiProviderId: number, name: string): Promise<StoredAiCredential | null> {
      return state.credentials.find((credential) => credential.aiProviderId === aiProviderId && credential.name === name) ?? null
    },
    async createCredential(aiProviderId: number, name: string, apiKey: string): Promise<StoredAiCredential> {
      const created = { id: state.credentials.length + 20, aiProviderId, name, apiKey }
      state.credentials.push(created)
      return created
    },
    async deleteCredential(id: number): Promise<void> {
      state.deletedCredentials.push(id)
    },
    async countSettingsForModel(): Promise<number> {
      return options.settingsForModel ?? 0
    },
    async countSettingsForCredential(): Promise<number> {
      return options.settingsForCredential ?? 0
    },
    async ensureSeeded(): Promise<void> {},
  }

  return { store, state, service: new AiProviderService(store) }
}

describe("maskApiKey", () => {
  it("hides everything but the last four characters", () => {
    assert.equal(maskApiKey("sk-abcdef1234"), "****1234")
    assert.equal(maskApiKey("abc"), "****")
  })
})

describe("AiProviderService providers", () => {
  it("lists seeded providers with masked credentials", async () => {
    const { service } = makeStore({
      providers: [{ id: 1, name: "OpenAI" }, { id: 2, name: "Anthropic" }],
      models: [{ id: 10, aiProviderId: 1, name: "gpt-4o" }],
      credentials: [{ id: 20, aiProviderId: 1, name: "prod", apiKey: "sk-secret-1234" }],
    })

    const providers = await service.listProviders()

    assert.deepEqual(providers, [{
      id: 1,
      name: "OpenAI",
      models: [{ id: 10, name: "gpt-4o", inUse: false }],
      credentials: [{ id: 20, name: "prod", apiKeyPreview: "****1234", inUse: false }],
    }, {
      id: 2,
      name: "Anthropic",
      models: [],
      credentials: [],
    }])
  })

  it("marks models and credentials assigned to an agent", async () => {
    const { service } = makeStore({
      models: [{ id: 10, aiProviderId: 1, name: "gpt-4o" }],
      credentials: [{ id: 20, aiProviderId: 1, name: "prod", apiKey: "sk-secret-1234" }],
      settingsForModel: 1,
      settingsForCredential: 1,
    })

    const providers = await service.listProviders()

    assert.deepEqual(providers[0]?.models, [{ id: 10, name: "gpt-4o", inUse: true }])
    assert.deepEqual(providers[0]?.credentials, [{ id: 20, name: "prod", apiKeyPreview: "****1234", inUse: true }])
  })

  it("rejects unknown providers", async () => {
    const { service } = makeStore({ providers: [] })

    await assert.rejects(service.getProvider(99), AiProviderNotFoundError)
    await assert.rejects(service.createModel(99, "gpt-4o"), AiProviderNotFoundError)
    await assert.rejects(service.createCredential(99, "prod", "sk-key"), AiProviderNotFoundError)
  })
})

describe("AiProviderService models", () => {
  it("creates a model trimming its name", async () => {
    const { service } = makeStore()

    const model = await service.createModel(1, "  gpt-4o  ")

    assert.deepEqual(model, { id: 10, name: "gpt-4o", inUse: false })
  })

  it("rejects duplicate and invalid model names", async () => {
    const { service } = makeStore({ models: [{ id: 10, aiProviderId: 1, name: "gpt-4o" }] })

    await assert.rejects(service.createModel(1, "gpt-4o"), DuplicateAiError)
    await assert.rejects(service.createModel(1, "bad name!"), InvalidAiRequestError)
    await assert.rejects(service.createModel(1, ""), InvalidAiRequestError)
    await assert.rejects(service.createModel(1, "a..b"), InvalidAiRequestError)
  })

  it("deletes a model of the same provider", async () => {
    const { service, state } = makeStore({ models: [{ id: 10, aiProviderId: 1, name: "gpt-4o" }] })

    await service.deleteModel(1, 10)

    assert.deepEqual(state.deletedModels, [10])
  })

  it("rejects deleting missing, foreign or in-use models", async () => {
    const { service } = makeStore({
      providers: [{ id: 1, name: "OpenAI" }, { id: 2, name: "Anthropic" }],
      models: [{ id: 10, aiProviderId: 2, name: "claude-3" }],
    })

    await assert.rejects(service.deleteModel(1, 99), AiModelNotFoundError)
    await assert.rejects(service.deleteModel(1, 10), AiModelNotFoundError)

    const busy = makeStore({
      models: [{ id: 10, aiProviderId: 1, name: "gpt-4o" }],
      settingsForModel: 1,
    })

    await assert.rejects(busy.service.deleteModel(1, 10), AiInUseError)
  })
})

describe("AiProviderService credentials", () => {
  it("creates a credential returning only its preview", async () => {
    const { service } = makeStore()

    const credential = await service.createCredential(1, "prod", "sk-secret-1234")

    assert.deepEqual(credential, { id: 20, name: "prod", apiKeyPreview: "****1234", inUse: false })
  })

  it("rejects duplicate and invalid credentials", async () => {
    const { service } = makeStore({ credentials: [{ id: 20, aiProviderId: 1, name: "prod", apiKey: "sk-x" }] })

    await assert.rejects(service.createCredential(1, "prod", "sk-other"), DuplicateAiError)
    await assert.rejects(service.createCredential(1, "", "sk-other"), InvalidAiRequestError)
    await assert.rejects(service.createCredential(1, "other", ""), InvalidAiRequestError)
    await assert.rejects(service.createCredential(1, "other", "has space"), InvalidAiRequestError)
  })

  it("deletes a credential of the same provider", async () => {
    const { service, state } = makeStore({ credentials: [{ id: 20, aiProviderId: 1, name: "prod", apiKey: "sk-x" }] })

    await service.deleteCredential(1, 20)

    assert.deepEqual(state.deletedCredentials, [20])
  })

  it("rejects deleting missing, foreign or in-use credentials", async () => {
    const { service } = makeStore({
      providers: [{ id: 1, name: "OpenAI" }, { id: 2, name: "Anthropic" }],
      credentials: [{ id: 20, aiProviderId: 2, name: "prod", apiKey: "sk-x" }],
    })

    await assert.rejects(service.deleteCredential(1, 99), AiCredentialNotFoundError)
    await assert.rejects(service.deleteCredential(1, 20), AiCredentialNotFoundError)

    const busy = makeStore({
      credentials: [{ id: 20, aiProviderId: 1, name: "prod", apiKey: "sk-x" }],
      settingsForCredential: 2,
    })

    await assert.rejects(busy.service.deleteCredential(1, 20), AiInUseError)
  })
})
