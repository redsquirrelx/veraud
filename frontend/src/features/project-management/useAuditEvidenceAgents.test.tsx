import { act, renderHook } from "@testing-library/react"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { getQualityAuditConfiguration, type AuditConfigurationHistory } from "./qualityAuditApi.ts"
import { useAuditEvidenceAgents } from "./useAuditEvidenceAgents.ts"

vi.mock("./qualityAuditApi.ts", () => ({ getQualityAuditConfiguration: vi.fn() }))
const history: AuditConfigurationHistory = { configuration: null, invocations: [{ id: "inv-1", agentId: "agent", status: "running" }] }
beforeEach(() => { vi.useFakeTimers(); vi.mocked(getQualityAuditConfiguration).mockReset() })
afterEach(() => vi.useRealTimers())

it("polls only while the running audit's evidence tab is active and retains receipts on failures", async () => {
  vi.mocked(getQualityAuditConfiguration).mockResolvedValueOnce(history).mockRejectedValueOnce(new Error("offline")).mockResolvedValue(history)
  const { result, rerender, unmount } = renderHook(({ active }) => useAuditEvidenceAgents(2, 41, active, true, 0), { initialProps: { active: false } })
  expect(getQualityAuditConfiguration).not.toHaveBeenCalled()
  rerender({ active: true })
  await act(async () => { await Promise.resolve() })
  expect(result.current.history).toEqual(history)
  await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
  expect(result.current.failed).toBe(true)
  expect(result.current.history).toEqual(history)
  rerender({ active: false })
  await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
  expect(getQualityAuditConfiguration).toHaveBeenCalledTimes(2)
  expect(vi.getTimerCount()).toBe(0)
  unmount()
})

it("does not overlap reads and aborts obsolete audit requests", async () => {
  let finish!: (value: AuditConfigurationHistory) => void
  vi.mocked(getQualityAuditConfiguration).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    .mockResolvedValue({ ...history, invocations: [] })
  const { result, rerender } = renderHook(({ id }) => useAuditEvidenceAgents(2, id, true, true, 0), { initialProps: { id: 41 } })
  await act(async () => { await vi.advanceTimersByTimeAsync(20000) })
  expect(getQualityAuditConfiguration).toHaveBeenCalledTimes(1)
  const signal = vi.mocked(getQualityAuditConfiguration).mock.calls[0][2]
  rerender({ id: 42 })
  await act(async () => { await Promise.resolve() })
  expect(signal?.aborted).toBe(true)
  await act(async () => { finish(history) })
  expect(result.current.history?.invocations).toEqual([])
})

it("refreshes receipts on completion then caches final configuration across tab switches", async () => {
  vi.mocked(getQualityAuditConfiguration).mockResolvedValue(history)
  const { rerender } = renderHook(({ active, pending }) => useAuditEvidenceAgents(2, 41, active, pending, 0),
    { initialProps: { active: true, pending: true } })
  await act(async () => { await Promise.resolve() })
  rerender({ active: true, pending: false })
  await act(async () => { await Promise.resolve() })
  expect(getQualityAuditConfiguration).toHaveBeenCalledTimes(2)
  rerender({ active: false, pending: false })
  rerender({ active: true, pending: false })
  await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
  expect(getQualityAuditConfiguration).toHaveBeenCalledTimes(2)
})
