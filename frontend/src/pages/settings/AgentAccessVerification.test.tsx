import { useState } from "react"
import { afterEach, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { AgentAccessVerification } from "./AgentAccessVerification.tsx"
import type { AgentSettings } from "../../infrastructure/http-client/httpClient.ts"

const agent: AgentSettings = { agentType: "analyzer", configured: true, configuration: {
  model: { id: 1, name: "model", providerId: 1, providerName: "OpenAI" },
  credential: { id: 2, name: "credential", providerId: 1, providerName: "OpenAI" },
  temperature: null, maxTokens: null,
}, verification: { status: "not_verified", checkedAt: null, message: null } }

function Verification() {
  const [current, setCurrent] = useState(agent)
  return <AgentAccessVerification agent={current} disabled={false} onUpdated={setCurrent} />
}

afterEach(() => vi.unstubAllGlobals())

it("shows failed access and can retry to verified", async () => {
  const fetch = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...agent, verification: { status: "failed", checkedAt: "2026-10-12T00:00:00Z", message: "Model access denied" } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...agent, verification: { status: "verified", checkedAt: "2026-10-12T00:00:00Z", message: null } }), { status: 200 }))
  vi.stubGlobal("fetch", fetch)
  const user = userEvent.setup()
  render(<Verification />)
  expect(screen.getByText("Not verified")).toBeDefined()
  await user.click(screen.getByRole("button", { name: "Verify access" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("Model access denied")
  expect(screen.getByText("Needs attention")).toBeDefined()
  await user.click(screen.getByRole("button", { name: "Verify access" }))
  expect(await screen.findByText("Verified")).toBeDefined()
  expect(screen.queryByRole("alert")).toBeNull()
  expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/api/agent-settings/analyzer/verify"), { method: "POST" })
})

it("requires saved assignments before verifying", () => {
  render(<AgentAccessVerification agent={agent} disabled onUpdated={() => {}} />)
  expect(screen.getByRole("button", { name: "Verify access" })).toBeDisabled()
  expect(screen.getByText("Save your changes before verifying access.")).toBeDefined()
})
