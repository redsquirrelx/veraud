import { afterEach, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { AgentSettings } from "../../infrastructure/http-client/httpClient.ts"
import { AgentSettingsDrawer } from "./AgentSettingsDrawer.tsx"

afterEach(() => vi.unstubAllGlobals())

it.each([null, 8000])("shows inherited output and persists an override or restores inheritance (initial %s)", async (initial) => {
  const agent: AgentSettings = { agentType: "responsibility", qualityAttributes: ["maintainability"], workflowIds: [],
    configured: true, configuration: {
      model: { id: 1, name: "model", providerId: 1, providerName: "OpenAI" },
      credential: { id: 2, name: "key", providerId: 1, providerName: "OpenAI" },
      temperature: null, maxTokens: initial,
    }, verification: { status: "not_verified", checkedAt: null, message: null } }
  const fetch = vi.fn().mockImplementation(async (_url, init) => new Response(JSON.stringify(init?.method === "PUT" ? agent : {
    schema: { properties: { agent_defaults: { properties: {
      max_output_tokens: { type: "integer", minimum: 256, default: 4000 },
    } } } }, values: { agent_defaults: { max_output_tokens: 16000 } },
  })))
  vi.stubGlobal("fetch", fetch)
  const saved = vi.fn()
  render(<AgentSettingsDrawer agent={agent} open providers={[{ id: 1, name: "OpenAI",
    models: [{ id: 1, name: "model", inUse: true }], credentials: [{ id: 2, name: "key", apiKeyPreview: "****", inUse: true }] }]}
    providersLoading={false} providersError="" onClose={vi.fn()} onSaved={saved} onVerified={vi.fn()} />)
  const output = await screen.findByPlaceholderText("16000")
  expect(output).toHaveValue(initial)
  expect(await screen.findByText(initial === null ? /16,000 tokens per response, inherited/ : /8,000 tokens per response, individual override/)).toBeVisible()
  await userEvent.clear(output)
  if (initial === null) await userEvent.type(output, "24000")
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }))
  await waitFor(() => expect(saved).toHaveBeenCalledOnce())
  const request = fetch.mock.calls.find(([, init]) => init?.method === "PUT")
  expect(JSON.parse(String(request?.[1].body)).maxTokens).toBe(initial === null ? 24000 : null)
})
