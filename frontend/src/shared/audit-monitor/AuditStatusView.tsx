import { useEffect, useId, useState } from "react"
import { useTranslation } from "react-i18next"
import { Link } from "react-router-dom"
import { ArrowRightIcon, Badge, Card, CheckIcon, ChevronDownIcon, CrossIcon, FolderIcon, GridIcon, ShieldIcon, Spinner } from "../ui-kit/index.ts"
import { formatDateTime } from "../i18n/format.ts"
import { AgentTokenUsage } from "../agent-monitor/AgentTokenUsage.tsx"
import type projects from "../i18n/locales/en/projects.json"
import {
  auditProgress,
  agentTree,
  pipelineLabelKey,
  pipelineProgress,
  progressText,
  stateLabelKey,
  stateTone,
  type AuditAgentNode,
  type AuditPipelineRun,
  type AuditProgress,
  type AuditRunState,
  type AuditStatusModel,
} from "./auditStatus.ts"
import "./AuditStatusView.css"

/** Decorative: the badge beside it already carries the state as text. */
function RunStateIcon({ state }: { state: AuditRunState }) {
  if (state === "completed") {
    return <CheckIcon size={14} />
  }
  if (state === "failed") {
    return <CrossIcon size={14} />
  }
  if (state === "running") {
    return <Spinner size={12} />
  }
  return <span className={`audit-run-dot audit-run-dot-${state}`} />
}

function ProgressLabel({ progress }: { progress: AuditProgress }) {
  const { t } = useTranslation("projects")
  return <span className="label audit-progress">{progressText(t, progress)}</span>
}

function PhaseBadge({ phase }: { phase: string }) {
  const { t } = useTranslation("projects")
  const [highlighted, setHighlighted] = useState(true)
  useEffect(() => {
    const timer = setTimeout(() => setHighlighted(false), 240)
    return () => clearTimeout(timer)
  }, [])
  return <span className="audit-agent-phase" data-highlighted={highlighted}>
    <Badge tone="neutral" highlighted={highlighted}>
      {t(`auditStatus.phases.${phase}` as `auditStatus.phases.${keyof typeof projects.auditStatus.phases}`,
        { defaultValue: phase.replaceAll("_", " ") })}
    </Badge>
  </span>
}

function AgentRow({ node, primary = false }: { node: AuditAgentNode, primary?: boolean }) {
  const { agent, children } = node
  const { t } = useTranslation("projects")
  const childrenId = useId()
  const [expanded, setExpanded] = useState(true)
  const expandable = primary || children.length > 0
  const Header = expandable ? "button" : "div"

  return (
    <li className={`audit-agent${primary ? " audit-agent-root" : ""}`} data-state={agent.state}>
      <Header className={`audit-agent-head${expandable ? " audit-agent-toggle" : ""}`}
        type={expandable ? "button" : undefined}
        aria-label={expandable ? t("auditStatus.agents.title", { agentType: agent.agentType, id: agent.id }) : undefined}
        aria-expanded={expandable ? expanded : undefined} aria-controls={expandable ? childrenId : undefined}
        onClick={expandable ? () => setExpanded((value) => !value) : undefined}>
        <span className={`audit-agent-icon audit-agent-icon-${agent.state}`} aria-hidden="true">
          <RunStateIcon state={agent.state} />
        </span>
        <span className="mono audit-agent-type">
          {t("auditStatus.agents.title", { agentType: agent.agentType, id: agent.id })}
        </span>
        {expandable && <span>
          <span className="audit-pipeline-chevron" data-expanded={expanded} aria-hidden="true"><ChevronDownIcon size={12} /></span>
        </span>}
        <Badge tone={stateTone(agent.state)}>{t(stateLabelKey(agent.state))}</Badge>
        {agent.state === "running" && agent.phase && <PhaseBadge key={`${agent.id}:${agent.phase}`} phase={agent.phase} />}
      </Header>
      <div className="audit-agent-meta">
        {agent.startedAt && <span className="label">{t("auditStatus.agents.startedAt", { date: formatDateTime(agent.startedAt) })}</span>}
        {agent.finishedAt && <span className="label">{t("auditStatus.agents.finishedAt", { date: formatDateTime(agent.finishedAt) })}</span>}
      </div>
      <AgentTokenUsage execution={agent} />
      {agent.error && <p role="alert" className="audit-agent-error">{agent.error}</p>}
      {expandable && <ul id={childrenId} className="audit-agent-list audit-agent-children" hidden={!expanded}>
        {children.map((child) => <AgentRow key={child.agent.agentType} node={child} />)}
      </ul>}
    </li>
  )
}

