import type { AgentExecution } from "../../infrastructure/http-client/httpClient.ts"

/** Keep captured configuration and monotonic usage across HTTP and socket updates. */
export function mergeExecution(previous: AgentExecution | null | undefined, incoming: AgentExecution): AgentExecution {
  if (!previous) return incoming
  const rank = (execution: AgentExecution) => execution.status === "Waiting" ? 0 : execution.status === "Running" ? 1 : 2
  const lifecycle = rank(previous) > rank(incoming) ? previous : incoming
  const count = (old: number | null | undefined, next: number | null | undefined) =>
    old == null ? next ?? null : next == null ? old : Math.max(old, next)
  return {
    ...previous, ...incoming, ...lifecycle,
    configuration: incoming.configuration ?? previous.configuration ?? null,
    inputTokens: count(previous.inputTokens, incoming.inputTokens),
    outputTokens: count(previous.outputTokens, incoming.outputTokens),
    estimatedTokens: count(previous.estimatedTokens, incoming.estimatedTokens),
    interruptionReason: lifecycle.interruptionReason ?? previous.interruptionReason ?? incoming.interruptionReason ?? null,
  }
}
