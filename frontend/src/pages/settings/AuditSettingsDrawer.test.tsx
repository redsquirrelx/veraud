import { afterEach, beforeAll, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { initializeI18n } from "../../shared/i18n/index.ts"
import { AuditSettingsDrawer } from "./AuditSettingsDrawer.tsx"

beforeAll(async () => { await initializeI18n("en") })
afterEach(() => { vi.unstubAllGlobals() })

it("loads saved values, accepts a large shared budget and saves category operating overrides", async () => {
  const schema = { type: "object", properties: {
    audit_budget: { type: "object", properties: { max_total_tokens: { type: "integer", minimum: 1000 } } },
    functional_config: { type: "object", properties: { retrieval_top_k: { type: "integer", minimum: 1, maximum: 20 } } },
    agent_defaults: { type: "object", properties: { max_context_characters: { type: "integer", minimum: 1000 } } },
  } }
  const fetch = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ schema,
    values: { functional_config: { retrieval_top_k: 3 } } })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ values: {} })))
  vi.stubGlobal("fetch", fetch)
  const close = vi.fn()
  render(<AuditSettingsDrawer attribute="functional_adequacy" label="Functional adequacy" open onClose={close} />)
  const retrieval = await screen.findByLabelText("retrieval_top_k")
  expect(retrieval).toHaveValue(3)
  await userEvent.type(screen.getByLabelText("max_total_tokens"), "300000000000")
  await userEvent.clear(retrieval)
  await userEvent.type(retrieval, "0")
  expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled()
  await userEvent.clear(retrieval)
  await userEvent.type(retrieval, "4")
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }))
  await waitFor(() => expect(close).toHaveBeenCalledOnce())
  expect(fetch.mock.calls[1]?.[1]).toMatchObject({ method: "PUT", body: JSON.stringify({
    audit_budget: { max_total_tokens: 300000000000 }, functional_config: { retrieval_top_k: 4 },
  }) })
})

it("cancels without saving loaded settings", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ schema: { type: "object" }, values: {} })))
  vi.stubGlobal("fetch", fetch)
  const close = vi.fn()
  render(<AuditSettingsDrawer attribute="security" label="Security" open onClose={close} />)
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }))
  expect(close).toHaveBeenCalledOnce()
  expect(fetch).toHaveBeenCalledTimes(1)
})