function PipelineRow({ pipeline }: { pipeline: AuditPipelineRun }) {
  const { t } = useTranslation("projects")
  const agentsId = useId()
  // Pipelines start open: the agent runs are the point of the view. Folding is
  // for scanning an audit with many attributes, not a summary-first default.
  const [expanded, setExpanded] = useState(true)
  const labelKey = pipelineLabelKey(pipeline.id)
  const name = labelKey === null ? pipeline.id : t(labelKey)
  const progress = pipelineProgress(pipeline)
  const tree = agentTree(pipeline.agents)
  const rootType = pipeline.id === "maintainability" ? "maintainability_manager"
    : ["security", "functional_adequacy"].includes(pipeline.id) ? pipeline.id : null

  // A real root already names and controls this group. Keep generic category
  // headers for empty groups or historical rows without an identified root.
  if (tree.length > 0 && tree.every((node) => node.agent.agentType === rootType)) {
    return <ul className="audit-agent-list audit-root-list" data-state={pipeline.state}>
      {tree.map((node) => <AgentRow key={node.agent.agentType} node={node} primary />)}
    </ul>
  }

  return (
    <section className="audit-pipeline" data-state={pipeline.state}>
      {/* An explicit name: the flex row has no whitespace between its parts, so
          the name derived from the contents would read "SecurityRunning…". */}
      <button
        type="button"
        className="audit-pipeline-head"
        aria-expanded={expanded}
        aria-controls={agentsId}
        aria-label={t("auditStatus.pipelines.toggleLabel", {
          pipeline: name,
          state: t(stateLabelKey(pipeline.state)),
          progress: progressText(t, progress),
        })}
        onClick={() => setExpanded((current) => !current)}
      >
        <span className="audit-pipeline-line">
          <span className="audit-pipeline-icon" aria-hidden="true">
            {pipeline.id === "security" ? <ShieldIcon /> : <GridIcon />}
          </span>
          <span className="audit-pipeline-name">{name}</span>
          <span className="audit-pipeline-chevron" data-expanded={expanded} aria-hidden="true">
            <ChevronDownIcon size={12} />
          </span>
        </span>
        <span className="audit-pipeline-line">
          <Badge tone={stateTone(pipeline.state)}>{t(stateLabelKey(pipeline.state))}</Badge>
          <ProgressLabel progress={progress} />
        </span>
      </button>
      <div
        id={agentsId}
        className="audit-pipeline-detail"
        data-expanded={expanded}
        aria-hidden={!expanded}
        inert={!expanded}
      >
        <div className="audit-pipeline-detail-inner">
          {pipeline.agents.length === 0 ? (
            <p className="label">{t("auditStatus.agents.empty")}</p>
          ) : (
            <ul className="audit-agent-list">
              {tree.map((node) => (
                <AgentRow key={node.agent.agentType} node={node} />
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  )
}

/** Read-only view of one audit: its state, the pipelines it covers and the
 *  agents that ran inside each one. Purely presentational — it fetches
 *  nothing, so any caller can drive it with live or fixture data.
 *  `bare` drops the card surface and `summary` drops the header, so a caller
 *  that renders its own summary shows the identity once instead of twice. */
export function AuditStatusView({ audit, bare = false, summary = true }: {
  audit: AuditStatusModel
  bare?: boolean
  summary?: boolean
}) {
  const { t } = useTranslation("projects")
  const hasRevision = audit.branch !== null || audit.commitHash !== null
  const repository = audit.project ? `${audit.project.repositoryOwner}/${audit.project.repositoryName}` : null

  const content = (
    <div className="audit-status" data-state={audit.state} role="group" aria-label={t("auditStatus.regionLabel")}>
      {summary && <>
        <div className="audit-status-head">
          <span className="mono audit-status-id">{t("auditStatus.title", { id: audit.id })}</span>
          <Badge tone={stateTone(audit.state)}>{t(stateLabelKey(audit.state))}</Badge>
          <ProgressLabel progress={auditProgress(audit)} />
        </div>
        <div className="audit-status-meta">
          {audit.project && <Link className="audit-status-project" to={`/projects/${audit.project.id}/audits`}
            aria-label={t("auditStatus.openProject", { repository })}>
            <FolderIcon size={13} />
            <span className="mono">{repository}</span>
            <ArrowRightIcon size={12} />
          </Link>}
          {hasRevision ? (
            <span className="mono audit-status-revision">
              {t("auditStatus.revision", { branch: audit.branch ?? "—", hash: audit.commitHash?.slice(0, 7) ?? "—" })}
            </span>
          ) : (
            <span className="label">{t("auditStatus.revisionUnknown")}</span>
          )}
          <span className="label">{t("auditStatus.createdAt", { date: formatDateTime(audit.createdAt) })}</span>
          {audit.finishedAt && <span className="label">{t("auditStatus.finishedAt", { date: formatDateTime(audit.finishedAt) })}</span>}
          {audit.reportAvailable && <Badge tone="neutral">{t("auditStatus.reportAvailable")}</Badge>}
        </div>
      </>}
      {audit.error && <p role="alert" className="audit-status-error">{audit.error}</p>}
      {audit.pipelines.length === 0 ? (
        <p className="label">{t("auditStatus.pipelines.empty")}</p>
      ) : (
        <div className="audit-pipeline-list">
          {audit.pipelines.map((pipeline) => (
            <PipelineRow key={pipeline.id} pipeline={pipeline} />
          ))}
        </div>
      )}
    </div>
  )

  return bare ? content : <Card>{content}</Card>
}
