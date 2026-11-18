import { afterEach, expect, it, vi } from "vitest"
import { ApiError } from "../../infrastructure/http-client/httpClient.ts"
import { getVerificationSuite, listVerificationCommits, requestVerificationSuite, downloadVerificationSuite } from "./qualityAuditApi.ts"

afterEach(() => vi.unstubAllGlobals())
afterEach(() => vi.restoreAllMocks())

function fetchWith(status: number, body: unknown) {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(body), { status })))
  vi.stubGlobal("fetch", fetch)
  return fetch
}

it("requests a verification suite with the default create action", async () => {
  const fetch = fetchWith(202, { status: "building", run_id: "r1", action: "create" })

  const result = await requestVerificationSuite(5, 8)

  expect(fetch).toHaveBeenCalledExactlyOnceWith(expect.stringContaining("/api/projects/5/audits/8/verification-suite"),
    expect.objectContaining({ method: "POST", headers: { "content-type": "application/json" } }))
  const body = JSON.parse((fetch.mock.calls[0]?.[1] as RequestInit | undefined)?.body as string)
  expect(body).toEqual({ action: "create" })
  expect(result).toEqual({ status: "building", run_id: "r1", action: "create" })
})

it("forwards green control, target commit and group for an execute", async () => {
  const fetch = fetchWith(202, { status: "building" })

  await requestVerificationSuite(5, 8, { action: "execute", targetCommit: "a".repeat(40), group: "testability", greenControl: "/green" })

  const body = JSON.parse((fetch.mock.calls[0]?.[1] as RequestInit | undefined)?.body as string)
  expect(body).toEqual({ action: "execute", targetCommit: "a".repeat(40), group: "testability", greenControl: "/green" })
})

it("surfaces the server error body when requesting the suite fails", async () => {
  fetchWith(422, { message: "Configure the Verification Suite model and credential in Settings" })

  const error = await requestVerificationSuite(5, 8).catch((cause: unknown) => cause)

  expect(error).toBeInstanceOf(ApiError)
  expect((error as ApiError).status).toBe(422)
  expect((error as ApiError).message).toBe("Configure the Verification Suite model and credential in Settings")
  expect((error as ApiError).messageSource).toBe("server")
})

it("falls back to the client message when the error body carries no message", async () => {
  fetchWith(400, {})

  const error = await requestVerificationSuite(5, 8).catch((cause: unknown) => cause)

  expect(error).toBeInstanceOf(ApiError)
  expect((error as ApiError).status).toBe(400)
  expect((error as ApiError).message).toBe("Could not request the verification suite")
  expect((error as ApiError).messageSource).toBe("client")
})

it("reads verification suite state with the action in the query string and supports the group filter", async () => {
  const fetch = fetchWith(200, { status: "not_built" })

  await getVerificationSuite(5, 8)
  await getVerificationSuite(5, 8, "execute", "testability")

  expect(fetch.mock.calls[0]?.[0]).toContain("?action=create")
  expect(fetch.mock.calls[1]?.[0]).toContain("?action=execute&group=testability")
  expect((fetch.mock.calls[0]?.[1] as RequestInit | undefined)?.signal).toBeInstanceOf(AbortSignal)
})

it("forwards pagination parameters for the verification commits listing", async () => {
  const fetch = fetchWith(200, { commits: [], hasMore: false, baselineCommit: "a".repeat(40), branch: "main", branchTip: "b".repeat(40), limit: 30, offset: 0 })

  await listVerificationCommits(2, 8, 40, 20)

  expect(fetch.mock.calls[0]?.[0]).toContain("/api/projects/2/audits/8/verification-commits?limit=40&offset=20")
})

it("downloads the verification suite ZIP and triggers the browser download", async () => {
  const blob = new Blob(["fake-zip"])
  const fetch = vi.fn().mockResolvedValue(new Response(blob, { status: 200 }))
  vi.stubGlobal("fetch", fetch)
  const createUrl = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:fake")
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {})
  vi.spyOn(document, "createElement").mockImplementation(((tagName: string) => {
    if (tagName === "a") {
      return { href: "", download: "", click: vi.fn(), remove: vi.fn() } as unknown as HTMLElement
    }
    return document.createElementNS("http://www.w3.org/1999/xhtml", tagName)
  }) as typeof document.createElement)

  await downloadVerificationSuite(5, 8)

  expect(fetch).toHaveBeenCalledExactlyOnceWith(expect.stringContaining("/api/projects/5/audits/8/verification-suite.zip"))
  expect(createUrl).toHaveBeenCalledOnce()
})

it("throws an ApiError instead of saving an empty artifact when the suite download fails", async () => {
  fetchWith(404, { message: "Verification suite has not been built yet" })

  const error = await downloadVerificationSuite(5, 8).catch((cause: unknown) => cause)

  expect(error).toBeInstanceOf(ApiError)
  expect((error as ApiError).status).toBe(404)
})
