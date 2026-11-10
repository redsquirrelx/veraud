import { act, renderHook, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { getArchitectureContextContent, type ArchitectureContextContent } from "./architectureContextApi.ts"
import { useArchitectureContext } from "./useArchitectureContext.ts"

vi.mock("./architectureContextApi.ts", () => ({ getArchitectureContextContent: vi.fn() }))

const commit = "a".repeat(40)
const content: ArchitectureContextContent = {
  projectId: 2,
  commitHash: commit,
  executionId: 41,
  executionStatus: "partial",
  schemaVersion: "1",
  createdAt: "2026-11-09T03:40:18.000Z",
  data: { knowledge: [], covered_categories: [], pending_categories: [] },
}

beforeEach(() => vi.resetAllMocks())
afterEach(() => vi.useRealTimers())

describe("useArchitectureContext", () => {
  it("loads once and refetches only when the completion revision changes", async () => {
    vi.mocked(getArchitectureContextContent).mockResolvedValueOnce(null).mockResolvedValue(content)
    const { result, rerender } = renderHook(({ revision }) => useArchitectureContext(2, commit, revision), {
      initialProps: { revision: "waiting" },
    })
    await waitFor(() => expect(result.current).toEqual({ status: "ready", context: null }))
    rerender({ revision: "waiting" })
    expect(getArchitectureContextContent).toHaveBeenCalledTimes(1)
    rerender({ revision: "completed:41" })
    await waitFor(() => expect(result.current).toEqual({ status: "ready", context: content }))
    expect(getArchitectureContextContent).toHaveBeenCalledTimes(2)
  })

  it("stays idle for an invalid commit and never fetches", () => {
    const { result } = renderHook(() => useArchitectureContext(2, "not-a-hash", "ready"))
    expect(result.current).toEqual({ status: "idle" })
    expect(getArchitectureContextContent).not.toHaveBeenCalled()
  })

  it("aborts a late response on unmount", async () => {
    let resolve!: (value: ArchitectureContextContent | null) => void
    const signals: AbortSignal[] = []
    vi.mocked(getArchitectureContextContent).mockImplementation((_id, _hash, signal) => new Promise((resolvePromise) => {
      signals.push(signal!)
      resolve = resolvePromise
    }))
    const { result, unmount } = renderHook(() => useArchitectureContext(2, commit, "ready"))
    expect(result.current.status).toBe("loading")
    unmount()
    expect(signals[0]?.aborted).toBe(true)
    await act(async () => { resolve(content) })
    expect(result.current.status).toBe("loading")
  })
})
