import { afterEach, beforeAll, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { changeLanguage, initializeI18n } from "../../shared/i18n/index.ts"
import { AuditSettingsDrawer } from "./AuditSettingsDrawer.tsx"

beforeAll(async () => { await initializeI18n("en") })
afterEach(async () => { vi.unstubAllGlobals(); await changeLanguage("en") })

it("loads saved values, accepts a large shared budget and saves category operating overrides", async () => {
  const schema = { type: "object", properties: {
    audit_budget: { type: "object", properties: { max_total_tokens: { type: "integer", minimum: 1000 } } },
    functional_config: { type: "object", properties: { retrieval_top_k: { type: "integer", minimum: 1, maximum: 20 } } },
    agent_defaults: { type: "object", properties: {
      max_context_characters: { type: "integer", minimum: 1000 },
      max_output_tokens: { type: "integer", minimum: 256, default: 4000 },
    } },
  } }
  const fetch = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ schema,
    values: { functional_config: { retrieval_top_k: 3 }, agent_defaults: { max_output_tokens: 8000 } } })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ values: {} })))
  vi.stubGlobal("fetch", fetch)
  const close = vi.fn()
  render(<AuditSettingsDrawer attribute="functional_adequacy" label="Functional adequacy" open onClose={close} />)
  const retrieval = await screen.findByLabelText("Maximum retrieved results")
  expect(retrieval).toHaveValue(3)
  const output = screen.getByLabelText("Maximum output tokens per call")
  expect(output).toHaveValue(8000)
  await userEvent.clear(output)
  await userEvent.type(output, "255")
  expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled()
  await userEvent.clear(output)
  await userEvent.type(output, "16000")
  await userEvent.type(screen.getByLabelText("Shared total token budget"), "300000000000")
  await userEvent.clear(retrieval)
  await userEvent.type(retrieval, "0")
  expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled()
  await userEvent.clear(retrieval)
  await userEvent.type(retrieval, "4")
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }))
  await waitFor(() => expect(close).toHaveBeenCalledOnce())
  expect(fetch.mock.calls[1]?.[1]).toMatchObject({ method: "PUT", body: JSON.stringify({
    audit_budget: { max_total_tokens: 300000000000 }, functional_config: { retrieval_top_k: 4 },
    agent_defaults: { max_output_tokens: 16000 },
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

it("offers one output control when the legacy security schema also declares it", async () => {
  const output = { type: "integer", minimum: 256, default: 4000 }
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ schema: { properties: {
    agent_defaults: { properties: { max_output_tokens: output } },
    security_config: { properties: { max_output_tokens: output, max_scan_files: { type: "integer" } } },
  } }, values: { agent_defaults: { max_output_tokens: 16000 } } }))))
  render(<AuditSettingsDrawer attribute="security" label="Security" open onClose={vi.fn()} />)
  expect(await screen.findByLabelText("Maximum output tokens per call")).toHaveValue(16000)
  expect(screen.getAllByLabelText("Maximum output tokens per call")).toHaveLength(1)
  expect(screen.getByLabelText("Maximum files to scan")).toBeVisible()
})

it("translates known field labels without discarding edits", async () => {
  const descriptor = {
    schema: { properties: { audit_budget: { properties: { max_total_tokens: { type: "integer", minimum: 1000 } } } } },
    values: { audit_budget: { max_total_tokens: 3000 } },
  }
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(descriptor))))
  render(<AuditSettingsDrawer attribute="maintainability" label="Maintainability" open onClose={vi.fn()} />)
  const budget = await screen.findByLabelText("Shared total token budget")
  await userEvent.clear(budget)
  await userEvent.type(budget, "5000")

  await changeLanguage("es")

  expect(screen.getByLabelText("Presupuesto total compartido de tokens")).toHaveValue(5000)
  expect(screen.getByRole("button", { name: "Guardar cambios" })).toBeEnabled()
  expect(fetch).toHaveBeenCalledTimes(1)
})
