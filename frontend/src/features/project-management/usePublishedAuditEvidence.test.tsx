import { act, renderHook } from "@testing-library/react"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { getPublishedAuditEvidence } from "./qualityAuditApi.ts"
import { usePublishedAuditEvidence } from "./usePublishedAuditEvidence.ts"

vi.mock("./qualityAuditApi.ts", () => ({ getPublishedAuditEvidence: vi.fn() }))
beforeEach(() => { vi.useFakeTimers(); vi.mocked(getPublishedAuditEvidence).mockReset() })
afterEach(() => { vi.useRealTimers() })

it("polls published records, retains them on failure, and stops after the terminal response", async () => {
  vi.mocked(getPublishedAuditEvidence).mockResolvedValueOnce({ partial: true, available: true, data: { evidence_inventory: ["E-1"] } })
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce({ partial: false, available: true, data: { evidence_inventory: ["E-1", "E-2"] } })
  const { result, unmount } = renderHook(() => usePublishedAuditEvidence(2, 41, true))
  await act(async () => { await Promise.resolve() })
  expect(result.current.state).toMatchObject({ status: "loaded", data: { evidence_inventory: ["E-1"] } })
  await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
  expect(result.current.failed).toBe(true)
  expect(result.current.state).toMatchObject({ status: "loaded", data: { evidence_inventory: ["E-1"] } })
  await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
  expect(result.current.failed).toBe(false)
  expect(result.current.value?.partial).toBe(false)
  await act(async () => { await vi.advanceTimersByTimeAsync(15000) })
  expect(getPublishedAuditEvidence).toHaveBeenCalledTimes(3)
  unmount()
  expect(vi.getTimerCount()).toBe(0)
})

it("never overlaps requests and aborts pending work when the view closes", async () => {
  vi.mocked(getPublishedAuditEvidence).mockImplementation(() => new Promise(() => {}))
  const { unmount } = renderHook(() => usePublishedAuditEvidence(2, 41, true))
  await act(async () => { await vi.advanceTimersByTimeAsync(20000) })
  expect(getPublishedAuditEvidence).toHaveBeenCalledTimes(1)
  const signal = vi.mocked(getPublishedAuditEvidence).mock.calls[0][2]
  unmount()
  expect(signal?.aborted).toBe(true)
})

it("does not poll inactive views and discards data on a change of audit", async () => {
  vi.mocked(getPublishedAuditEvidence).mockResolvedValue({ partial: true, available: true, data: { evidence_inventory: ["old"] } })
  const { result, rerender } = renderHook(({ id, enabled }) => usePublishedAuditEvidence(2, id, enabled), { initialProps: { id: 41, enabled: false } })
  expect(getPublishedAuditEvidence).not.toHaveBeenCalled()
  rerender({ id: 41, enabled: true })
  await act(async () => { await Promise.resolve() })
  expect(result.current.state.status).toBe("loaded")
  rerender({ id: 42, enabled: false })
  expect(result.current.state.status).toBe("loading")
  expect(vi.getTimerCount()).toBe(0)
})
