import { expect, it } from "vitest"
import { configFields, auditDraftValues, preserveHiddenSettings } from "./auditOperatingSettingsApi.ts"
import { FUNCTIONAL_AUDIT_MODES } from "./functionalAuditUi.ts"

it("keeps requirements-based mode explicitly hidden without removing its identity", () => {
  expect(FUNCTIONAL_AUDIT_MODES.exploratory.visible).toBe(true)
  expect(FUNCTIONAL_AUDIT_MODES.requirements_based.visible).toBe(false)
  expect(FUNCTIONAL_AUDIT_MODES.exploratory.labelKey).not.toBe(FUNCTIONAL_AUDIT_MODES.requirements_based.labelKey)
})

it("filters stale LLM drafts and can clear a visible limit without deleting hidden configuration", () => {
  const descriptor = { schema: { properties: {
    functional_config: { properties: { timeout_seconds: { type: "number" }, retrieval_top_k: { type: "integer" } } },
    agent_defaults: { properties: { max_model_calls: { type: "integer" } } },
  } }, values: { functional_config: { timeout_seconds: 30, retrieval_top_k: 7 }, agent_defaults: { max_model_calls: 50 } } }
  const form = { "functional_config.timeout_seconds": "", "functional_config.retrieval_top_k": "2", "agent_defaults.max_model_calls": "4" }
  expect(auditDraftValues("functional_adequacy", { descriptor, form })).toEqual({})
  expect(preserveHiddenSettings(descriptor, configFields(descriptor.schema, "functional_adequacy"), form)).toEqual({
    functional_config: { retrieval_top_k: 7 }, agent_defaults: { max_model_calls: 50 },
  })
  expect(descriptor.values.functional_config.timeout_seconds).toBe(30)
})
