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
  window.localStorage.removeItem("projects.cloneFullRepository")
  window.localStorage.removeItem("projects.shallowClone")
})

function stubFetch(handler: (url: string, init?: RequestInit) => Response) {
  globalThis.fetch = (async (input: unknown, init?: RequestInit) => {
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
  return render(
    <MemoryRouter>
      <ToastProvider>
        <HomePage />
        <Dock />
      </ToastProvider>
    </MemoryRouter>
  )
}

describe("HomePage", () => {
  for (const checked of [false, true]) {
    it(`sends the current clone preference (${checked}) when registering`, async () => {
      window.localStorage.setItem("projects.shallowClone", "false")
      let body: unknown
      stubFetch((_url, init) => {
        if (init?.method === "POST") {
          body = JSON.parse(String(init.body))
          return new Response(JSON.stringify({ id: 1, repositoryOwner: "acme", repositoryName: "Demo", status: "QUEUED" }), { status: 201 })
        }
        return new Response(JSON.stringify([]), { status: 200 })
      })
      renderHome()
      if (checked) await userEvent.click(screen.getByRole("checkbox", { name: "Shallow clone" }))
      await userEvent.type(screen.getByPlaceholderText("Repository URL: https://github.com/owner/repo or git@github.com:owner/repo.git"), "https://github.com/acme/Demo")
      await userEvent.click(screen.getByRole("button", { name: "Register project" }))
      expect(body).toEqual({ repositoryUrl: "https://github.com/acme/Demo", shallowClone: checked })
    })
  }
  it("persists the shallow clone preference and restores it when reopening the page", async () => {
    stubFetch(() => new Response(JSON.stringify([]), { status: 200 }))
    const view = renderHome()
    const checkbox = screen.getByRole("checkbox", { name: "Shallow clone" })
    expect(checkbox).toBeChecked()

    await userEvent.click(checkbox)
    expect(window.localStorage.getItem("projects.shallowClone")).toBe("false")
    view.unmount()
    renderHome()
    expect(screen.getByRole("checkbox", { name: "Shallow clone" })).not.toBeChecked()

    await userEvent.click(screen.getByRole("checkbox", { name: "Shallow clone" }))
    expect(window.localStorage.getItem("projects.shallowClone")).toBe("true")
  })

  for (const full of [false, true]) {
    it(`migrates the previous full-clone preference (${full})`, () => {
      window.localStorage.setItem("projects.cloneFullRepository", JSON.stringify(full))
      stubFetch(() => new Response(JSON.stringify([]), { status: 200 }))
      renderHome()
      expect(screen.getByRole("checkbox", { name: "Shallow clone" })).toHaveProperty("checked", !full)
      expect(window.localStorage.getItem("projects.shallowClone")).toBe(JSON.stringify(!full))
      expect(window.localStorage.getItem("projects.cloneFullRepository")).toBeNull()
    })
  }

  it("shows the registration use case", () => {
    stubFetch(() => new Response(JSON.stringify([]), { status: 200 }))
    renderHome()

    expect(screen.getByText("Projects and repositories")).toBeDefined()
    expect(screen.getByPlaceholderText("Repository URL: https://github.com/owner/repo or git@github.com:owner/repo.git")).toBeDefined()
    expect(screen.getByRole("button", { name: "Register project" })).toBeDefined()
  })

  it("shows Wait on the button while submitting", async () => {
    stubFetch(() => new Response(JSON.stringify([]), { status: 200 }))
    renderHome()

    await userEvent.type(screen.getByPlaceholderText("Repository URL: https://github.com/owner/repo or git@github.com:owner/repo.git"), "https://github.com/acme/Demo")
    await userEvent.click(screen.getByRole("button", { name: "Register project" }))

    expect(await screen.findByRole("button", { name: "Wait" })).toBeDefined()
  })

  it("toasts success in the dock after registering", async () => {
    stubProjects(() => new Response(
      JSON.stringify({ id: 1, repositoryOwner: "acme", repositoryName: "Demo", status: "QUEUED" }),
      { status: 201 }
    ))
    renderHome()

    await userEvent.type(screen.getByPlaceholderText("Repository URL: https://github.com/owner/repo or git@github.com:owner/repo.git"), "https://github.com/acme/Demo")
    await userEvent.click(screen.getByRole("button", { name: "Register project" }))

    expect(await screen.findByText("Project acme/Demo registered")).toBeDefined()
  })

  it("toasts the backend error in the dock", async () => {
    stubProjects(() => new Response(JSON.stringify({ message: "Repository is not accessible" }), { status: 422 }))
    renderHome()

    await userEvent.type(screen.getByPlaceholderText("Repository URL: https://github.com/owner/repo or git@github.com:owner/repo.git"), "https://github.com/acme/Gone")
    await userEvent.click(screen.getByRole("button", { name: "Register project" }))

    expect(await screen.findByRole("alert")).toBeDefined()
  })
})
