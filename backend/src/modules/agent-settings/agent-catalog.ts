/** Wire metadata is owned by agent-server. No backend list of agent identities. */
export interface CatalogAgent {
  agent_id: string
  name: string
  role: string
  requires_model: boolean
  model_configuration_id: string | null
  execution_modes: string[]
  quality_attributes: string[]
  workflow_ids: string[]
  parent_ids: string[]
  child_ids: string[]
  availability: "available" | "not_executed"
}

export interface AgentCatalog {
  schema_version: "1.0"
  agents: CatalogAgent[]
}

export interface AgentCatalogSource {
  getAgentCatalog(): Promise<AgentCatalog>
}

export class AgentCatalogError extends Error {
  constructor(message = "Agent-server catalog is unavailable or invalid; the last synchronized catalog was preserved") {
    super(message)
    this.name = "AgentCatalogError"
  }
}

/** Validate the complete graph before any write. Ignore unrelated wire extensions. */
export function parseAgentCatalog(value: unknown): AgentCatalog {
  const invalid = (): never => { throw new AgentCatalogError("Agent-server returned an invalid agent catalog") }
  const object = (item: unknown): Record<string, unknown> => item !== null && typeof item === "object" && !Array.isArray(item) ? item as Record<string, unknown> : invalid()
  const text = (item: unknown): string => typeof item === "string" && item.trim().length > 0 ? item : invalid()
  const strings = (item: unknown): string[] => {
    if (!Array.isArray(item)) return invalid()
    const result = item.map(text)
    return new Set(result).size === result.length ? result : invalid()
  }
  const wire = object(value)
  if (wire.schema_version !== "1.0" || !Array.isArray(wire.agents)) return invalid()
  const agents: CatalogAgent[] = wire.agents.map((item: unknown) => {
    const row = object(item)
    if (typeof row.requires_model !== "boolean" || !["available", "not_executed"].includes(String(row.availability))) return invalid()
    const modes = strings(row.execution_modes)
    if (!modes.length || modes.some((mode) => !["direct", "pipeline", "audit", "internal", "snapshot"].includes(mode))) return invalid()
    const modelId = row.model_configuration_id === null ? null : text(row.model_configuration_id)
    if (row.requires_model !== (modelId !== null)) return invalid()
    return { agent_id: text(row.agent_id), name: text(row.name), role: text(row.role),
      requires_model: row.requires_model, model_configuration_id: modelId, execution_modes: modes,
      quality_attributes: strings(row.quality_attributes), workflow_ids: strings(row.workflow_ids),
      parent_ids: strings(row.parent_ids), child_ids: strings(row.child_ids),
      availability: row.availability as CatalogAgent["availability"] }
  })
  const byId = new Map(agents.map((agent) => [agent.agent_id, agent]))
  if (byId.size !== agents.length) return invalid()
  for (const agent of agents) {
    if (agent.model_configuration_id !== null && !byId.get(agent.model_configuration_id)?.requires_model) return invalid()
    for (const parent of agent.parent_ids) {
      if (parent === agent.agent_id || !byId.get(parent)?.child_ids.includes(agent.agent_id)) return invalid()
    }
    for (const child of agent.child_ids) {
      if (child === agent.agent_id || !byId.get(child)?.parent_ids.includes(agent.agent_id)) return invalid()
    }
  }
  const visiting = new Set<string>()
  const visited = new Set<string>()
  const visit = (id: string): void => {
    if (visiting.has(id)) invalid()
    if (visited.has(id)) return
    visiting.add(id)
    for (const child of byId.get(id)!.child_ids) visit(child)
    visiting.delete(id)
    visited.add(id)
  }
  for (const agent of agents) visit(agent.agent_id)
  return { schema_version: "1.0", agents }
}
