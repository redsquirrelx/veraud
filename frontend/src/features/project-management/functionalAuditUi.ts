/** UI policy only. Both functional modes and their wire contracts remain on the server. */
export const FUNCTIONAL_AUDIT_MODES = {
  exploratory: { visible: true, labelKey: "qualityAudits.setup.functionalExploratory" },
  requirements_based: { visible: false, labelKey: "qualityAudits.setup.functionalRequirementsBased" },
} as const

/** Exploration uses no provider, embeddings, model calls or token budgets. */
export function isExploratoryFunctionalField(path: string[]): boolean {
  return path.length === 2 && path[0] === "functional_config"
    && ["timeout_seconds", "max_wall_time_seconds", "cancellation_grace_seconds"].includes(path[1]!)
}
