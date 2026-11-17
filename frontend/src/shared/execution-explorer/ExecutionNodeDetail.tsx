import { useTranslation } from "react-i18next"
import { Badge } from "../ui-kit/index.ts"
import { formatDateTime } from "../i18n/format.ts"
import { useAuditStateLabel } from "../audit-monitor/monitorLabels.ts"
import { AgentTokenUsage, hasReportedTokens } from "../agent-monitor/AgentTokenUsage.tsx"
import { stateTone, type AuditAgentRun } from "../audit-monitor/auditStatus.ts"

/** Detail sections for the agent picked in the tree. */
export function ExecutionNodeDetail({ agent }: { agent: AuditAgentRun }) {
  const { t } = useTranslation("executionExplorer")
  const stateLabel = useAuditStateLabel()
  const phase = agent.state === "running" && agent.phase ? agent.phase.replaceAll("_", " ") : null

  return (
    <div className="execution-explorer-node-detail">
      <section className="execution-explorer-node-section" aria-label={t("node.execution")}>
        <h4>{t("node.execution")}</h4>
        <p className="mono execution-explorer-node-identity">{agent.agentType} · {agent.id}</p>
        <p className="execution-explorer-node-badges">
          <Badge tone={stateTone(agent.state)}>{stateLabel(agent.state)}</Badge>
          {agent.role && <Badge tone="neutral">{agent.role}</Badge>}
          {phase && <span className="execution-explorer-node-phase">{phase}</span>}
        </p>
      </section>

      <section className="execution-explorer-node-section" aria-label={t("node.dates")}>
        <h4>{t("node.dates")}</h4>
        <dl className="execution-explorer-node-dates">
          <div>
            <dt>{t("node.started")}</dt>
            <dd>{agent.startedAt ? <time dateTime={agent.startedAt}>{formatDateTime(agent.startedAt)}</time> : t("node.notRecorded")}</dd>
          </div>
          <div>
            <dt>{t("node.finished")}</dt>
            <dd>{agent.finishedAt ? <time dateTime={agent.finishedAt}>{formatDateTime(agent.finishedAt)}</time> : t("node.notRecorded")}</dd>
          </div>
        </dl>
      </section>

      <section className="execution-explorer-node-section" aria-label={t("node.tokens")}>
        <h4>{t("node.tokens")}</h4>
        {hasReportedTokens(agent) || (agent.unknownUsageAttempts ?? 0) > 0 || agent.configuration ? (
          <AgentTokenUsage execution={agent} />
        ) : (
          <p className="label">{t("node.notRecorded")}</p>
        )}
      </section>

      {agent.error?.trim() && (
        <section className="execution-explorer-node-section execution-explorer-node-error" aria-label={t("node.error")}>
          <h4>{t("node.error")}</h4>
          <p className="mono" role="alert">{agent.error}</p>
        </section>
      )}
    </div>
  )
}
