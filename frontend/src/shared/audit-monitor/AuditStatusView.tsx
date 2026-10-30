import { useEffect, useId, useState } from "react"
import { useTranslation } from "react-i18next"
import { Link } from "react-router-dom"
import { ArrowRightIcon, Badge, Card, ChevronDownIcon, DotsIcon, FolderIcon, GridIcon, ShieldIcon } from "../ui-kit/index.ts"
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
  type AuditStatusModel,
} from "./auditStatus.ts"
import "./AuditStatusView.css"
import { useExpansion } from "./useExpansion.ts"
import { useMonitorLabels } from "./monitorLabels.ts"
import { AuditActions } from "./AuditActions.tsx"

function ProgressLabel({ progress }: { progress: AuditProgress }) {
  const { t } = useTranslation("projects")
  return <span className="label audit-progress">{progressText(t, progress)}</span>
}

function PhaseDot({ phase }: { phase: string }) {
  const { t } = useTranslation("projects")
  const [highlighted, setHighlighted] = useState(true)
  useEffect(() => {
    const timer = setTimeout(() => setHighlighted(false), 240)
    return () => clearTimeout(timer)
  }, [])
  const label = t(`auditStatus.phases.${phase}` as `auditStatus.phases.${keyof typeof projects.auditStatus.phases}`,
    { defaultValue: phase.replaceAll("_", " ") })
  return <span className="audit-agent-phase" data-phase={phase} data-highlighted={highlighted}
    role="img" aria-label={label} title={label} />
}

function AgentRow({ node, path, primary = false, evidenceAudit }: { node: AuditAgentNode, path: readonly (string | number)[], primary?: boolean, evidenceAudit?: AuditStatusModel }) {
  const { agent, children } = node
  const { t } = useTranslation("projects")
  const { t: tEvidence } = useTranslation("auditEvidence")
  const labels = useMonitorLabels()
  const childrenId = useId()
  const detailsId = useId()
  const stateId = useId()
  const [expanded, toggleExpanded] = useExpansion(path)
  const [detailsExpanded, toggleDetails] = useExpansion([...path, "$details"], false)
  const identity = t("auditStatus.agents.title", { agentType: agent.agentType, id: agent.id })
  const leaf = !primary && children.length === 0
  const contentExpanded = expanded && (!leaf || detailsExpanded)

  function toggleOwnDetails() {
    if (!expanded) toggleExpanded()
    if (expanded || !detailsExpanded) toggleDetails()
  }

  return (
    <li className={`audit-agent${primary ? " audit-agent-root" : ""}`} data-state={agent.state}>
      <div className="audit-agent-head">
        <button className="audit-agent-toggle" type="button" aria-label={identity} aria-describedby={stateId}
          title={leaf ? labels.details : labels.branch}
          aria-expanded={contentExpanded} aria-controls={childrenId} onClick={leaf ? toggleOwnDetails : toggleExpanded}>
          {agent.state === "running" && agent.phase
            ? <PhaseDot key={`${agent.id}:${agent.phase}`} phase={agent.phase} />
            : <span className="audit-agent-phase" role="img" aria-label={labels.noPhase} title={labels.noPhase} />}
          <span className="mono audit-agent-type" title={agent.name ?? agent.agentType}>{agent.name ?? agent.agentType}</span>
          <span id={stateId} className="audit-agent-state">{t(stateLabelKey(agent.state))}</span>
          <span className="audit-pipeline-chevron" data-expanded={contentExpanded} aria-hidden="true"><ChevronDownIcon size={12} /></span>
        </button>
        <button className="audit-agent-details-toggle" type="button" aria-label={`${labels.details} · ${identity}`}
          title={labels.details} aria-expanded={expanded && detailsExpanded} aria-controls={detailsId}
          onClick={toggleOwnDetails}><DotsIcon size={14} /></button>
      </div>
      <div id={childrenId} className="audit-agent-content" hidden={!contentExpanded}>
        <div id={detailsId} className="audit-agent-details" hidden={!detailsExpanded}>
          <section className="audit-agent-detail-section audit-agent-meta" aria-label={labels.execution}>
            <h4>{labels.execution}</h4>
            <p className="mono audit-agent-identity">{identity}</p>
          </section>
          <section className="audit-agent-detail-section" aria-label={labels.dates}>
            <h4>{labels.dates}</h4>
            <dl className="audit-agent-dates">
              <div><dt>{labels.started}</dt><dd>{agent.startedAt
                ? <time dateTime={agent.startedAt}>{formatDateTime(agent.startedAt)}</time> : labels.notRecorded}</dd></div>
              <div><dt>{labels.finished}</dt><dd>{agent.finishedAt
                ? <time dateTime={agent.finishedAt}>{formatDateTime(agent.finishedAt)}</time> : labels.notRecorded}</dd></div>
            </dl>
          </section>
          <section className="audit-agent-detail-section" aria-label={labels.tokens}>
            <h4>{labels.tokens}</h4>
            <AgentTokenUsage execution={agent} />
          </section>
          {agent.error && <section className="audit-agent-detail-section" aria-label={labels.error}>
            <h4>{labels.error}</h4>
            <p role="alert" className="audit-agent-error">{agent.error}</p>
          </section>}
          {evidenceAudit?.project && agent.role === "investigator" && <div className="audit-agent-actions">
            <Link className="ui-button ui-button-secondary"
              to={`/projects/${evidenceAudit.project.id}/audits/${evidenceAudit.id}/evidence/${encodeURIComponent(agent.id)}?${new URLSearchParams({ agent: agent.agentType, name: agent.name ?? agent.agentType })}`}>
              {tEvidence("view")}
            </Link>
          </div>}
        </div>
        {children.length > 0 && <ul className="audit-agent-list audit-agent-children">
          {children.map((child) => <AgentRow key={child.agent.agentType} node={child} path={[...path, child.agent.agentType]} evidenceAudit={evidenceAudit} />)}
        </ul>}
      </div>
    </li>
  )
}

