import { afterEach, expect, it, vi } from "vitest"
import { listQualityAuditPage } from "./qualityAuditApi.ts"

afterEach(() => vi.unstubAllGlobals())

it("requests only the selected page and forwards cancellation", async () => {
  const page = { items: [], total: 23, hasRunning: true, limit: 5, offset: 10 }
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(page), { status: 200 }))
  vi.stubGlobal("fetch", fetch)
  const controller = new AbortController()

  expect(await listQualityAuditPage(2, 5, 10, controller.signal)).toEqual(page)
  expect(fetch).toHaveBeenCalledExactlyOnceWith(expect.stringContaining("/api/projects/2/audits?limit=5&offset=10"),
    expect.objectContaining({ signal: controller.signal }))
})
