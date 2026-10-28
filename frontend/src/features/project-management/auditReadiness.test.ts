import { describe, expect, it } from "vitest"
import type { AgentSettings } from "../../infrastructure/http-client/httpClient.ts"
import { auditReadiness } from "./auditReadiness.ts"

const agent = (agentType: string, options: Partial<AgentSettings> = {}): AgentSettings => ({
  agentType, configured: true, configuration: null, qualityAttributes: [], workflowIds: [], availability: "available", requiresModel: true, ...options,
})

describe("audit readiness", () => {
  it("checks only selected roots and accepts model access that will be verified on start", () => {
    expect(auditReadiness([agent("security"), agent("functional_adequacy", { configured: false })], ["security"])).toEqual([])
    expect(auditReadiness([agent("maintainability_manager")], ["maintainability"])).toEqual([])
  })
  it("reports missing, unavailable, unconfigured and failed model access", () => {
    expect(auditReadiness([], ["security"])).toEqual([{ attribute: "security", reason: "unavailable" }])
    expect(auditReadiness([agent("security", { availability: "not_executed" })], ["security"])).toEqual([{ attribute: "security", reason: "unavailable" }])
    expect(auditReadiness([agent("functional_adequacy", { configured: false })], ["functional_adequacy"])).toEqual([{ attribute: "functional_adequacy", reason: "unconfigured" }])
    expect(auditReadiness([agent("security", { verification: { status: "failed", checkedAt: null, message: "Unavailable" } })], ["security"]))
      .toEqual([{ attribute: "security", reason: "verificationFailed" }])
  })
  it("resolves inherited model ownership without requiring models for deterministic participants", () => {
    expect(auditReadiness([agent("security", { configured: false, modelConfigurationAgentType: "owner" }), agent("owner")], ["security"])).toEqual([])
    expect(auditReadiness([agent("security", { configured: false, requiresModel: false })], ["security"])).toEqual([])
  })
})
