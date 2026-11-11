import { act, renderHook, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { getArchitectureContextAvailability, type ArchitectureContextAvailability } from "./architectureContextApi.ts"
import { useArchitectureContextAvailability } from "./useArchitectureContextAvailability.ts"

vi.mock("./architectureContextApi.ts", () => ({ getArchitectureContextAvailability: vi.fn() }))
const available = (commitHash: string): ArchitectureContextAvailability => ({ projectId: 2, commitHash,
  available: true, executionId: 41, executionStatus: "partial" })
beforeEach(() => vi.resetAllMocks())
afterEach(() => vi.useRealTimers())

describe("architecture context availability", () => {
  it("fails closed during loading and ignores late responses from another version", async () => {
    const finish = new Map<string, (value: ArchitectureContextAvailability) => void>()
    vi.mocked(getArchitectureContextAvailability).mockImplementation((_id, hash) => new Promise((resolve) => { finish.set(hash, resolve) }))
    const { result, rerender } = renderHook(({ hash }) => useArchitectureContextAvailability(2, hash, true, "ready"), {
      initialProps: { hash: "aaa" },
    })
    expect(result.current.available).toBe(false)
    rerender({ hash: "bbb" })
    await act(async () => { finish.get("aaa")!(available("aaa")) })
    expect(result.current.available).toBe(false)
    await act(async () => { finish.get("bbb")!(available("bbb")) })
    expect(result.current.available).toBe(true)
    expect(result.current.executionStatus).toBe("partial")
  })

  it("rechecks after pipeline completion and after missing context becomes available", async () => {
    vi.useFakeTimers()
    vi.mocked(getArchitectureContextAvailability).mockResolvedValueOnce({ ...available("aaa"), available: false, executionId: null, executionStatus: null })
      .mockResolvedValue(available("aaa"))
    const { result, rerender } = renderHook(({ revision }) => useArchitectureContextAvailability(2, "aaa", true, revision), {
      initialProps: { revision: "running" },
    })
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(result.current.available).toBe(false)
    await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    expect(result.current.available).toBe(true)
    rerender({ revision: "completed" })
    expect(result.current.available).toBe(false)
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(result.current.available).toBe(true)
    expect(getArchitectureContextAvailability).toHaveBeenCalledTimes(3)
  })

  it("keeps failed or mismatched checks disabled and does not query history-only views", async () => {
    vi.mocked(getArchitectureContextAvailability).mockResolvedValue(available("another-commit"))
    const { result, rerender } = renderHook(({ enabled }) => useArchitectureContextAvailability(2, "aaa", enabled, "ready"), {
      initialProps: { enabled: false },
    })
    expect(getArchitectureContextAvailability).not.toHaveBeenCalled()
    rerender({ enabled: true })
    await waitFor(() => expect(result.current.status).toBe("failed"))
    expect(result.current.available).toBe(false)
  })
})
