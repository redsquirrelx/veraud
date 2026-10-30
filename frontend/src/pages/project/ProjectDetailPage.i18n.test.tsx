import { afterEach, beforeEach, describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Navigate, Route, Routes } from "react-router-dom"
import { ProjectDetailPage } from "./ProjectDetailPage.tsx"
import { ToastProvider } from "../../app/toasts.tsx"
import { Dock } from "../../app/dock.tsx"
import { initializeI18n } from "../../shared/i18n/index.ts"

const realFetch = globalThis.fetch
const realWebSocket = globalThis.WebSocket

class FakeSocket {
  addEventListener() {}
  close() {}
}

beforeEach(() => {
  window.localStorage.clear()
})

afterEach(async () => {
  globalThis.fetch = realFetch
  globalThis.WebSocket = realWebSocket
  await initializeI18n("en")
})

const rows = [
  { id: 2, repositoryOwner: "acme", repositoryName: "Demo", cloneProtocol: "https", status: "READY", registeredAt: "2026-01-01", lastSyncedAt: "2026-01-02", branch: null, commitHash: null },
]

const gitBranches = { branches: ["main"], currentBranch: "main", detachedHash: null, taskId: 1 }
const gitCommits = {
  branch: "main",
  commits: [{ commitHash: "a".repeat(40), subject: "init" }],
  limit: 30,
  offset: 0,
  taskId: 2,
}

function stubProjects() {
  globalThis.fetch = (async (input: unknown) => {
    const url = String(input)
    if (url.includes("/api/tasks/active")) {
      return new Response(JSON.stringify([]), { status: 200 })
    }
    if (url.endsWith("/audits")) {
      return new Response(JSON.stringify([]), { status: 200 })
    }
    if (url.includes("/git/branches")) {
      return new Response(JSON.stringify(gitBranches), { status: 200 })
    }
    if (url.includes("/git/log")) {
      return new Response(JSON.stringify(gitCommits), { status: 200 })
    }
    if (url.includes("/git/tree")) {
      return new Response(JSON.stringify({ files: ["README.md"], taskId: 6 }), { status: 200 })
    }
    return new Response(JSON.stringify(rows), { status: 200 })
  }) as typeof fetch
  globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket
}

function renderDetail(entry: string) {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <ToastProvider>
        <Routes>
          <Route path="projects/:id" element={<Navigate to="overview" replace />} />
          <Route path="projects/:id/:section" element={<ProjectDetailPage />} />
        </Routes>
        <Dock />
      </ToastProvider>
    </MemoryRouter>
  )
}

describe("ProjectDetailPage in Spanish", () => {
  it("translates the header, sections and registered/synced labels", async () => {
    await initializeI18n("es")
    stubProjects()
    renderDetail("/projects/2")

    expect(await screen.findByRole("heading", { name: "acme/Demo" })).toBeDefined()
    const header = screen.getByLabelText("Contexto del proyecto")
    expect(header).toBeDefined()
    // Status codes become labels; the protocol badge stays verbatim.
    expect(header.textContent).toContain("Listo")
    expect(header.textContent).toContain("HTTPS")
    expect(screen.getByRole("button", { name: "Sincronizar" })).toBeDefined()
    expect(screen.getByRole("button", { name: "Analizar" })).toBeDefined()
    // Translated section tabs keep stable navigation targets.
    expect(screen.getByRole("button", { name: "Resumen" })).toBeDefined()
    expect(screen.getByRole("button", { name: "Análisis" })).toBeDefined()
    expect(screen.getByRole("button", { name: "Auditorías" })).toBeDefined()
    expect(screen.getByRole("button", { name: "Archivos" })).toBeDefined()
    // Registered/synced key strings with locale-formatted dates.
    expect(screen.getByText(/Registrado el/)).toBeDefined()
    expect(screen.getByText(/Última sincronización/)).toBeDefined()
    expect(screen.getByRole("link", { name: "Abrir en GitHub" })).toBeDefined()
    expect(screen.getByRole("region", { name: "Resumen del proyecto" })).toBeDefined()
  })

  it("separates audit setup in Analysis from history in Audits in Spanish", async () => {
    await initializeI18n("es")
    stubProjects()
    renderDetail("/projects/2")

    await screen.findByRole("heading", { name: "acme/Demo" })
    await userEvent.click(screen.getByRole("button", { name: "Análisis" }))

    expect(await screen.findByRole("heading", { name: "Auditoría de calidad" })).toBeDefined()
    await userEvent.click(screen.getByRole("button", { name: "Auditorías" }))
    expect(screen.queryByRole("heading", { name: "Auditoría de calidad" })).toBeNull()
    expect(await screen.findByText("No hay auditorías registradas.")).toBeDefined()
    expect(screen.queryByText("Aún no hay análisis: elige una versión y pulsa Analizar")).toBeNull()
  })

  it("translates the not-found message for unknown projects", async () => {
    await initializeI18n("es")
    stubProjects()
    renderDetail("/projects/99")

    expect(await screen.findByText("Proyecto no encontrado")).toBeDefined()
  })
})
