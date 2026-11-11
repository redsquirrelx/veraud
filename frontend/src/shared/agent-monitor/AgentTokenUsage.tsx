import { useTranslation } from "react-i18next"
import type { AgentConfiguration, AgentExecution } from "../../infrastructure/http-client/httpClient.ts"
import { formatNumber } from "../i18n/format.ts"
import "./AgentTokenUsage.css"

export type AgentTokenUsageData = Pick<AgentExecution, "agentType" | "inputTokens" | "outputTokens" | "estimatedTokens" | "interruptionReason"> & {
  id: number | string
  configuration?: Pick<AgentConfiguration, "tokenBudget" | "absoluteTokenLimit"> | null
  unknownUsageAttempts?: number
  invocations?: Pick<NonNullable<AgentExecution["invocations"]>[number], "input_tokens" | "output_tokens" | "unknown_usage_attempts">[] | null
}

type TokenUsageReportedFields = Pick<AgentTokenUsageData, "inputTokens" | "outputTokens" | "estimatedTokens" | "invocations">

function sumReported(receipts: number[]) {
  return receipts.length ? receipts.reduce((sum, value) => sum + value, 0) : null
}

/** Whether the execution reported any token usage (direct counts or invocation receipts). */
export function hasReportedTokens(execution: TokenUsageReportedFields): boolean {
  const invokedInputs = (execution.invocations ?? []).flatMap((receipt) => typeof receipt.input_tokens === "number" ? [receipt.input_tokens] : [])
  const invokedOutputs = (execution.invocations ?? []).flatMap((receipt) => typeof receipt.output_tokens === "number" ? [receipt.output_tokens] : [])
  const input = execution.inputTokens ?? sumReported(invokedInputs)
  const output = execution.outputTokens ?? sumReported(invokedOutputs)
  const estimated = execution.estimatedTokens ?? 0
  return input != null || output != null || estimated > 0
}

export function AgentTokenUsage({ execution }: { execution: AgentTokenUsageData }) {
  const { t } = useTranslation("agents")
  const format = (value: number) => formatNumber(value, { maximumFractionDigits: 1 })
  const invokedInputs = (execution.invocations ?? []).flatMap((receipt) => typeof receipt.input_tokens === "number" ? [receipt.input_tokens] : [])
  const invokedOutputs = (execution.invocations ?? []).flatMap((receipt) => typeof receipt.output_tokens === "number" ? [receipt.output_tokens] : [])
  const input = execution.inputTokens ?? sumReported(invokedInputs)
  const output = execution.outputTokens ?? sumReported(invokedOutputs)
  const estimated = execution.estimatedTokens ?? 0
  const reported = hasReportedTokens(execution)
  const unknownAttempts = execution.unknownUsageAttempts
    ?? (execution.invocations ?? []).reduce((sum, receipt) => sum + (receipt.unknown_usage_attempts ?? 0), 0)
  const total = (input ?? 0) + (output ?? 0) + estimated
  const budget = execution.configuration?.tokenBudget
  const absolute = execution.configuration?.absoluteTokenLimit
  const percentage = budget != null && budget > 0 ? total / budget * 100 : null
  const exhausted = execution.interruptionReason === "token_budget_exhausted" || (reported && absolute != null && total >= absolute)
  const tolerance = reported && budget != null && total > budget
  const state = exhausted ? "exhausted" : tolerance ? "tolerance" : "normal"
  const stateKey = exhausted
    ? "tokenUsage.state.exhausted"
    : tolerance
      ? absolute != null ? "tokenUsage.state.inTolerance" : "tokenUsage.state.budgetExceeded"
      : "tokenUsage.state.withinBudget"
  const label = t(stateKey)
  const partialReport = (input == null || output == null) && estimated === 0
  const summaryKey = partialReport
    ? budget != null ? "tokenUsage.summary.reportedWithBudget" : "tokenUsage.summary.reportedTotalOnly"
    : budget != null ? "tokenUsage.summary.withBudget" : "tokenUsage.summary.totalOnly"

  return <div className={`agent-token-usage agent-token-${state}`} aria-label={t("tokenUsage.usageFor", { agentType: execution.agentType, id: execution.id })}>
    <div className="agent-token-summary">
      <span>{reported ? t(summaryKey, { total: format(total), budget: budget != null ? format(budget) : "" }) : t("tokenUsage.notReported")}</span>
      {reported && percentage !== null && <strong>{format(percentage)}%</strong>}
    </div>
    {reported && budget != null && <>
      <progress className="agent-token-bar" value={total} max={absolute ?? budget} aria-label={t("tokenUsage.budgetUsage")}
        aria-valuetext={t("tokenUsage.budgetUsageValue", { total: format(total), percentage: format(percentage ?? 0), state: label })} />
    </>}
    {(reported && budget != null || exhausted) && <span className="agent-token-state">{label}</span>}
    <span className="agent-token-note">{absolute != null ? t("tokenUsage.absoluteLimit", { value: format(absolute) }) : t("tokenUsage.noAbsoluteLimit")}</span>
    {budget == null && <span className="agent-token-note">{t("tokenUsage.noBudget")}</span>}
    {estimated > 0 && <span className="agent-token-note">{t("tokenUsage.includesEstimated", { value: format(estimated) })}</span>}
    {unknownAttempts > 0 && <span className="agent-token-note">{t("tokenUsage.incompleteCount", { count: unknownAttempts })}</span>}
    {reported && <details className="agent-token-breakdown">
      <summary>{t("tokenUsage.breakdown")}</summary>
      <dl>
        <dt>{t("tokenUsage.input")}</dt><dd>{input == null ? t("tokenUsage.notReportedValue") : format(input)}</dd>
        <dt>{t("tokenUsage.output")}</dt><dd>{output == null ? t("tokenUsage.notReportedValue") : format(output)}</dd>
        <dt>{t("tokenUsage.estimated")}</dt><dd>{execution.estimatedTokens == null ? t("tokenUsage.notReportedValue") : format(estimated)}</dd>
      </dl>
    </details>}
  </div>
}
