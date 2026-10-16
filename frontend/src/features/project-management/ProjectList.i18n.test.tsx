import { afterEach, describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { ProjectList } from "./ProjectList.tsx"
import { useProjects } from "./useProjects.ts"
import { initializeI18n } from "../../shared/i18n/index.ts"
import type { ProjectSummary } from "../../infrastructure/http-client/httpClient.ts"

const realFetch = globalThis.fetch

afterEach(async () => {
  globalThis.fetch = realFetch
  window.localStorage.removeItem("projects.pinned")
  await initializeI18n("en")
})

const rows: ProjectSummary[] = [
  { id: 1, repositoryOwner: "acme", repositoryName: "Zulu", cloneProtocol: "https", status: "READY", registeredAt: "2026-01-01", lastSyncedAt: "2026-01-02", branch: null, commitHash: null },
  { id: 2, repositoryOwner: "acme", repositoryName: "Alpha", cloneProtocol: "https", status: "QUEUED", registeredAt: "2026-01-02", lastSyncedAt: null, branch: null, commitHash: null },
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

function renderList() {
  return render(
    <MemoryRouter>
      <ListHarness />
    </MemoryRouter>
  )
}

describe("ProjectList in Spanish", () => {
  it("translates the listing chrome while keeping repository names intact", async () => {
    await initializeI18n("es")
    stubProjects(rows)
    renderList()

    expect(await screen.findByText("2 proyectos registrados")).toBeDefined()
    expect(screen.getByPlaceholderText("Buscar por repositorio")).toBeDefined()
    expect(screen.getByRole("tab", { name: "Todos (2)" })).toBeDefined()
    expect(screen.getByRole("tab", { name: "En cola (1)" })).toBeDefined()
    expect(screen.getByRole("tab", { name: "Listo (1)" })).toBeDefined()
    expect(screen.getByRole("tab", { name: "Título" })).toBeDefined()
    expect(screen.getByRole("tab", { name: "Fecha" })).toBeDefined()
    // Repository identifiers stay untranslated.
    expect(screen.getByText("acme/Zulu")).toBeDefined()
    expect(screen.getByText("acme/Alpha")).toBeDefined()
    // Card chrome translates: status badge, inspect action and pin control.
    expect(screen.getByText("Listo")).toBeDefined()
    expect(screen.getByText("En cola")).toBeDefined()
    expect(screen.getAllByText("HTTPS")).toHaveLength(2)
    expect(screen.getAllByRole("button", { name: "Inspeccionar" }).length).toBe(2)
    expect(screen.getAllByRole("button", { name: "Fijar proyecto" }).length).toBe(2)
  })

  it("translates the empty state", async () => {
    await initializeI18n("es")
    stubProjects([])
    renderList()

    expect(await screen.findByText("0 proyectos registrados")).toBeDefined()
    expect(screen.getByText("Aún no hay proyectos")).toBeDefined()
  })

  it("translates the load error", async () => {
    await initializeI18n("es")
    globalThis.fetch = (() => {
      throw new Error("down")
    }) as typeof fetch
    renderList()

    expect(await screen.findByText("No se pudieron cargar los proyectos")).toBeDefined()
  })
})
