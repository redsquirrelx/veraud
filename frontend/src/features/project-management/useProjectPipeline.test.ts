import { act, renderHook, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { useProjectPipeline } from "./useProjectPipeline.ts"
import type { ProjectPipelineStep } from "./projectPipeline.ts"

describe("useProjectPipeline", () => {
  it("blocks duplicate starts, keeps progress until completion and supports another run", async () => {
    let finish!: () => void
    const run = vi.fn(() => new Promise<void>((resolve) => { finish = resolve }))
    const { result } = renderHook(() => useProjectPipeline(2, [{ id: "first", run }]))
    let pending!: Promise<void>
    act(() => { pending = result.current.start("main", "aaa"); void result.current.start("main", "aaa") })
    expect(run).toHaveBeenCalledOnce()
    expect(result.current.running).toBe(true)
    expect(result.current.progress?.stepId).toBe("first")
    await act(async () => { finish(); await pending })
    expect(result.current.status).toBe("completed")
    act(() => { pending = result.current.start("main", "bbb") })
    expect(run).toHaveBeenCalledTimes(2)
    await act(async () => { finish(); await pending })
  })

  it("exposes a safe failure and allows retry", async () => {
    const run = vi.fn().mockRejectedValueOnce(new Error("private transport detail")).mockResolvedValueOnce("artifact")
    const { result } = renderHook(() => useProjectPipeline(2, [{ id: "first", run }]))
    await act(async () => { await result.current.start("main", "aaa") })
    expect(result.current.status).toBe("failed")
    expect(JSON.stringify(result.current)).not.toContain("private transport detail")
    await act(async () => { await result.current.start("main", "aaa") })
    expect(result.current.status).toBe("completed")
  })

  it("retains partial documentary coverage without representing it as complete", async () => {
    const { result } = renderHook(() => useProjectPipeline(2, [{ id: "architecture-context",
      run: async () => ({ execution_status: "partial" }),
    }]))
    await act(async () => { await result.current.start("main", "aaa") })
    expect(result.current.status).toBe("completed")
    expect(result.current.contextStatus).toBe("partial")
  })

  it("aborts on project change and unmount, ignoring late outputs", async () => {
    const signals: AbortSignal[] = []
    const finishes: (() => void)[] = []
    const steps: ProjectPipelineStep[] = [{ id: "first", run: (_context, _results, signal) => {
      signals.push(signal)
      return new Promise<void>((resolve) => { finishes.push(resolve) })
    } }]
    const { result, rerender, unmount } = renderHook(({ id }) => useProjectPipeline(id, steps), { initialProps: { id: 2 } })
    act(() => { void result.current.start("main", "aaa") })
    rerender({ id: 3 })
    expect(signals[0]?.aborted).toBe(true)
    expect(result.current.status).toBe("idle")
    await act(async () => { finishes[0]!() })
    expect(result.current.status).toBe("idle")
    act(() => { void result.current.start("main", "bbb") })
    await waitFor(() => expect(signals).toHaveLength(2))
    unmount()
    expect(signals[1]?.aborted).toBe(true)
    await act(async () => { finishes[1]!() })
  })
})
