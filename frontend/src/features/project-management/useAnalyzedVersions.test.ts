import { afterEach, describe, expect, it } from "vitest"
import { act, renderHook, waitFor } from "@testing-library/react"
import { analyzedLabel, useAnalyzedVersions } from "./useAnalyzedVersions.ts"

const realFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = realFetch
})

const versions = [
  { id: 9, branch: "main", commitHash: "b".repeat(40), derivedStatus: "Completed" },
]

describe("useAnalyzedVersions", () => {
  it("stays empty without a project and without fetching", async () => {
    let calls = 0
    globalThis.fetch = (async () => {
      calls += 1
      return new Response(JSON.stringify([]), { status: 200 })
    }) as typeof fetch

    const { result } = renderHook(() => useAnalyzedVersions(null))

    await act(async () => {
      await result.current.refresh()
    })

    expect(calls).toBe(0)
    expect(result.current.versions).toEqual([])
  })

  it("loads the versions on refresh", async () => {
    globalThis.fetch = (async () => {
      return new Response(JSON.stringify(versions), { status: 200 })
    }) as typeof fetch

    const { result } = renderHook(() => useAnalyzedVersions(2))

    await act(async () => {
      await result.current.refresh()
    })

    await waitFor(() => {
      expect(result.current.versions).toEqual(versions)
    })
    expect(result.current.error).toBe("")
  })

  it("reports load failures", async () => {
    globalThis.fetch = (async () => {
      return new Response(JSON.stringify({ message: "boom" }), { status: 500 })
    }) as typeof fetch

    const { result } = renderHook(() => useAnalyzedVersions(2))

    await act(async () => {
      await result.current.refresh()
    })

    await waitFor(() => {
      expect(result.current.error).toBe("Could not load analyzed versions")
    })
    expect(result.current.versions).toEqual([])
  })

  it("labels versions with branch, short hash and status", () => {
    expect(analyzedLabel({
      id: 9,
      branch: "main",
      commitHash: "b".repeat(40),
      analysisStatus: "Pending",
      analyzedAt: null,
      evaluationId: 7,
      execution: null,
      derivedStatus: "Completed",
    })).toBe(`main @ ${"b".repeat(7)} · Completed`)
    expect(analyzedLabel({
      id: 10,
      branch: null,
      commitHash: null,
      analysisStatus: "Pending",
      analyzedAt: null,
      evaluationId: null,
      execution: null,
      derivedStatus: "NeverAnalyzed",
    })).toBe("? @ ? · NeverAnalyzed")
  })

  it("drops the versions when the project changes", async () => {
    globalThis.fetch = (async () => {
      return new Response(JSON.stringify(versions), { status: 200 })
    }) as typeof fetch

    const { result, rerender } = renderHook(({ id }) => useAnalyzedVersions(id), {
      initialProps: { id: 2 as number | null },
    })

    await act(async () => {
      await result.current.refresh()
    })
    expect(result.current.versions).toEqual(versions)

    rerender({ id: null })

    expect(result.current.versions).toEqual([])
  })
})
