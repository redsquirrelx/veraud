import type { AgentCatalog, AgentCatalogSource } from "../../modules/agent-settings/agent-catalog.js"

/** Explicit fake discovery source for tests that do not start a Python server. */
export const TEST_AGENT_TYPES = ["dummy", "orientation", "architecture", "semantic_validation", "maintainability_manager", "security"] as const

export function testAgentCatalog(): AgentCatalog {
  return { schema_version: "1.0", agents: TEST_AGENT_TYPES.map((id) => ({
    agent_id: id, name: id, role: "test_agent", requires_model: true,
    model_configuration_id: id, execution_modes: ["direct"], parent_ids: [], child_ids: [], availability: "available",
    quality_attributes: [], workflow_ids: [],
  })) }
}

export function makeTestAgentCatalogSource(): AgentCatalogSource {
  return { getAgentCatalog: async () => testAgentCatalog() }
}

export const TEST_MAINTAINABILITY_AGENTS = ["maintainability_manager", "modularity", "reusability", "architecture_boundary",
  "responsibility", "dependency_impact", "abstraction", "reuse_opportunity", "component_adaptability",
  "server_only_investigator"]

export function makeQualityAuditCatalogSource(): AgentCatalogSource {
  const catalog = testAgentCatalog()
  const children: Record<string, string[]> = {
    maintainability_manager: ["modularity", "reusability"],
    modularity: ["architecture_boundary", "responsibility", "dependency_impact", "server_only_investigator"],
    reusability: ["abstraction", "reuse_opportunity", "component_adaptability"],
  }
  for (const id of [...TEST_MAINTAINABILITY_AGENTS, "functional_adequacy"]) {
    if (!catalog.agents.some((agent) => agent.agent_id === id)) {
      catalog.agents.push({ ...catalog.agents[0]!, agent_id: id, name: id, model_configuration_id: id })
    }
  }
  for (const agent of catalog.agents) {
    agent.child_ids = children[agent.agent_id] ?? []
    agent.parent_ids = Object.entries(children).filter(([, ids]) => ids.includes(agent.agent_id)).map(([id]) => id)
  }
  return { getAgentCatalog: async () => catalog }
}
