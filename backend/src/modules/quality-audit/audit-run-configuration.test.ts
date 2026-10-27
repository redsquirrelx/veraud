import { it } from "node:test"
import assert from "node:assert/strict"
import type { AgentSettingsView } from "../agent-settings/agent-settings.service.js"
import { auditRunConfiguration } from "./audit-run-configuration.js"

function agent(agentType: string, role: string, childAgentTypes: string[] = [], availability = "available"): AgentSettingsView {
  return { agentType, name: agentType, role, childAgentTypes, availability, parentAgentTypes: [], qualityAttributes: [], workflowIds: [],
    executionModes: [], requiresModel: true, modelConfigurationAgentType: agentType, configured: false, configuration: null,
    verification: { status: "not_verified", checkedAt: null, message: null } }
}

it("snapshots the selected hierarchy and available techniques without mutable catalog references or secrets", () => {
  const agents = [
    agent("maintainability_manager", "manager", ["modularity", "reusability"]),
    agent("modularity", "coordinator", ["responsibility", "dependency_impact"]),
    agent("reusability", "coordinator", ["abstraction"]),
    agent("responsibility", "investigator"), agent("dependency_impact", "investigator"), agent("abstraction", "investigator"),
    agent("security", "security_pipeline", ["sast_scanner", "dast_sandbox"]),
    agent("sast_scanner", "security_component"), agent("dast_sandbox", "security_component", [], "not_executed"),
  ]
  Object.assign(agents[0]!, { api_key: "private-key", temperature: 0.9 })
  const selection = { modularity: ["responsibility"] }
  const snapshot = auditRunConfiguration(agents, "release", "a".repeat(40), ["maintainability", "security"], selection)
  assert.deepEqual(snapshot.scopes[0]!.requiredAgents.map((agent) => agent.id), ["maintainability_manager", "modularity"])
  assert.deepEqual(snapshot.scopes[0]!.subcharacteristics[0]!.investigators, [{ id: "responsibility", name: "responsibility" }])
  assert.deepEqual(snapshot.scopes[1]!.techniques, [{ id: "sast_scanner", name: "sast_scanner" }])
  selection.modularity.length = 0
  agents[3]!.name = "renamed"
  assert.equal(snapshot.scopes[0]!.subcharacteristics[0]!.investigators[0]!.name, "responsibility")
  assert.doesNotMatch(JSON.stringify(snapshot), /private-key|api_key|temperature/)
})
