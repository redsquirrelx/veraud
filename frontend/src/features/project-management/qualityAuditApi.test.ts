import { afterEach, expect, it, vi } from "vitest"
import { listQualityAuditPage, startQualityAudit } from "./qualityAuditApi.ts"

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

it("retains the requirements-based API contract although its UI is hidden", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ executionId: 12 }), { status: 202 }))
  vi.stubGlobal("fetch", fetch)
  const requirements = [{ requirement_id: "REQ-001", description: "List items." }]
  await startQualityAudit(2, "main", "a".repeat(40), ["functional_adequacy"], {
    functional_requirements: requirements, functional_config: { retrieval_top_k: 3 },
  })
  expect(JSON.parse(fetch.mock.calls[0]?.[1]?.body)).toEqual({ branch: "main", commitHash: "a".repeat(40),
    attributes: ["functional_adequacy"], functional_requirements: requirements, functional_config: { retrieval_top_k: 3 } })
})
