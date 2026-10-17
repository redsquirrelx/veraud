/** The two limit objects a maintainability audit accepts, mirroring the body of
 *  `POST /api/audits`. They are distinct on purpose: `agent_defaults` sets what
 *  each manager, coordinator and investigator may spend on its own, while
 *  `audit_budget` caps every agent of the run together. */

/** agent-server/config/agents/budgets.py: `TokenBudgetConfig.max_total_tokens`. */
export const MIN_TOTAL_TOKENS = 1_000
/** agent-server/config/agents/developer.py: `AgentDeveloperConfig.max_context_characters`. */
export const MIN_CONTEXT_CHARACTERS = 4_000
/** Widest integer the server contract and its storage both accept. */
export const MAX_LIMIT = 2_147_483_647

export interface AuditAgentDefaults {
  maxContextCharacters: number
  maxTotalTokens: number
}

export interface AuditBudget {
  maxTotalTokens: number
}

export interface AuditConfiguration {
  agentDefaults: AuditAgentDefaults
  auditBudget: AuditBudget
}

/** Seeds the form while no endpoint backs it. Swap for the stored values then. */
export const AUDIT_CONFIGURATION_PLACEHOLDER: AuditConfiguration = {
  agentDefaults: { maxContextCharacters: 160_000, maxTotalTokens: 500_000 },
  auditBudget: { maxTotalTokens: 3_000_000 },
}

/** Raw form text, so a half-typed number never fights the caret. */
export interface AuditLimitForm {
  contextCharacters: string
  agentTokens: string
  auditTokens: string
}

export function auditLimitForm(configuration: AuditConfiguration): AuditLimitForm {
  return {
    contextCharacters: String(configuration.agentDefaults.maxContextCharacters),
    agentTokens: String(configuration.agentDefaults.maxTotalTokens),
    auditTokens: String(configuration.auditBudget.maxTotalTokens),
  }
}

/** Null for anything the server would reject, so the form can refuse it first. */
export function parseLimit(text: string, minimum: number): number | null {
  const value = Number(text.trim())
  return Number.isInteger(value) && value >= minimum && value <= MAX_LIMIT ? value : null
}

/** Tokens the shared budget still has once one agent spends its full allowance. */
export function sharedBudgetHeadroom(auditTokens: number | null, agentTokens: number | null): number | null {
  return auditTokens === null || agentTokens === null ? null : auditTokens - agentTokens
}

/** A shared cap below one agent's allowance would leave that allowance unreachable. */
export function sharedBudgetFits(auditTokens: number | null, agentTokens: number | null): boolean {
  const headroom = sharedBudgetHeadroom(auditTokens, agentTokens)
  return headroom === null || headroom >= 0
}
