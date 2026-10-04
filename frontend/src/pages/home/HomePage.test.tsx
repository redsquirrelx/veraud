import { afterEach, describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { HomePage } from "./HomePage.tsx"
import { ToastProvider } from "../../app/toasts.tsx"
import { Dock } from "../../app/dock.tsx"

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

function stubFetch(handler: (url: string, init?: { method?: string }) => Response) {
  globalThis.fetch = (async (input: unknown, init?: { method?: string }) => {
    return handler(String(input), init)
  }) as typeof fetch
  globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket
}

function stubProjects(response: (isPost: boolean) => Response) {
  stubFetch((url, init) => {
    if (url.includes("/api/projects") && init?.method === "POST") {
      return response(true)
    }
    return new Response(JSON.stringify([]), { status: 200 })
  })
}

function renderHome() {
  render(
    <MemoryRouter>
      <ToastProvider>
        <HomePage />
        <Dock />
      </ToastProvider>
    </MemoryRouter>
  )
}

describe("HomePage", () => {
  it("shows the registration use case", () => {
    stubFetch(() => new Response(JSON.stringify([]), { status: 200 }))
    renderHome()

    expect(screen.getByText("Projects and repositories")).toBeDefined()
    expect(screen.getByPlaceholderText("Enter a repository: https://github.com/owner/repo")).toBeDefined()
    expect(screen.getByRole("button", { name: "Register project" })).toBeDefined()
  })

  it("shows Wait on the button while submitting", async () => {
    stubFetch(() => new Response(JSON.stringify([]), { status: 200 }))
    renderHome()

    await userEvent.type(screen.getByPlaceholderText("Enter a repository: https://github.com/owner/repo"), "https://github.com/acme/Demo")
    await userEvent.click(screen.getByRole("button", { name: "Register project" }))

    expect(await screen.findByRole("button", { name: "Wait" })).toBeDefined()
  })

  it("toasts success in the dock after registering", async () => {
    stubProjects(() => new Response(
      JSON.stringify({ id: 1, repositoryOwner: "acme", repositoryName: "Demo", status: "QUEUED" }),
      { status: 201 }
    ))
    renderHome()

    await userEvent.type(screen.getByPlaceholderText("Enter a repository: https://github.com/owner/repo"), "https://github.com/acme/Demo")
    await userEvent.click(screen.getByRole("button", { name: "Register project" }))

    expect(await screen.findByText("Project acme/Demo registered")).toBeDefined()
  })

  it("toasts the backend error in the dock", async () => {
    stubProjects(() => new Response(JSON.stringify({ message: "Repository is not accessible" }), { status: 422 }))
    renderHome()

    await userEvent.type(screen.getByPlaceholderText("Enter a repository: https://github.com/owner/repo"), "https://github.com/acme/Gone")
    await userEvent.click(screen.getByRole("button", { name: "Register project" }))

    expect(await screen.findByRole("alert")).toBeDefined()
  })
})
