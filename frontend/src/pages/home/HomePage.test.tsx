import { afterEach, describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { HomePage } from "./HomePage.tsx"

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

function stubFetch(handler: (url: string) => Response) {
  globalThis.fetch = (async (input: unknown) => {
    return handler(String(input))
  }) as typeof fetch
  globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket
}

function renderHome() {
  render(
    <MemoryRouter>
      <HomePage />
    </MemoryRouter>
  )
}

describe("HomePage", () => {
  it("shows the registration use case", () => {
    stubFetch(() => new Response(JSON.stringify([]), { status: 200 }))
    renderHome()

    expect(screen.getByText("Projects and repositories")).toBeDefined()
    expect(screen.getByPlaceholderText("https://github.com/owner/repo")).toBeDefined()
    expect(screen.getByRole("button", { name: "Register project" })).toBeDefined()
  })

  it("shows Wait on the button while submitting", async () => {
    stubFetch(() => new Response(JSON.stringify([]), { status: 200 }))
    renderHome()

    await userEvent.type(screen.getByPlaceholderText("https://github.com/owner/repo"), "https://github.com/acme/Demo")
    await userEvent.click(screen.getByRole("button", { name: "Register project" }))

    expect(await screen.findByRole("button", { name: "Wait" })).toBeDefined()
  })

  it("toasts success in the dock after registering", async () => {
    stubFetch((url) => {
      if (url.includes("/api/projects")) {
        return new Response(
          JSON.stringify({ id: 1, repositoryOwner: "acme", repositoryName: "Demo", status: "QUEUED" }),
          { status: 201 }
        )
      }
      return new Response(JSON.stringify([]), { status: 200 })
    })
    renderHome()

    await userEvent.type(screen.getByPlaceholderText("https://github.com/owner/repo"), "https://github.com/acme/Demo")
    await userEvent.click(screen.getByRole("button", { name: "Register project" }))

    expect(await screen.findByText("Project acme/Demo registered")).toBeDefined()
  })

  it("toasts the backend error in the dock", async () => {
    stubFetch((url) => {
      if (url.includes("/api/projects")) {
        return new Response(JSON.stringify({ message: "Repository is not accessible" }), { status: 422 })
      }
      return new Response(JSON.stringify([]), { status: 200 })
    })
    renderHome()

    await userEvent.type(screen.getByPlaceholderText("https://github.com/owner/repo"), "https://github.com/acme/Gone")
    await userEvent.click(screen.getByRole("button", { name: "Register project" }))

    expect(await screen.findByRole("alert")).toBeDefined()
  })
})
