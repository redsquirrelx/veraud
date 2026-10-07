import { afterEach, describe, expect, it } from "vitest"
import { act, renderHook } from "@testing-library/react"
import { useAiProviders } from "./useAiProviders.ts"

const realFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = realFetch
})

const firstList = [{
  id: 1,
  name: "OpenAI",
  models: [{ id: 10, name: "gpt-4o", inUse: false }],
  credentials: [],
}]

const refreshedList = [{
  id: 1,
  name: "OpenAI",
  models: [{ id: 10, name: "gpt-4o", inUse: false }, { id: 11, name: "o1", inUse: false }],
  credentials: [],
}]

function stubSequence(responses: Array<{ status: number, body?: unknown }>) {
  const calls: Array<{ url: string, method: string, body: unknown }> = []
  globalThis.fetch = (async (url: string, init?: { method?: string, body?: string }) => {
    const next = responses.shift()
    if (next === undefined) {
      throw new Error(`unexpected fetch ${String(url)}`)
    }
    calls.push({ url: String(url), method: init?.method ?? "GET", body: init?.body === undefined ? null : JSON.parse(init.body as string) as unknown })
    if (next.body === undefined) {
      return new Response(null, { status: next.status })
    }
    return new Response(JSON.stringify(next.body), { status: next.status })
  }) as typeof fetch
  return calls
}

describe("useAiProviders", () => {
  it("loads the providers on mount", async () => {
    stubSequence([{ status: 200, body: firstList }])
    const { result } = renderHook(() => useAiProviders())

    expect(result.current.loading).toBe(true)

    await act(async () => {
      await Promise.resolve()
    })

    expect(result.current.loading).toBe(false)
    expect(result.current.providers).toEqual(firstList)
    expect(result.current.loadError).toBe("")
  })

  it("reports the backend message when loading fails", async () => {
    stubSequence([{ status: 500, body: { message: "Database is locked" } }])
    const { result } = renderHook(() => useAiProviders())

    await act(async () => {
      await Promise.resolve()
    })

    expect(result.current.providers).toEqual([])
    expect(result.current.loadError).toBe("Could not load AI providers")
  })

  it("adds a model and refreshes the list", async () => {
    const calls = stubSequence([
      { status: 200, body: firstList },
      { status: 201, body: { id: 11, name: "o1", inUse: false } },
      { status: 200, body: refreshedList },
    ])
    const { result } = renderHook(() => useAiProviders())

    await act(async () => {
      await Promise.resolve()
    })

    let created
    await act(async () => {
      created = await result.current.addModel(1, "o1")
    })

    expect(created).toEqual({ id: 11, name: "o1", inUse: false })
    expect(result.current.providers).toEqual(refreshedList)
    expect(calls[1]).toMatchObject({ method: "POST", body: { name: "o1" } })
    expect(calls[1]?.url).toContain("/api/ai-providers/1/models")
  })

  it("propagates backend errors without refreshing", async () => {
    const calls = stubSequence([
      { status: 200, body: firstList },
      { status: 409, body: { message: "Model o1 is already registered" } },
    ])
    const { result } = renderHook(() => useAiProviders())

    await act(async () => {
      await Promise.resolve()
    })

    await act(async () => {
      await expect(result.current.addModel(1, "o1")).rejects.toThrow("Model o1 is already registered")
    })

    expect(calls.length).toBe(2)
    expect(result.current.providers).toEqual(firstList)
  })

  it("removes a model and refreshes the list", async () => {
    const calls = stubSequence([
      { status: 200, body: refreshedList },
      { status: 204 },
      { status: 200, body: firstList },
    ])
    const { result } = renderHook(() => useAiProviders())

    await act(async () => {
      await Promise.resolve()
    })

    await act(async () => {
      await result.current.removeModel(1, 11)
    })

    expect(result.current.providers).toEqual(firstList)
    expect(calls[1]).toMatchObject({ method: "DELETE" })
    expect(calls[1]?.url).toContain("/api/ai-providers/1/models/11")
  })

  it("adds and removes a credential refreshing each time", async () => {
    stubSequence([
      { status: 200, body: firstList },
      { status: 201, body: { id: 20, name: "prod", apiKeyPreview: "****1234", inUse: false } },
      { status: 200, body: firstList },
      { status: 204 },
      { status: 200, body: firstList },
    ])
    const { result } = renderHook(() => useAiProviders())

    await act(async () => {
      await Promise.resolve()
    })

    await act(async () => {
      const created = await result.current.addCredential(1, "prod", "secret-1234")
      expect(created.apiKeyPreview).toBe("****1234")
    })

    await act(async () => {
      await result.current.removeCredential(1, 20)
    })

    expect(result.current.providers).toEqual(firstList)
  })
})