function PipelineRow({ pipeline, auditId, evidenceAudit }: { pipeline: AuditPipelineRun, auditId: number, evidenceAudit?: AuditStatusModel }) {
  const { t } = useTranslation("projects")
  const agentsId = useId()
  // Pipelines start open: the agent runs are the point of the view. Folding is
  // for scanning an audit with many attributes, not a summary-first default.
  const path = [auditId, pipeline.id]
  const [expanded, toggleExpanded] = useExpansion(path)
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
      {tree.map((node) => <AgentRow key={node.agent.agentType} node={node} path={[...path, node.agent.agentType]} primary evidenceAudit={evidenceAudit} />)}
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
        onClick={toggleExpanded}
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
                <AgentRow key={node.agent.agentType} node={node} path={[...path, node.agent.agentType]} evidenceAudit={evidenceAudit} />
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
export function AuditStatusView({ audit, bare = false, summary = true, evidenceLinks = false, actions = true }: {
  audit: AuditStatusModel
  bare?: boolean
  summary?: boolean
  evidenceLinks?: boolean
  actions?: boolean
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
          {audit.project && audit.project.id <= 0 && <span className="audit-status-project"><span className="mono">{repository}</span></span>}
          {audit.project && audit.project.id > 0 && <Link className="audit-status-project" to={`/projects/${audit.project.id}/audits`}
            aria-label={t("auditStatus.openProject", { repository })}>
            <FolderIcon size={13} />
            <span className="mono">{repository}</span>
            <ArrowRightIcon size={12} />
          </Link>}
          {actions && <AuditActions audit={audit} />}
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
      {!summary && actions && <AuditActions audit={audit} />}
      {audit.pipelines.length === 0 ? (
        <p className="label">{t("auditStatus.pipelines.empty")}</p>
      ) : (
        <div className="audit-pipeline-list">
          {audit.pipelines.map((pipeline) => (
             <PipelineRow key={pipeline.id} pipeline={pipeline} auditId={audit.id} evidenceAudit={evidenceLinks ? audit : undefined} />
          ))}
        </div>
      )}
    </div>
  )

  return bare ? content : <Card>{content}</Card>
}
