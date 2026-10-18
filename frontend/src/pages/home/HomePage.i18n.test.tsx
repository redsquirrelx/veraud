import { afterEach, describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { HomePage } from "./HomePage.tsx"
import { ToastProvider } from "../../app/toasts.tsx"
import { Dock } from "../../app/dock.tsx"
import { initializeI18n } from "../../shared/i18n/index.ts"

const realFetch = globalThis.fetch
const realWebSocket = globalThis.WebSocket

class FakeSocket {
  addEventListener() {}
  close() {}
}

afterEach(async () => {
  globalThis.fetch = realFetch
  globalThis.WebSocket = realWebSocket
  window.localStorage.removeItem("projects.cloneFullRepository")
  window.localStorage.removeItem("projects.shallowClone")
  await initializeI18n("en")
})

function stubFetch(handler: (url: string, init?: RequestInit) => Response) {
  globalThis.fetch = (async (input: unknown, init?: RequestInit) => {
    return handler(String(input), init)
  }) as typeof fetch
  globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket
}

function renderHome() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <HomePage />
        <Dock />
      </ToastProvider>
    </MemoryRouter>
  )
}

describe("HomePage in Spanish", () => {
  it("translates the home chrome while keeping repository content intact", async () => {
    await initializeI18n("es")
    stubFetch((url, init) => {
      if (url.includes("/api/projects") && init?.method === "POST") {
        return new Response(JSON.stringify({ id: 1, repositoryOwner: "acme", repositoryName: "Demo", status: "QUEUED" }), { status: 201 })
      }
      return new Response(JSON.stringify([]), { status: 200 })
    })
    renderHome()

    expect(screen.getByRole("heading", { name: "Proyectos y repositorios" })).toBeDefined()
    expect(screen.getByText(/Supervisión autónoma continua/)).toBeDefined()
    expect(screen.getByText("ISO/IEC 25010")).toBeDefined()
    expect(screen.getByRole("checkbox", { name: "Clon superficial" })).toBeDefined()
    expect(screen.getByRole("button", { name: "Registrar proyecto" })).toBeDefined()
    // The URL example is content and stays untranslated.
    expect(screen.getByPlaceholderText("Repository URL: https://github.com/owner/repo or git@github.com:owner/repo.git")).toBeDefined()
    expect(await screen.findByText("0 proyectos registrados")).toBeDefined()
    expect(screen.getByText("Aún no hay proyectos")).toBeDefined()
  })

  it("toasts the translated registration success", async () => {
    await initializeI18n("es")
    stubFetch((url, init) => {
      if (url.includes("/api/projects") && init?.method === "POST") {
        return new Response(JSON.stringify({ id: 1, repositoryOwner: "acme", repositoryName: "Demo", status: "QUEUED" }), { status: 201 })
      }
      return new Response(JSON.stringify([]), { status: 200 })
    })
    renderHome()

    await userEvent.type(screen.getByPlaceholderText("Repository URL: https://github.com/owner/repo or git@github.com:owner/repo.git"), "https://github.com/acme/Demo")
    await userEvent.click(screen.getByRole("button", { name: "Registrar proyecto" }))

    expect(await screen.findByText("Proyecto acme/Demo registrado")).toBeDefined()
  })
})
