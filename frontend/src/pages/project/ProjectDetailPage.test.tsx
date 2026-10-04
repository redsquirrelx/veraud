import { afterEach, describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { ProjectDetailPage } from "./ProjectDetailPage.tsx"

const realFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = realFetch
})

const rows = [
  { id: 2, repositoryOwner: "acme", repositoryName: "Demo", status: "READY", registeredAt: "2026-01-01", lastSyncedAt: "2026-01-02", branch: null, commitHash: null },
]

function stubProjects() {
  globalThis.fetch = (async () => {
    return new Response(JSON.stringify(rows), { status: 200 })
  }) as typeof fetch
}

function renderDetail(entry: string) {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="projects/:id" element={<ProjectDetailPage />} />
      </Routes>
    </MemoryRouter>
  )
}

describe("ProjectDetailPage", () => {
  it("shows the project header with sidebar", async () => {
    stubProjects()
    renderDetail("/projects/2")

    expect(await screen.findByText("acme/Demo")).toBeDefined()
    expect(screen.getByText("READY")).toBeDefined()
    expect(screen.getByText("Project")).toBeDefined()
    expect(screen.getByText(`Last synced ${new Date("2026-01-02").toLocaleDateString()}`)).toBeDefined()
    expect(screen.getByRole("button", { name: "Sync" })).toBeDefined()
  })

  it("shows not found for unknown projects", async () => {
    stubProjects()
    renderDetail("/projects/99")

    expect(await screen.findByText("Project not found")).toBeDefined()
  })
})
