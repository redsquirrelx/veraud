import { afterEach, describe, expect, it } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { ProjectList } from "./ProjectList.tsx"
import { useProjects } from "./useProjects.ts"
import type { ProjectSummary } from "../../infrastructure/http-client/httpClient.ts"

const realFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = realFetch
})

const rows: ProjectSummary[] = [
  { id: 1, repositoryOwner: "acme", repositoryName: "Zulu", status: "READY", registeredAt: "2026-01-01", lastSyncedAt: "2026-01-02", branch: null, commitHash: null },
  { id: 2, repositoryOwner: "acme", repositoryName: "Alpha", status: "QUEUED", registeredAt: "2026-01-02", lastSyncedAt: null, branch: null, commitHash: null },
]

function stubProjects(current: ProjectSummary[]) {
  globalThis.fetch = (async () => {
    return new Response(JSON.stringify(current), { status: 200 })
  }) as typeof fetch
}

function ListHarness() {
  const listing = useProjects()
  return <ProjectList listing={listing} />
}

describe("ProjectList", () => {
  it("shows the registered count and every project", async () => {
    stubProjects(rows)
    render(
      <MemoryRouter>
        <ListHarness />
      </MemoryRouter>
    )

    expect(await screen.findByText("2 registered projects")).toBeDefined()
    expect(screen.getByText("acme/Zulu")).toBeDefined()
    expect(screen.getByText("acme/Alpha")).toBeDefined()
  })

  it("narrows by search text", async () => {
    stubProjects(rows)
    render(
      <MemoryRouter>
        <ListHarness />
      </MemoryRouter>
    )

    await screen.findByText("acme/Zulu")
    await userEvent.type(screen.getByPlaceholderText("Search by repository"), "alpha")

    expect(screen.queryByText("acme/Zulu")).toBeNull()
    expect(screen.getByText("acme/Alpha")).toBeDefined()
  })

  it("sorts by registration date", async () => {
    stubProjects(rows)
    const { container } = render(
      <MemoryRouter>
        <ListHarness />
      </MemoryRouter>
    )

    await screen.findByText("acme/Zulu")

    function titles() {
      return [...container.querySelectorAll(".project-title")].map((node) => node.textContent)
    }
    expect(titles()).toEqual(["acme/Alpha", "acme/Zulu"])

    await userEvent.click(screen.getByRole("tab", { name: "Date" }))

    expect(titles()).toEqual(["acme/Zulu", "acme/Alpha"])
  })

  it("shows skeletons while loading", async () => {
    globalThis.fetch = (() => new Promise<Response>(() => {})) as typeof fetch
    const { container } = render(
      <MemoryRouter>
        <ListHarness />
      </MemoryRouter>
    )
    await waitFor(() => {
      expect(container.querySelectorAll(".project-skeleton").length).toBe(3)
    })
  })

  it("sorts alphabetically and flips direction", async () => {
    stubProjects(rows)
    const { container } = render(
      <MemoryRouter>
        <ListHarness />
      </MemoryRouter>
    )

    await screen.findByText("acme/Zulu")

    function titles() {
      return [...container.querySelectorAll(".project-title")].map((node) => node.textContent)
    }
    expect(titles()).toEqual(["acme/Alpha", "acme/Zulu"])

    await userEvent.click(screen.getByRole("button", { name: "Sort descending" }))

    expect(titles()).toEqual(["acme/Zulu", "acme/Alpha"])
  })

  it("filters by status tab", async () => {
    stubProjects(rows)
    render(
      <MemoryRouter>
        <ListHarness />
      </MemoryRouter>
    )

    await screen.findByText("acme/Zulu")
    await userEvent.click(screen.getByRole("tab", { name: "Queued (1)" }))

    expect(screen.queryByText("acme/Zulu")).toBeNull()
    expect(screen.getByText("acme/Alpha")).toBeDefined()
  })

  it("shows the empty state when none match", async () => {
    stubProjects([])
    render(
      <MemoryRouter>
        <ListHarness />
      </MemoryRouter>
    )

    expect(await screen.findByText("No projects yet")).toBeDefined()
  })

  it("shows a load error instead of the empty state", async () => {
    globalThis.fetch = (() => {
      throw new Error("down")
    }) as typeof fetch
    render(
      <MemoryRouter>
        <ListHarness />
      </MemoryRouter>
    )

    expect(await screen.findByText("Could not load projects")).toBeDefined()
  })

  it("paginates ten projects per page", async () => {
    const many = Array.from({ length: 11 }, (_, index) => ({
      id: index + 1,
      repositoryOwner: "acme",
      repositoryName: `Repo-${String(index + 1).padStart(2, "0")}`,
      status: "READY",
      registeredAt: "2026-01-01",
      lastSyncedAt: "2026-01-02",
      branch: null,
      commitHash: null,
    }))
    stubProjects(many)
    const { container } = render(
      <MemoryRouter>
        <ListHarness />
      </MemoryRouter>
    )

    await screen.findByText("acme/Repo-01")

    function titles() {
      return [...container.querySelectorAll(".project-title")].map((node) => node.textContent)
    }
    expect(titles().length).toBe(10)
    expect(screen.getByText("Page 1 of 2")).toBeDefined()

    await userEvent.click(screen.getByRole("button", { name: "Next page" }))

    expect(await screen.findByText("Page 2 of 2")).toBeDefined()
    expect(titles()).toEqual(["acme/Repo-11"])
  })
})
