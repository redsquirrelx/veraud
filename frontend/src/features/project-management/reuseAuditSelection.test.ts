import { describe, expect, it } from "vitest"
import type { AgentSettings } from "../../infrastructure/http-client/httpClient.ts"
import type { AuditRunConfiguration } from "./qualityAuditApi.ts"
import { reuseAuditSelection } from "./reuseAuditSelection.ts"

function agent(agentType: string, overrides: Partial<AgentSettings> = {}): AgentSettings {
  return { agentType, qualityAttributes: ["maintainability"], workflowIds: [], configured: false, configuration: null, ...overrides }
}

const saved: AuditRunConfiguration = { version: 1, branch: "old-branch", commitHash: "b".repeat(40), attributes: ["maintainability", "security"], scopes: [
  { id: "maintainability", requiredAgents: [], techniques: [], investigators: [], subcharacteristics: [
    { id: "modularity", name: "Modularity", investigators: [{ id: "responsibility", name: "Responsibility" }] },
  ] },
  { id: "security", requiredAgents: [], techniques: [{ id: "sast", name: "SAST" }], investigators: [], subcharacteristics: [] },
] }

describe("reuse audit selections", () => {
  it("copies the original selection without adding newly registered investigators or mutating history", () => {
    const before = JSON.stringify(saved)
    const result = reuseAuditSelection(saved, [
      agent("modularity"), agent("responsibility", { role: "investigator", parentAgentTypes: ["modularity"] }),
      agent("new_investigator", { role: "investigator", parentAgentTypes: ["modularity"] }),
      agent("security", { childAgentTypes: ["sast"] }), agent("sast"),
    ])
    expect(result).toEqual({ maintainability: { modularity: ["responsibility"] }, security: true, functionalAdequacy: false, adjusted: false })
    result.maintainability.modularity!.push("new_investigator")
    expect(JSON.stringify(saved)).toBe(before)
  })

  it("drops unavailable investigators and incompatible techniques rather than silently replacing them", () => {
    const result = reuseAuditSelection(saved, [
      agent("modularity"), agent("responsibility", { role: "investigator", parentAgentTypes: ["modularity"], availability: "not_executed" }),
      agent("security", { childAgentTypes: ["sast", "new_technique"] }), agent("sast"), agent("new_technique"),
    ])
    expect(result).toEqual({ maintainability: {}, security: false, functionalAdequacy: false, adjusted: true })
  })
})
