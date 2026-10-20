import type { AgentExecution, AgentInvocation } from "../../infrastructure/http-client/httpClient.ts"

export function mergeInvocations(previous: AgentInvocation[] = [], incoming: AgentInvocation[] = []): AgentInvocation[] {
  const merged = new Map(previous.map((item) => [item.invocation_id, item]))
  for (const item of incoming) {
    const old = merged.get(item.invocation_id)
    const lifecycle = old && old.status !== "running" ? old : item
    const count = (a: number | null | undefined, b: number | null) =>
      a == null ? b : b == null ? a : Math.max(a, b)
    merged.set(item.invocation_id, { ...lifecycle,
      input_tokens: count(old?.input_tokens, item.input_tokens),
      output_tokens: count(old?.output_tokens, item.output_tokens) })
  }
  return [...merged.values()]
}

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
    monitorContext: incoming.monitorContext ?? previous.monitorContext,
    invocations: mergeInvocations(previous.invocations, incoming.invocations),
    result: lifecycle.result ?? previous.result ?? incoming.result,
    inputTokens: count(previous.inputTokens, incoming.inputTokens),
    outputTokens: count(previous.outputTokens, incoming.outputTokens),
    estimatedTokens: count(previous.estimatedTokens, incoming.estimatedTokens),
    interruptionReason: lifecycle.interruptionReason ?? previous.interruptionReason ?? incoming.interruptionReason ?? null,
  }
}
