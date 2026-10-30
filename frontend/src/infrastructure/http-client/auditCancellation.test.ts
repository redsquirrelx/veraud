import { afterEach, expect, it, vi } from "vitest"
import { cancelQualityAudit } from "./httpClient.ts"

afterEach(() => vi.unstubAllGlobals())

it("posts to the project-scoped endpoint and deduplicates in-flight requests", async () => {
  let finish!: (value: Response) => void
  const fetch = vi.fn(() => new Promise<Response>((resolve) => { finish = resolve }))
  vi.stubGlobal("fetch", fetch)
  const first = cancelQualityAudit(5, 41)
  const duplicate = cancelQualityAudit(5, 41)
  expect(first).toBe(duplicate)
  expect(fetch).toHaveBeenCalledOnce()
  expect(fetch.mock.calls[0]).toEqual([expect.stringContaining("/api/projects/5/audits/41/cancel"), expect.objectContaining({ method: "POST" })])
  finish(new Response(JSON.stringify({ id: 41, executionStatus: "Running", auditStatus: "cancelling", finishedAt: null, error: null }), { status: 202 }))
  expect((await first).auditStatus).toBe("cancelling")
})

it("allows retrying after a failed request and rejects another audit's response", async () => {
  const fetch = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(new Response(JSON.stringify({ id: 42 }), { status: 202 }))
  vi.stubGlobal("fetch", fetch)
  await expect(cancelQualityAudit(5, 41)).rejects.toThrow("offline")
  await expect(cancelQualityAudit(5, 41)).rejects.toThrow("another audit")
  expect(fetch).toHaveBeenCalledTimes(2)
})

it("never sends requests for DEMO or invalid project identifiers", async () => {
  const fetch = vi.fn()
  vi.stubGlobal("fetch", fetch)
  await expect(cancelQualityAudit(-1, -1)).rejects.toThrow()
  await expect(cancelQualityAudit(5, 0)).rejects.toThrow()
  expect(fetch).not.toHaveBeenCalled()
})
