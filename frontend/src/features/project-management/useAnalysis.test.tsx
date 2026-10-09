import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, renderHook, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { useAnalysis } from "./useAnalysis.ts"
import { AgentExecutionsProvider } from "../../shared/agent-monitor/agentMonitor.tsx"

const realFetch = globalThis.fetch
const realWebSocket = globalThis.WebSocket

type Listener = (event: { data: string }) => void

class FakeSocket {
  static instances: FakeSocket[] = []
  listeners: Record<string, Listener[]> = {}
  url: string

  constructor(url: string) {
    this.url = url
    FakeSocket.instances.push(this)
  }

  addEventListener(type: string, listener: Listener) {
    if (this.listeners[type] === undefined) {
      this.listeners[type] = []
    }
    this.listeners[type].push(listener)
  }

  push(data: unknown) {
    for (const listener of this.listeners["message"] ?? []) {
      listener({ data: JSON.stringify(data) })
    }
  }

  close() {}
}

function wrapper({ children }: { children: ReactNode }) {
  return <AgentExecutionsProvider>{children}</AgentExecutionsProvider>
}

const waiting = {
  id: 11,
  evaluationId: 7,
  agentType: "analyzer",
  status: "Waiting",
  result: null,
  error: null,
  inputTokens: null,
  outputTokens: null,
  createdAt: "2026-01-01",
  startedAt: null,
  finishedAt: null,
}

afterEach(() => {
  globalThis.fetch = realFetch
  globalThis.WebSocket = realWebSocket
  FakeSocket.instances = []
  window.localStorage.removeItem("analysis.lastExecution.2")
  vi.useRealTimers()
})

beforeEach(() => {
  globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket
})

describe("useAnalysis", () => {
  it("starts tracking and completes when the socket reports back", async () => {
    globalThis.fetch = (async () => {
      return new Response(JSON.stringify({ versionId: 3, evaluationId: 7, execution: waiting }), { status: 201 })
    }) as typeof fetch
    globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket

    const { result } = renderHook(() => useAnalysis(2), { wrapper })

    expect(result.current.phase).toBe("idle")

    await act(async () => {
      await result.current.start("main", "a".repeat(40))
    })

    expect(result.current.phase).toBe("tracking")
    expect(result.current.execution?.status).toBe("Waiting")

    await act(async () => {
      FakeSocket.instances[0]?.push({
        type: "agent-execution.updated",
        execution: { ...waiting, status: "Completed", result: "{\"kind\":\"library\"}" },
      })
    })

    await waitFor(() => {
      expect(result.current.phase).toBe("done")
    })
    expect(result.current.execution?.result).toBe("{\"kind\":\"library\"}")
    expect(result.current.analyzing).toBe(false)
  })

  it("reports a failed start with the backend message", async () => {
    globalThis.fetch = (async () => {
      return new Response(JSON.stringify({ message: "No agent type analyzer is registered" }), { status: 422 })
    }) as typeof fetch
    globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket

    const { result } = renderHook(() => useAnalysis(2), { wrapper })

    await act(async () => {
      await result.current.start("main", "a".repeat(40))
    })

    expect(result.current.phase).toBe("error")
    expect(result.current.message).toBe("No agent type analyzer is registered")
    expect(result.current.execution).toBeNull()
  })

  it("does nothing without a project", async () => {
    let calls = 0
    globalThis.fetch = (async () => {
      calls += 1
      return new Response(JSON.stringify({}), { status: 201 })
    }) as typeof fetch

    const { result } = renderHook(() => useAnalysis(null), { wrapper })

    await act(async () => {
      await result.current.start("main", "a".repeat(40))
    })

    expect(calls).toBe(0)
    expect(result.current.phase).toBe("idle")
  })
})
