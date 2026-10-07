import { afterEach, describe, expect, it } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { ToastProvider } from "../../app/toasts.tsx"
import { Dock } from "../../app/dock.tsx"
import { SettingsPage } from "./SettingsPage.tsx"

const realFetch = globalThis.fetch
const realWebSocket = globalThis.WebSocket

class FakeSocket {
  addEventListener() {}
  close() {}
}

afterEach(() => {
  globalThis.fetch = realFetch
  globalThis.WebSocket = realWebSocket
  window.localStorage.removeItem("tasks.visibility")
})

const providers = [{
  id: 1,
  name: "OpenAI",
  models: [{ id: 10, name: "gpt-4o", inUse: true }],
  credentials: [{ id: 20, name: "prod", apiKeyPreview: "****1234", inUse: false }],
}]

function stubRouted(responses: Array<{ status: number, body?: unknown }>) {
  const calls: Array<{ url: string, method: string }> = []
  globalThis.fetch = (async (url: string, init?: { method?: string }) => {
    if (String(url).includes("/api/tasks/active")) {
      return new Response(JSON.stringify([]), { status: 200 })
    }
    const next = responses.shift()
    if (next === undefined) {
      throw new Error(`unexpected fetch ${String(url)}`)
    }
    calls.push({ url: String(url), method: init?.method ?? "GET" })
    if (next.body === undefined) {
      return new Response(null, { status: next.status })
    }
    return new Response(JSON.stringify(next.body), { status: next.status })
  }) as typeof fetch
  globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket
  return calls
}

function renderSettings(responses: Array<{ status: number, body?: unknown }>) {
  const calls = stubRouted(responses)
  render(
    <ToastProvider>
      <SettingsPage />
      <Dock />
    </ToastProvider>
  )
  return calls
}

describe("SettingsPage", () => {
  it("shows the title with task notification toggles", () => {
    renderSettings([{ status: 200, body: [] }])

    expect(screen.getByRole("heading", { name: "General settings" })).toBeDefined()
    expect(screen.getByText("Task notifications")).toBeDefined()
    expect(screen.getByRole("checkbox", { name: /Clone/ })).toBeDefined()
  })

  it("persists muted read tasks as visible", async () => {
    renderSettings([{ status: 200, body: [] }])

    const toggle = screen.getByRole("checkbox", { name: /List branches/ })
    expect(toggle).not.toBeChecked()

    await userEvent.click(toggle)

    expect(toggle).toBeChecked()
    expect(JSON.parse(window.localStorage.getItem("tasks.visibility") as string)["list-branches"]).toBe(true)
  })

  it("loads models and credentials from the backend", async () => {
    renderSettings([{ status: 200, body: providers }])

    await userEvent.click(await screen.findByRole("option", { name: /gpt-4o/ }))

    const modelOption = screen.getByRole("option", { name: /gpt-4o/ })
    expect(within(modelOption).getByText("OpenAI")).toBeDefined()
    expect(screen.getByText("****1234")).toBeDefined()
    expect(screen.getByText("In use")).toBeDefined()
    expect(screen.getByRole("button", { name: "Remove gpt-4o" }).hasAttribute("disabled")).toBe(true)
    expect(screen.getByRole("button", { name: "Remove prod" }).hasAttribute("disabled")).toBe(false)
  })

  it("reports backend failures while loading", async () => {
    renderSettings([{ status: 500, body: { message: "boom" } }])

    expect(await screen.findByText("Could not load AI providers")).toBeDefined()
  })

  it("shows skeleton rows while loading", () => {
    globalThis.fetch = (() => new Promise(() => {})) as typeof fetch
    globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket
    render(
      <ToastProvider>
        <SettingsPage />
        <Dock />
      </ToastProvider>
    )

    expect(document.querySelectorAll(".ui-item-list-skeleton").length).toBe(6)
  })

  it("registers a model toasting success", async () => {
    const withNewModel = [{
      id: 1,
      name: "OpenAI",
      models: [{ id: 10, name: "gpt-4o", inUse: true }, { id: 11, name: "o1", inUse: false }],
      credentials: [],
    }]
    renderSettings([
      { status: 200, body: providers },
      { status: 201, body: { id: 11, name: "o1", inUse: false } },
      { status: 200, body: withNewModel },
    ])

    await screen.findByRole("option", { name: /gpt-4o/ })
    await userEvent.click(screen.getByRole("button", { name: "Add model" }))

    const dialog = screen.getByRole("dialog", { name: "Add a model" })
    await userEvent.click(within(dialog).getByRole("button", { name: "Select a provider..." }))
    await userEvent.click(within(dialog).getByRole("option", { name: "OpenAI" }))
    await userEvent.type(within(dialog).getByPlaceholderText("Insert the model name..."), "o1")
    await userEvent.click(within(dialog).getByRole("button", { name: "Submit" }))

    expect(await screen.findByRole("option", { name: /o1/ })).toBeDefined()
    expect(screen.queryByRole("dialog")).toBeNull()
    expect(await screen.findByText("Model o1 registered")).toBeDefined()
  })

  it("toasts registration failures keeping the modal open", async () => {
    renderSettings([
      { status: 200, body: providers },
      { status: 409, body: { message: "Model gpt-4o is already registered" } },
    ])

    await screen.findByRole("option", { name: /gpt-4o/ })
    await userEvent.click(screen.getByRole("button", { name: "Add model" }))

    const dialog = screen.getByRole("dialog", { name: "Add a model" })
    await userEvent.click(within(dialog).getByRole("button", { name: "Select a provider..." }))
    await userEvent.click(within(dialog).getByRole("option", { name: "OpenAI" }))
    await userEvent.type(within(dialog).getByPlaceholderText("Insert the model name..."), "gpt-4o")
    await userEvent.click(within(dialog).getByRole("button", { name: "Submit" }))

    expect(await screen.findAllByText("Model gpt-4o is already registered")).toHaveLength(2)
    expect(screen.getByRole("dialog", { name: "Add a model" })).toBeDefined()
  })

  it("removes a credential toasting success", async () => {
    const withoutCredential = [{
      id: 1,
      name: "OpenAI",
      models: [{ id: 10, name: "gpt-4o", inUse: true }],
      credentials: [],
    }]
    const calls = renderSettings([
      { status: 200, body: providers },
      { status: 204 },
      { status: 200, body: withoutCredential },
    ])

    await screen.findByRole("option", { name: /prod/ })
    await userEvent.click(screen.getByRole("button", { name: "Remove prod" }))

    expect(await screen.findByText("Credential prod deleted")).toBeDefined()
    expect(screen.queryByRole("button", { name: "Remove prod" })).toBeNull()
    expect(calls[1]?.url).toContain("/api/ai-providers/1/credentials/20")
  })

  it("toasts deletion failures", async () => {
    renderSettings([
      { status: 200, body: providers },
      { status: 409, body: { message: "Model gpt-4o is assigned to an agent" } },
    ])

    await screen.findByRole("option", { name: /gpt-4o/ })
    await userEvent.click(screen.getByRole("button", { name: "Remove prod" }))

    expect(await screen.findByText("Model gpt-4o is assigned to an agent")).toBeDefined()
    expect(screen.getByRole("button", { name: "Remove prod" })).toBeDefined()
  })
})
