import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, renderHook, waitFor } from "@testing-library/react"
import { useContext, type ReactNode } from "react"
import { AgentExecutionsProvider } from "./agentMonitor.tsx"
import { AuditExecutionUpdateContext, useAgentExecutions } from "./useAgentExecutions.ts"
import { discoverExecutions } from "./executionDiscoveryApi.ts"

vi.mock("./executionDiscoveryApi.ts", () => ({ discoverExecutions: vi.fn() }))

const realWebSocket = globalThis.WebSocket
const realFetch = globalThis.fetch

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
  vi.useRealTimers()
  globalThis.WebSocket = realWebSocket
  globalThis.fetch = realFetch
  window.localStorage.removeItem("agents.recentExecutionIds")
  FakeSocket.instances = []
})

beforeEach(() => {
  vi.mocked(discoverExecutions).mockReset().mockResolvedValue([])
  globalThis.fetch = (async () => new Response(JSON.stringify({ ...opened, configuration: null }))) as typeof fetch
})

describe("AgentExecutionsProvider", () => {
  it("polls discovery to recover missed opened events and aborts requests on unmount", async () => {
    vi.useFakeTimers()
    globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket
    vi.mocked(discoverExecutions).mockResolvedValueOnce([]).mockResolvedValue([11])
    const { result, unmount } = renderHook(() => useAgentExecutions(), { wrapper })
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(result.current).toHaveLength(0)
    await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
    expect(result.current[0]?.id).toBe(11)
    const signal = vi.mocked(discoverExecutions).mock.calls[0]?.[0]
    unmount()
    expect(signal?.aborted).toBe(true)
  })
  it("discovers architecture-context executions after reload without local IDs or socket events", async () => {
    globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket
    vi.mocked(discoverExecutions).mockResolvedValue([42])
    globalThis.fetch = (async () => new Response(JSON.stringify({ ...opened, id: 42,
      agentType: "architecture_context", status: "Completed", result: '{"execution_status":"partial"}',
      monitorContext: { project: { id: 2, repositoryOwner: "acme", repositoryName: "demo" },
        branch: "main", commitHash: "a".repeat(40), evaluationType: "ArchitectureContext", qualityAttributes: [], workflowIds: [] },
    }))) as typeof fetch
    const { result } = renderHook(() => useAgentExecutions(), { wrapper })
    await waitFor(() => expect(result.current[0]?.agentType).toBe("architecture_context"))
    expect(result.current[0]?.monitorContext?.project?.id).toBe(2)
    expect(result.current[0]?.result).toBe('{"execution_status":"partial"}')
    expect(JSON.parse(window.localStorage.getItem("agents.recentExecutionIds")!)).toContain(42)
  })

  it("rediscovers work on reconnect even if its opened event was missed", async () => {
    globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket
    const { result } = renderHook(() => useAgentExecutions(), { wrapper })
    await waitFor(() => expect(discoverExecutions).toHaveBeenCalledOnce())
    vi.mocked(discoverExecutions).mockResolvedValue([11])
    act(() => FakeSocket.instances[0]?.emit("open"))
    await waitFor(() => expect(result.current).toHaveLength(1))
  })
  it("merges cancellation responses and terminal events without reopening a confirmed audit", async () => {
    globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket
    const { result } = renderHook(() => ({ executions: useAgentExecutions(), update: useContext(AuditExecutionUpdateContext) }), { wrapper })
    act(() => FakeSocket.instances[0]?.push({ type: "agent-execution.opened", execution: { ...opened, status: "Running" } }))
    await waitFor(() => expect(result.current.executions).toHaveLength(1))
    const requested = { id: 11, executionStatus: "Running", auditStatus: "cancelling", cancellationRequestedAt: "2026-10-30T12:00:00Z", finishedAt: null, error: null }
    act(() => result.current.update(requested))
    expect(result.current.executions[0]?.cancellationRequestedAt).toBe(requested.cancellationRequestedAt)
    expect(result.current.executions[0]?.status).toBe("Running")
    act(() => FakeSocket.instances[0]?.push({ type: "agent-execution.updated", execution: {
      ...opened, status: "Completed", interruptionReason: "cancelled", finishedAt: "2026-10-30T12:01:00Z",
      cancellationRequestedAt: requested.cancellationRequestedAt,
    } }))
    act(() => result.current.update(requested))
    expect(result.current.executions[0]?.status).toBe("Completed")
    expect(result.current.executions[0]?.interruptionReason).toBe("cancelled")
    expect(result.current.executions[0]?.finishedAt).toBe("2026-10-30T12:01:00Z")
  })
  it("keeps live children and terminal usage when a stale hydration response arrives", async () => {
    globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket
    let resolveInitial!: (response: Response) => void
    globalThis.fetch = (() => new Promise<Response>((resolve) => { resolveInitial = resolve })) as typeof fetch
    const child = { invocation_id: "child", parent_invocation_id: "manager", agent_id: "modularity", run_id: "audit",
      status: "running", started_at: "2026-10-20T10:00:00Z", finished_at: null, input_tokens: 2, output_tokens: null, error: null }
    const { result } = renderHook(() => useAgentExecutions(), { wrapper })
    act(() => FakeSocket.instances[0]?.push({ type: "agent-execution.opened", execution: { ...opened, invocations: [child] } }))
    await waitFor(() => expect(resolveInitial).toBeDefined())
    const finished = { ...child, status: "completed", finished_at: "2026-10-20T10:01:00Z", input_tokens: 20 }
    act(() => FakeSocket.instances[0]?.push({ type: "agent-execution.updated", execution: { ...opened, status: "Running", invocations: [finished] } }))
    resolveInitial(new Response(JSON.stringify({ ...opened, invocations: [child] })))
    await waitFor(() => expect(result.current[0]?.invocations).toEqual([finished]))
    act(() => FakeSocket.instances[0]?.push({ type: "agent-execution.updated", execution: { ...opened, status: "Running", invocations: [child] } }))
    expect(result.current[0]?.invocations).toEqual([finished])
  })
  it("hydrates context and terminal audit output even when completion races the initial lookup", async () => {
    globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket
    let resolveInitial!: (response: Response) => void
    const initial = new Promise<Response>((resolve) => { resolveInitial = resolve })
    let calls = 0
    const context = { project: null, branch: null, commitHash: null, evaluationType: "QualityAudit",
      qualityAttributes: ["maintainability"], workflowIds: ["quality-audit"] }
    const output = JSON.stringify({ attributes: ["maintainability", "security"], status: "partial" })
    globalThis.fetch = (async (input) => {
      expect(String(input)).toContain("?monitor=true")
      calls++
      return calls === 1 ? initial : new Response(JSON.stringify({ ...opened, status: "Completed", result: output, monitorContext: context }))
    }) as typeof fetch
    const { result } = renderHook(() => useAgentExecutions(), { wrapper })
    act(() => FakeSocket.instances[0]?.push({ type: "agent-execution.opened", execution: opened }))
    await waitFor(() => expect(calls).toBe(1))
    act(() => FakeSocket.instances[0]?.push({ type: "agent-execution.updated", execution: { ...opened, status: "Completed", result: null } }))
    resolveInitial(new Response(JSON.stringify({ ...opened, monitorContext: context })))
    await waitFor(() => expect(result.current[0]?.result).toBe(output))
    expect(result.current[0]?.status).toBe("Completed")
    expect(result.current[0]?.monitorContext).toEqual(context)
    act(() => FakeSocket.instances[0]?.push({ type: "agent-execution.updated", execution: { ...opened, status: "Completed", result: null } }))
    expect(result.current[0]?.result).toBe(output)
  })

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
