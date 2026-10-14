import type { AgentExecution } from "../../infrastructure/http-client/httpClient.ts"
import "./AgentTokenUsage.css"

const numberFormat = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 })
const format = (value: number) => numberFormat.format(value)

export function AgentTokenUsage({ execution }: { execution: AgentExecution }) {
  const input = execution.inputTokens
  const output = execution.outputTokens
  const estimated = execution.estimatedTokens ?? 0
  const reported = input != null || output != null || estimated > 0
  const total = (input ?? 0) + (output ?? 0) + estimated
  const budget = execution.configuration?.tokenBudget
  const absolute = execution.configuration?.absoluteTokenLimit
  const percentage = budget != null && budget > 0 ? total / budget * 100 : null
  const exhausted = execution.interruptionReason === "token_budget_exhausted" || (reported && absolute != null && total >= absolute)
  const tolerance = reported && budget != null && total > budget
  const state = exhausted ? "exhausted" : tolerance ? "tolerance" : "normal"
  const label = exhausted ? "Absolute limit reached" : tolerance ? absolute != null ? "In tolerance" : "Initial budget exceeded" : "Within budget"

  return <div className={`agent-token-usage agent-token-${state}`} aria-label={`Token usage for ${execution.agentType} run ${execution.id}`}>
    <div className="agent-token-summary">
      <span>{reported ? `${(input == null || output == null) && estimated === 0 ? "Reported: " : ""}${format(total)}${budget != null ? ` / ${format(budget)}` : ""} tokens` : "Token usage not reported"}</span>
      {reported && percentage !== null && <strong>{format(percentage)}%</strong>}
    </div>
    {reported && budget != null && <>
      <progress className="agent-token-bar" value={total} max={absolute ?? budget} aria-label="Token budget usage"
        aria-valuetext={`${format(total)} tokens, ${format(percentage ?? 0)}% of initial budget. ${label}.`} />
    </>}
    {(reported && budget != null || exhausted) && <span className="agent-token-state">{label}</span>}
    <span className="agent-token-note">{absolute != null ? `Absolute limit: ${format(absolute)} tokens` : "No absolute limit recorded"}</span>
    {budget == null && <span className="agent-token-note">No initial budget recorded</span>}
    {estimated > 0 && <span className="agent-token-note">Includes {format(estimated)} estimated tokens</span>}
    {reported && <details className="agent-token-breakdown">
      <summary>Token breakdown</summary>
      <dl>
        <dt>Input (reported)</dt><dd>{input == null ? "Not reported" : format(input)}</dd>
        <dt>Output (reported)</dt><dd>{output == null ? "Not reported" : format(output)}</dd>
        <dt>Estimated</dt><dd>{execution.estimatedTokens == null ? "Not reported" : format(estimated)}</dd>
      </dl>
    </details>}
  </div>
}
