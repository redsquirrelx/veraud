import { beforeEach, expect, it, vi } from "vitest"
import { requestJson } from "../../infrastructure/http-client/httpClient.ts"
import { loadExecutionEvents, type ExecutionEvent } from "./executionEventsApi.ts"

vi.mock("../../infrastructure/http-client/httpClient.ts", () => ({ requestJson: vi.fn() }))
beforeEach(() => vi.resetAllMocks())
const event = (eventId: string, sequence: number, occurredAt: string) => ({ eventId, streamId: "s", sequence, occurredAt }) as ExecutionEvent

it("fetches all pages, sorts by occurrence (not reception), and preserves repeated actions", async () => {
  const first = event("a", 1, "2026-10-31T10:00:00Z")
  const second = event("b", 2, "2026-10-31T10:00:00Z")
  const third = event("c", 3, "2026-10-31T11:00:00Z")
  vi.mocked(requestJson).mockResolvedValueOnce({ total: 4, events: [third, second] })
    .mockResolvedValueOnce({ total: 4, events: [first, second] })
  const result = await loadExecutionEvents(8, new AbortController().signal)
  expect(result.map((row) => row.eventId)).toEqual(["a", "b", "c"])
  expect(requestJson).toHaveBeenNthCalledWith(2, "/api/agent-executions/8/events?offset=2&limit=200", expect.any(String), expect.any(Object), false)
})

it("rejects incomplete pagination and aborted responses", async () => {
  vi.mocked(requestJson).mockResolvedValue({ total: 2, events: [] })
  await expect(loadExecutionEvents(8, new AbortController().signal)).rejects.toThrow("Incomplete")
  const controller = new AbortController()
  controller.abort()
  await expect(loadExecutionEvents(8, controller.signal)).rejects.toThrow("Aborted")
})
