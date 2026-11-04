import { act, renderHook, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import type { ActiveTask } from "../../infrastructure/http-client/httpClient.ts"
import { getProjectGraph, startProjectGraph, type ProjectGraph } from "./projectGraphApi.ts"
import { useProjectGraph } from "./useProjectGraph.ts"

vi.mock("./projectGraphApi.ts", () => ({ getProjectGraph: vi.fn(), startProjectGraph: vi.fn() }))
const graph: ProjectGraph = { taskId: 8, projectId: 2, branch: "main", commitHash: "a".repeat(40),
  status: "Running", phase: "extracting", error: null, graphAvailable: false }
const task: ActiveTask = { id: 8, projectId: 2, repositoryOwner: "acme", repositoryName: "demo",
  description: "Graphify", status: "Running", kind: "graph.extract", exitCode: null }

beforeEach(() => { vi.mocked(getProjectGraph).mockReset(); vi.mocked(startProjectGraph).mockReset() })
afterEach(() => vi.useRealTimers())

describe("useProjectGraph", () => {
  it("submits once without blocking rendering and exposes safe launch errors", async () => {
    vi.mocked(getProjectGraph).mockResolvedValue(null)
    let reject!: (error: Error) => void
    vi.mocked(startProjectGraph).mockImplementation(() => new Promise((_resolve, fail) => { reject = fail }))
    const { result } = renderHook(() => useProjectGraph(2, "main", graph.commitHash, []))
    await waitFor(() => expect(getProjectGraph).toHaveBeenCalledOnce())
    let pending!: Promise<void>
    act(() => { pending = result.current.start(); void result.current.start() })
    expect(result.current.starting).toBe(true)
    expect(startProjectGraph).toHaveBeenCalledExactlyOnceWith(2, "main", graph.commitHash, false)
    await act(async () => { reject(new Error("private transport detail")); await pending })
    expect(result.current.running).toBe(false)
    expect(result.current.error).toBe("startError")
  })

  it("refreshes progress on same-status WebSocket updates and restores persisted results", async () => {
    vi.mocked(getProjectGraph).mockResolvedValue(graph)
    const { result, rerender } = renderHook(({ tasks }) => useProjectGraph(2, "main", graph.commitHash, tasks), {
      initialProps: { tasks: [task] },
    })
    await waitFor(() => expect(result.current.graph?.phase).toBe("extracting"))
    vi.mocked(getProjectGraph).mockResolvedValue({ ...graph, phase: "saving" })
    rerender({ tasks: [{ ...task }] })
    await waitFor(() => expect(result.current.graph?.phase).toBe("saving"))
    vi.mocked(getProjectGraph).mockResolvedValue({ ...graph, phase: "completed", status: "Succeded", graphAvailable: true })
    rerender({ tasks: [{ ...task, status: "Succeded" }] })
    await waitFor(() => expect(result.current.graph?.graphAvailable).toBe(true))
    expect(result.current.running).toBe(false)
    expect(result.current.completedTaskId).toBe(8)
  })

  it("reuses completed graphs without POST and only regenerates explicitly", async () => {
    vi.mocked(getProjectGraph).mockResolvedValue({ ...graph, status: "Succeded", phase: "completed", graphAvailable: true })
    const { result } = renderHook(() => useProjectGraph(2, "main", graph.commitHash, []))
    await waitFor(() => expect(result.current.graph?.graphAvailable).toBe(true))
    expect(result.current.completedTaskId).toBeNull()
    await act(async () => { await result.current.start() })
    expect(startProjectGraph).not.toHaveBeenCalled()
    vi.mocked(startProjectGraph).mockResolvedValue({ ...graph, taskId: 9 })
    await act(async () => { await result.current.start(true) })
    expect(startProjectGraph).toHaveBeenCalledExactlyOnceWith(2, "main", graph.commitHash, true)
  })

  it("does not attach a late launch response to a newly selected commit", async () => {
    vi.mocked(getProjectGraph).mockResolvedValue(null)
    let resolve!: (graph: ProjectGraph) => void
    vi.mocked(startProjectGraph).mockImplementation(() => new Promise((done) => { resolve = done }))
    const { result, rerender } = renderHook(({ commit }) => useProjectGraph(2, "main", commit, []), {
      initialProps: { commit: graph.commitHash },
    })
    await waitFor(() => expect(getProjectGraph).toHaveBeenCalledOnce())
    let pending!: Promise<void>
    act(() => { pending = result.current.start() })
    rerender({ commit: "b".repeat(40) })
    expect(result.current.starting).toBe(false)
    await act(async () => { resolve(graph); await pending })
    expect(result.current.graph).toBeNull()
  })

  it("polls while running when no WebSocket callback is received", async () => {
    vi.useFakeTimers()
    vi.mocked(getProjectGraph).mockResolvedValue(graph)
    const { result } = renderHook(() => useProjectGraph(2, "main", graph.commitHash, []))
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(result.current.running).toBe(true)
    vi.mocked(getProjectGraph).mockResolvedValue({ ...graph, phase: "failed", status: "Failed" })
    await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
    expect(result.current.graph?.status).toBe("Failed")
    expect(result.current.running).toBe(false)
  })
})
