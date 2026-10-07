import { afterEach, describe, expect, it } from "vitest"
import { ApiError, createAiCredential, createAiModel, deleteAiCredential, deleteAiModel, listAiProviders } from "./httpClient.ts"

const realFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = realFetch
})

function stubFetch(status: number, body?: unknown) {
  globalThis.fetch = (async () => {
    if (body === undefined) {
      return new Response(null, { status })
    }
    return new Response(JSON.stringify(body), { status })
  }) as typeof fetch
}

const providers = [{
  id: 1,
  name: "OpenAI",
  models: [{ id: 10, name: "gpt-4o", inUse: true }],
  credentials: [{ id: 20, name: "prod", apiKeyPreview: "****1234", inUse: false }],
}]

describe("listAiProviders", () => {
  it("returns the provider details", async () => {
    stubFetch(200, providers)

    expect(await listAiProviders()).toEqual(providers)
  })

  it("throws an ApiError when the backend fails", async () => {
    stubFetch(500, { message: "boom" })

    await expect(listAiProviders()).rejects.toMatchObject({ status: 500 } as Partial<ApiError>)
  })
})

describe("createAiModel", () => {
  it("posts the name and returns the model", async () => {
    const seen: Array<{ url: string, body: unknown }> = []
    globalThis.fetch = (async (url: string, init?: { body?: string }) => {
      seen.push({ url: String(url), body: JSON.parse(init?.body ?? "{}") as unknown })
      return new Response(JSON.stringify({ id: 10, name: "gpt-4o", inUse: false }), { status: 201 })
    }) as typeof fetch

    const model = await createAiModel(1, "gpt-4o")

    expect(model).toEqual({ id: 10, name: "gpt-4o", inUse: false })
    expect(seen[0]?.url).toContain("/api/ai-providers/1/models")
    expect(seen[0]?.body).toEqual({ name: "gpt-4o" })
  })

  it("reports duplicates with the backend message", async () => {
    stubFetch(409, { message: "Model gpt-4o is already registered" })

    await expect(createAiModel(1, "gpt-4o")).rejects.toMatchObject({ status: 409, message: "Model gpt-4o is already registered" } as Partial<ApiError>)
  })
})

describe("deleteAiModel", () => {
  it("resolves on 204 without a body", async () => {
    stubFetch(204)

    await expect(deleteAiModel(1, 10)).resolves.toBeUndefined()
  })

  it("reports missing models", async () => {
    stubFetch(404, { message: "Model 10 does not exist" })

    await expect(deleteAiModel(1, 10)).rejects.toMatchObject({ status: 404 } as Partial<ApiError>)
  })
})

describe("createAiCredential", () => {
  it("posts the name and key returning only the preview", async () => {
    stubFetch(201, { id: 20, name: "prod", apiKeyPreview: "****1234", inUse: false })

    const credential = await createAiCredential(3, "prod", "secret-1234")

    expect(credential.apiKeyPreview).toBe("****1234")
    expect(credential).not.toHaveProperty("apiKey")
  })
})

describe("deleteAiCredential", () => {
  it("resolves on 204 without a body", async () => {
    stubFetch(204)

    await expect(deleteAiCredential(3, 20)).resolves.toBeUndefined()
  })

  it("reports in-use credentials", async () => {
    stubFetch(409, { message: "Credential prod is assigned to an agent" })

    await expect(deleteAiCredential(3, 20)).rejects.toMatchObject({ status: 409 } as Partial<ApiError>)
  })
})
