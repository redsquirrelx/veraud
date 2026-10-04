import { afterEach, describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { ProjectDetailPage } from "./ProjectDetailPage.tsx"

const realFetch = globalThis.fetch
const realWebSocket = globalThis.WebSocket

class FakeSocket {
  addEventListener() {}
  close() {}
}

afterEach(() => {
  globalThis.fetch = realFetch
  globalThis.WebSocket = realWebSocket
})

const rows = [
  { id: 2, repositoryOwner: "acme", repositoryName: "Demo", status: "READY", registeredAt: "2026-01-01", lastSyncedAt: "2026-01-02", branch: null, commitHash: null },
]

function stubFetch(handler: (url: string) => Response) {
  globalThis.fetch = (async (input: unknown) => {
    return handler(String(input))
  }) as typeof fetch
  globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket
}

function stubProjects() {
  stubFetch((url) => {
    if (url.includes("/api/tasks/active")) {
      return new Response(JSON.stringify([]), { status: 200 })
    }
    return new Response(JSON.stringify(rows), { status: 200 })
  })
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

  it("syncs on demand and refreshes the header", async () => {
    stubFetch((url) => {
      if (url.includes("/sync")) {
        return new Response(
          JSON.stringify({ ...rows[0], status: "READY", lastSyncedAt: "2026-02-02" }),
          { status: 200 }
        )
      }
      if (url.includes("/api/tasks/active")) {
        return new Response(JSON.stringify([]), { status: 200 })
      }
      return new Response(JSON.stringify(rows), { status: 200 })
    })
    renderDetail("/projects/2")

    await screen.findByText("acme/Demo")
    await userEvent.click(screen.getByRole("button", { name: "Sync" }))

    expect(await screen.findByText(`Last synced ${new Date("2026-02-02").toLocaleDateString()}`)).toBeDefined()
    expect(await screen.findByText("Project acme/Demo synced")).toBeDefined()
  })

  it("shows the sync error and re-enables the button", async () => {
    stubFetch((url) => {
      if (url.includes("/sync")) {
        return new Response(JSON.stringify({ message: "Could not sync" }), { status: 422 })
      }
      if (url.includes("/api/tasks/active")) {
        return new Response(JSON.stringify([]), { status: 200 })
      }
      return new Response(JSON.stringify(rows), { status: 200 })
    })
    renderDetail("/projects/2")

    await screen.findByText("acme/Demo")
    await userEvent.click(screen.getByRole("button", { name: "Sync" }))

    expect(await screen.findByRole("alert")).toBeDefined()
    expect(screen.getByText("Could not sync")).toBeDefined()
    expect(screen.getByRole("button", { name: "Sync" }).hasAttribute("disabled")).toBe(false)
  })

  it("shows running sync tasks in the menu", async () => {
    stubFetch((url) => {
      if (url.includes("/api/tasks/active")) {
        return new Response(JSON.stringify([
          { id: 5, projectId: 2, repositoryOwner: "acme", repositoryName: "Demo", description: "pulling acme/Demo", status: "Running", exitCode: null },
        ]), { status: 200 })
      }
      return new Response(JSON.stringify(rows), { status: 200 })
    })
    renderDetail("/projects/2")

    expect(await screen.findByText("pulling acme/Demo")).toBeDefined()
  })
})
