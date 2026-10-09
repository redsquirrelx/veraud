import { afterEach, describe, expect, it } from "vitest"
import { act, renderHook, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { AgentExecutionsProvider } from "./agentMonitor.tsx"
import { useAgentExecutions } from "./useAgentExecutions.ts"

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

  emit(type: string) {
    for (const listener of this.listeners[type] ?? []) {
      listener({ data: "" })
    }
  }

  close() {}
}

function wrapper({ children }: { children: ReactNode }) {
  return <AgentExecutionsProvider retryMs={30}>{children}</AgentExecutionsProvider>
}

const opened = {
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
  globalThis.WebSocket = realWebSocket
  FakeSocket.instances = []
})

describe("AgentExecutionsProvider", () => {
  it("collects opened runs and applies later updates", async () => {
    globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket

    const { result } = renderHook(() => useAgentExecutions(), { wrapper })

    expect(result.current).toEqual([])

    FakeSocket.instances[0]?.push({ type: "agent-execution.opened", execution: opened })

    await waitFor(() => {
      expect(result.current.length).toBe(1)
    })

    FakeSocket.instances[0]?.push({
      type: "agent-execution.updated",
      execution: { ...opened, status: "Completed", result: "{\"kind\":\"library\"}" },
    })

    await waitFor(() => {
      expect(result.current[0]?.status).toBe("Completed")
    })
    expect(result.current[0]?.result).toBe("{\"kind\":\"library\"}")
  })

  it("ignores unrelated socket messages", async () => {
    globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket

    const { result } = renderHook(() => useAgentExecutions(), { wrapper })

    await waitFor(() => {
      expect(FakeSocket.instances.length).toBe(1)
    })

    FakeSocket.instances[0]?.push({ type: "task.updated", task: { id: 1 } })
    FakeSocket.instances[0]?.push({ type: "agent-execution.updated", execution: { id: "x" } })
    FakeSocket.instances[0]?.push("not json }")

    await act(async () => {})

    expect(result.current).toEqual([])
  })

  it("reconnects after the socket closes", async () => {
    globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket

    renderHook(() => useAgentExecutions(), { wrapper })

    await waitFor(() => {
      expect(FakeSocket.instances.length).toBe(1)
    })

    FakeSocket.instances[0]?.emit("close")

    await waitFor(() => {
      expect(FakeSocket.instances.length).toBe(2)
    })
  })
})
