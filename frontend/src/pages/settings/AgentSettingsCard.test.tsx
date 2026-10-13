import { useState } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { AgentSettingsCard } from "./AgentSettingsCard.tsx"
import type { AgentSettings, AiProviderDetail } from "../../infrastructure/http-client/httpClient.ts"

const providers: AiProviderDetail[] = [
  { id: 1, name: "OpenAI", models: [{ id: 10, name: "model-a", inUse: false }, { id: 11, name: "model-b", inUse: false }], credentials: [{ id: 20, name: "openai-key", apiKeyPreview: "****1234", inUse: false }] },
  { id: 2, name: "Google", models: [{ id: 12, name: "model-c", inUse: false }], credentials: [{ id: 21, name: "google-key", apiKeyPreview: "****5678", inUse: false }] },
]
const savedAgent: AgentSettings = {
  agentType: "dummy", configured: true,
  configuration: {
    model: { id: 12, name: "model-c", providerId: 2, providerName: "Google" },
    credential: { id: 21, name: "google-key", providerId: 2, providerName: "Google" },
    temperature: null, maxTokens: null,
  },
}

function EditableCard() {
  const [agent, setAgent] = useState<AgentSettings>({ agentType: "dummy", configured: false, configuration: null })
  return <AgentSettingsCard agent={agent} providers={providers} providersLoading={false} onSaved={setAgent} onVerified={setAgent} onConfigure={() => {}} />
}

afterEach(() => vi.unstubAllGlobals())

describe("AgentSettingsCard", () => {
  it("filters credentials, clears them on provider changes, retains them for same-provider models and saves", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(savedAgent), { status: 200 }))
    vi.stubGlobal("fetch", fetch)
    const user = userEvent.setup()
    render(<EditableCard />)
    expect(screen.getByRole("button", { name: "Select a model first" })).toBeDisabled()
    await user.click(screen.getByRole("button", { name: "Select a model..." }))
    await user.click(screen.getByRole("option", { name: /model-a/ }))
    await user.click(screen.getByRole("button", { name: "Select a credential..." }))
    expect(screen.queryByRole("option", { name: /google-key/ })).toBeNull()
    await user.click(screen.getByRole("option", { name: /openai-key/ }))
    await user.click(screen.getByRole("button", { name: "model-a" }))
    await user.click(screen.getByRole("option", { name: /model-b/ }))
    expect(screen.getByRole("button", { name: "openai-key" })).toBeEnabled()
    await user.click(screen.getByRole("button", { name: "model-b" }))
    await user.click(screen.getByRole("option", { name: /model-c/ }))
    expect(screen.getByRole("button", { name: "Select a credential..." })).toBeDefined()
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled()
    await user.click(screen.getByRole("button", { name: "Select a credential..." }))
    expect(screen.queryByRole("option", { name: /openai-key/ })).toBeNull()
    await user.click(screen.getByRole("option", { name: /google-key/ }))
    await user.click(screen.getByRole("button", { name: "Save changes" }))
    expect(await screen.findByRole("status")).toHaveTextContent("Configuration saved.")
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/api/agent-settings/dummy"), expect.objectContaining({
      method: "PUT", body: JSON.stringify({ modelId: 12, credentialId: 21 }),
    }))
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled()
    expect(screen.getByText("Configured")).toBeDefined()
  })

  it("keeps selections on failure and disables controls while saving", async () => {
    let resolve!: (response: Response) => void
    const fetch = vi.fn().mockImplementation(() => new Promise<Response>((done) => { resolve = done }))
    vi.stubGlobal("fetch", fetch)
    const user = userEvent.setup()
    render(<EditableCard />)
    await user.click(screen.getByRole("button", { name: "Select a model..." }))
    await user.click(screen.getByRole("option", { name: /model-c/ }))
    await user.click(screen.getByRole("button", { name: "Select a credential..." }))
    await user.click(screen.getByRole("option", { name: /google-key/ }))
    await user.click(screen.getByRole("button", { name: "Save changes" }))
    expect(screen.getByRole("button", { name: "Saving..." })).toBeDisabled()
    expect(screen.getByRole("button", { name: "model-c" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "google-key" })).toBeDisabled()
    resolve(new Response(JSON.stringify({ message: "Credential no longer exists" }), { status: 422 }))
    expect(await screen.findByRole("alert")).toHaveTextContent("Credential no longer exists")
    expect(screen.getByRole("button", { name: "model-c" })).toBeEnabled()
    expect(screen.getByRole("button", { name: "google-key" })).toBeEnabled()
    await waitFor(() => expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled())
    expect(fetch).toHaveBeenCalledTimes(1)
  })
})
