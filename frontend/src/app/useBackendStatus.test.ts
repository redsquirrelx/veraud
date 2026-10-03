import { afterEach, describe, expect, it } from "vitest"
import { renderHook, waitFor } from "@testing-library/react"
import { useBackendStatus } from "./useBackendStatus.ts"

const realFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = realFetch
})

function stubFetch(handler: () => Response) {
  globalThis.fetch = (async () => handler()) as typeof fetch
}

describe("useBackendStatus", () => {
  it("reports both services online", async () => {
    stubFetch(() => new Response(JSON.stringify({ status: "ok", agentServer: "online" }), { status: 200 }))
    const { result } = renderHook(() => useBackendStatus(20))

    await waitFor(() => {
      expect(result.current).toEqual({ backend: "online", agent: "online" })
    })
  })

  it("reports both offline when the backend is down", async () => {
    stubFetch(() => new Response("{}", { status: 500 }))
    const { result } = renderHook(() => useBackendStatus(20))

    await waitFor(() => {
      expect(result.current).toEqual({ backend: "offline", agent: "unknown" })
    })
  })

  it("reports the agent offline while the backend is up", async () => {
    stubFetch(() => new Response(JSON.stringify({ status: "ok", agentServer: "offline" }), { status: 200 }))
    const { result } = renderHook(() => useBackendStatus(20))

    await waitFor(() => {
      expect(result.current).toEqual({ backend: "online", agent: "offline" })
    })
  })

  it("recovers when the backend comes back", async () => {
    let up = false
    stubFetch(() => new Response("{}", { status: up ? 200 : 500 }))
    const { result } = renderHook(() => useBackendStatus(20))

    await waitFor(() => {
      expect(result.current.backend).toBe("offline")
    })

    up = true
    await waitFor(() => {
      expect(result.current.backend).toBe("online")
    })
  })
})
