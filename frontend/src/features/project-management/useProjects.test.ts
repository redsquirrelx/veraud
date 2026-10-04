import { afterEach, describe, expect, it } from "vitest"
import { act, renderHook, waitFor } from "@testing-library/react"
import { useProjects } from "./useProjects.ts"
import type { ProjectSummary } from "../../infrastructure/http-client/httpClient.ts"

const realFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = realFetch
})

const rows: ProjectSummary[] = [
  { id: 1, repositoryOwner: "acme", repositoryName: "Zulu", status: "READY", registeredAt: "2026-01-01", lastSyncedAt: "2026-01-02", branch: null, commitHash: null },
  { id: 2, repositoryOwner: "acme", repositoryName: "Alpha", status: "QUEUED", registeredAt: "2026-01-02", lastSyncedAt: null, branch: null, commitHash: null },
  { id: 3, repositoryOwner: "other", repositoryName: "Beta", status: "SYNCING", registeredAt: "2026-01-03", lastSyncedAt: null, branch: null, commitHash: null },
]

function stubProjects() {
  globalThis.fetch = (async () => {
    return new Response(JSON.stringify(rows), { status: 200 })
  }) as typeof fetch
}

describe("useProjects", () => {
  it("loads every project", async () => {
    stubProjects()
    const { result } = renderHook(() => useProjects())

    await waitFor(() => {
      expect(result.current.total).toBe(3)
    })
    expect(result.current.projects.length).toBe(3)
  })

  it("filters by title text", async () => {
    stubProjects()
    const { result } = renderHook(() => useProjects())

    await waitFor(() => {
      expect(result.current.total).toBe(3)
    })

    act(() => {
      result.current.setSearch("acme/z")
    })
    expect(result.current.projects.map((project) => project.repositoryName)).toEqual(["Zulu"])

    act(() => {
      result.current.setSearch("OTHER/")
    })
    expect(result.current.projects.map((project) => project.repositoryName)).toEqual(["Beta"])
  })

  it("filters by status with counts", async () => {
    stubProjects()
    const { result } = renderHook(() => useProjects())

    await waitFor(() => {
      expect(result.current.total).toBe(3)
    })

    expect(result.current.countFor("READY")).toBe(1)
    expect(result.current.countFor("QUEUED")).toBe(1)

    act(() => {
      result.current.setStatus("READY")
    })
    expect(result.current.projects.map((project) => project.repositoryName)).toEqual(["Zulu"])
  })

  it("reloads on refresh", async () => {
    let calls = 0
    globalThis.fetch = (async () => {
      calls += 1
      return new Response(JSON.stringify(calls === 1 ? [] : rows.slice(0, 1)), { status: 200 })
    }) as typeof fetch
    const { result } = renderHook(() => useProjects())

    await waitFor(() => {
      expect(calls).toBe(1)
    })
    expect(result.current.total).toBe(0)

    await act(async () => {
      await result.current.refresh()
    })
    expect(result.current.total).toBe(1)
  })

  it("paginates ten projects per page", async () => {
    const many = Array.from({ length: 12 }, (_, index) => ({
      id: index + 1,
      repositoryOwner: "acme",
      repositoryName: `Repo-${String(index + 1).padStart(2, "0")}`,
      status: "READY",
      registeredAt: "2026-01-01",
      branch: null,
      commitHash: null,
    }))
    globalThis.fetch = (async () => {
      return new Response(JSON.stringify(many), { status: 200 })
    }) as typeof fetch
    const { result } = renderHook(() => useProjects())

    await waitFor(() => {
      expect(result.current.total).toBe(12)
    })
    expect(result.current.pageCount).toBe(2)
    expect(result.current.projects.length).toBe(10)

    act(() => {
      result.current.setPage(2)
    })
    expect(result.current.page).toBe(2)
    expect(result.current.projects.length).toBe(2)
  })

  it("resets to the first page when the search changes", async () => {
    const many = Array.from({ length: 11 }, (_, index) => ({
      id: index + 1,
      repositoryOwner: "acme",
      repositoryName: `Repo-${String(index + 1).padStart(2, "0")}`,
      status: "READY",
      registeredAt: "2026-01-01",
      branch: null,
      commitHash: null,
    }))
    globalThis.fetch = (async () => {
      return new Response(JSON.stringify(many), { status: 200 })
    }) as typeof fetch
    const { result } = renderHook(() => useProjects())

    await waitFor(() => {
      expect(result.current.total).toBe(11)
    })

    act(() => {
      result.current.setPage(2)
    })
    expect(result.current.page).toBe(2)

    act(() => {
      result.current.setSearch("Repo-01")
    })
    expect(result.current.page).toBe(1)
  })
})
