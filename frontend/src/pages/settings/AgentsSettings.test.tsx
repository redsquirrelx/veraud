import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { AgentsSettings } from "./AgentsSettings.tsx"

afterEach(() => vi.unstubAllGlobals())

describe("AgentsSettings", () => {
  it("renders discovered types including unconfigured agents and shows saved configuration", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify([
      { agentType: "analyzer", configured: true, configuration: {
        model: { id: 1, name: "example", providerId: 1, providerName: "OpenAI" },
        credential: { id: 2, name: "production", providerId: 1, providerName: "OpenAI" },
        temperature: 0, maxTokens: 1024,
      } },
      { agentType: "new-agent", configured: false, configuration: null },
    ]), { status: 200 }))
    vi.stubGlobal("fetch", fetch)
    const user = userEvent.setup()
    render(<AgentsSettings providers={[{ id: 1, name: "OpenAI", models: [{ id: 1, name: "example", inUse: true }], credentials: [{ id: 2, name: "production", apiKeyPreview: "****1234", inUse: true }] }]} />)
    expect(await screen.findByRole("heading", { name: "new-agent" })).toBeDefined()
    expect(screen.getByText("Not configured")).toBeDefined()
    expect(screen.getByText("Configured")).toBeDefined()
    expect(fetch.mock.calls[0]?.[0]).toContain("/api/agent-settings")
    await user.click(screen.getByRole("button", { name: "Configure analyzer" }))
    const drawer = screen.getByRole("dialog", { name: "Configure analyzer" })
    expect(within(drawer).getByRole("button", { name: "example" })).toBeEnabled()
    expect(within(drawer).getByRole("button", { name: "production" })).toBeEnabled()
    expect(within(drawer).getByRole("spinbutton", { name: /Temperature/ })).toHaveValue(0)
    expect(within(drawer).getByRole("spinbutton", { name: /Maximum tokens/ })).toHaveValue(1024)
    expect(within(drawer).getByRole("button", { name: "Save changes" })).toBeDisabled()
  })

  it("shows catalog failures and reloads on retry", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ message: "Could not load agent settings" }), { status: 500 }))
      .mockResolvedValueOnce(new Response("[]", { status: 200 }))
    vi.stubGlobal("fetch", fetch)
    render(<AgentsSettings />)
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load agent settings")
    await userEvent.click(screen.getByRole("button", { name: "Retry" }))
    expect(await screen.findByText("No agent types are declared in the backend.")).toBeDefined()
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(screen.queryByRole("alert")).toBeNull()
  })

  it("edits and saves drawer selections and generation parameters, retaining values on failure", async () => {
    const configuration = {
      model: { id: 1, name: "example", providerId: 1, providerName: "OpenAI" },
      credential: { id: 2, name: "production", providerId: 1, providerName: "OpenAI" },
      temperature: 0.5, maxTokens: 1024,
    }
    const updated = { agentType: "analyzer", configured: true, configuration: {
      ...configuration, model: { ...configuration.model, id: 3, name: "new-model" }, temperature: 0, maxTokens: null,
    } }
    const fetch = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([{ agentType: "analyzer", configured: true, configuration }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ message: "Save failed" }), { status: 500 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(updated), { status: 200 }))
    vi.stubGlobal("fetch", fetch)
    const onSaved = vi.fn()
    const user = userEvent.setup()
    render(<AgentsSettings providers={[{ id: 1, name: "OpenAI", models: [{ id: 1, name: "example", inUse: true }, { id: 3, name: "new-model", inUse: false }], credentials: [{ id: 2, name: "production", apiKeyPreview: "****1234", inUse: true }] }]} onAssignmentsSaved={onSaved} />)
    await user.click(await screen.findByRole("button", { name: "Configure analyzer" }))
    const drawer = within(screen.getByRole("dialog", { name: "Configure analyzer" }))
    await user.click(drawer.getByRole("button", { name: "example" }))
    await user.click(screen.getByRole("option", { name: /new-model/ }))
    const temperature = drawer.getByRole("spinbutton", { name: /Temperature/ })
    await user.clear(temperature)
    await user.type(temperature, "3")
    expect(drawer.getByRole("button", { name: "Save changes" })).toBeDisabled()
    await user.clear(temperature)
    await user.type(temperature, "0")
    await user.clear(drawer.getByRole("spinbutton", { name: /Maximum tokens/ }))
    await user.click(drawer.getByRole("button", { name: "Save changes" }))
    expect(await drawer.findByRole("alert")).toHaveTextContent("Save failed")
    expect(temperature).toHaveValue(0)
    expect(onSaved).not.toHaveBeenCalled()
    await user.click(drawer.getByRole("button", { name: "Save changes" }))
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(updated))
    expect(fetch).toHaveBeenLastCalledWith(expect.stringContaining("/api/agent-settings/analyzer"), expect.objectContaining({
      method: "PUT", body: JSON.stringify({ modelId: 3, credentialId: 2, temperature: 0, maxTokens: null }),
    }))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(screen.getByRole("button", { name: "new-model" })).toBeDefined()
    await user.click(screen.getByRole("button", { name: "Configure analyzer" }))
    expect(within(screen.getByRole("dialog")).getByRole("spinbutton", { name: /Temperature/ })).toHaveValue(0)
    expect(within(screen.getByRole("dialog")).getByRole("spinbutton", { name: /Maximum tokens/ })).toHaveValue(null)
  })

  it("cancels requests when leaving the agents section", async () => {
    const fetch = vi.fn().mockImplementation(() => new Promise(() => {}))
    vi.stubGlobal("fetch", fetch)
    const { unmount } = render(<AgentsSettings />)
    await waitFor(() => expect(fetch).toHaveBeenCalledOnce())
    const signal = fetch.mock.calls[0]?.[1].signal as AbortSignal
    expect(signal.aborted).toBe(false)
    unmount()
    expect(signal.aborted).toBe(true)
  })
})
