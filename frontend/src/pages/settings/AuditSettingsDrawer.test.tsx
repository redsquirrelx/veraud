import { afterEach, beforeAll, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { changeLanguage, initializeI18n } from "../../shared/i18n/index.ts"
import { AuditSettingsDrawer } from "./AuditSettingsDrawer.tsx"

beforeAll(async () => { await initializeI18n("en") })
afterEach(async () => { vi.unstubAllGlobals(); await changeLanguage("en") })

it("only edits exploratory time limits and preserves every hidden LLM setting on save", async () => {
  const schema = { type: "object", properties: {
    audit_budget: { type: "object", properties: { max_total_tokens: { type: "integer", minimum: 1000 } } },
    functional_config: { type: "object", properties: {
      timeout_seconds: { type: "number", exclusiveMinimum: 0 },
      max_wall_time_seconds: { type: "number", exclusiveMinimum: 0 },
      retrieval_top_k: { type: "integer", minimum: 1, maximum: 20 },
      embedding_model: { type: "string" }, provider_request_timeout_seconds: { type: "number" },
    } },
    agent_defaults: { type: "object", properties: {
      max_context_characters: { type: "integer", minimum: 1000 },
      max_output_tokens: { type: "integer", minimum: 256, default: 4000 },
    } },
  } }
  const hidden = { audit_budget: { max_total_tokens: 100000 }, agent_defaults: { max_output_tokens: 8000 },
    functional_config: { timeout_seconds: 30, retrieval_top_k: 3, embedding_model: "saved-embedding-model",
      provider_rate_limits: { requests_per_minute: null, tokens_per_minute: 700000 } } }
  const fetch = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ schema, values: hidden })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ values: {} })))
  vi.stubGlobal("fetch", fetch)
  const close = vi.fn()
  render(<AuditSettingsDrawer attribute="functional_adequacy" label="Functional adequacy · exploratory" open onClose={close} />)
  const timeout = await screen.findByLabelText("timeout_seconds")
  expect(timeout).toHaveValue(30)
  expect(screen.queryByLabelText("Maximum retrieved results")).not.toBeInTheDocument()
  expect(screen.queryByLabelText("Maximum output tokens per call")).not.toBeInTheDocument()
  expect(screen.queryByLabelText("Shared total token budget")).not.toBeInTheDocument()
  expect(screen.queryByLabelText("embedding_model")).not.toBeInTheDocument()
  expect(screen.queryByLabelText("provider_request_timeout_seconds")).not.toBeInTheDocument()
  await userEvent.clear(timeout)
  await userEvent.type(timeout, "0")
  expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled()
  await userEvent.clear(timeout)
  await userEvent.type(timeout, "45")
  await userEvent.type(screen.getByLabelText("max_wall_time_seconds"), "90")
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }))
  await waitFor(() => expect(close).toHaveBeenCalledOnce())
  expect(fetch.mock.calls[1]?.[1]?.method).toBe("PUT")
  expect(JSON.parse(fetch.mock.calls[1]?.[1]?.body)).toEqual({ ...hidden,
    functional_config: { ...hidden.functional_config, timeout_seconds: 45, max_wall_time_seconds: 90 } })
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
