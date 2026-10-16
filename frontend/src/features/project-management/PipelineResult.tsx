import { useTranslation } from "react-i18next"
import type { ParseKeys, TFunction } from "i18next"
import { Badge, MermaidDiagram } from "../../shared/ui-kit/index.ts"
import type { AgentExecution } from "../../infrastructure/http-client/httpClient.ts"
import { AgentTokenUsage } from "../../shared/agent-monitor/AgentTokenUsage.tsx"
import { formatNumber } from "../../shared/i18n/format.ts"
import "./PipelineStage.css"
import {
  auditTone,
  parseStageStatus,
  verdictTone,
  type OrientationSummary,
  type ProjectArchitectureSummary,
  type SemanticValidationSummary,
} from "./pipelineResult.ts"
import {
  claimStatusLabelKeys,
  completionStatusLabelKeys,
  executionStatusLabelKeys,
  findingVerdictLabelKeys,
  reviewVerdictLabelKeys,
  statusLabelKey,
} from "./projectStatus.ts"

/** Known status label, translated at render; unknown values stay verbatim. */
function statusText(t: TFunction<"projects", undefined>, keys: Record<string, ParseKeys<"projects">>, value: string): string {
  const key = statusLabelKey(keys, value)
  return key === null ? value : t(key)
}

/** One pipeline row, with its error when it failed. */
export function PipelineRunStatus({ execution }: { execution: AgentExecution }) {
  const { t } = useTranslation("projects")
  return (
    <div className="audit-run-status">
      <div className="audit-status-row">
        <Badge tone={auditTone(execution.status)}>{statusText(t, executionStatusLabelKeys, execution.status)}</Badge>
        <span className="label">
          {t("pipeline.runLabel", { agentType: execution.agentType, id: execution.id })}
        </span>
        {execution.status === "Failed" && execution.error !== null && execution.error !== "" && (
          <span className="audit-error">{execution.error}</span>
        )}
        {execution.status === "Failed" && execution.interruptionReason === "token_budget_exhausted" && <span className="audit-error">{t("pipeline.tokenBudgetExhausted")}</span>}
        {execution.status === "Failed" && execution.result && <Badge tone="info">{t("pipeline.partialResults")}</Badge>}
      </div>
      <AgentTokenUsage execution={execution} />
    </div>
  )
}

export function OrientationResultView({ summary, execution }: { summary: OrientationSummary; execution?: AgentExecution }) {
  const { t } = useTranslation("projects")
  return (
    <div className="stage-view">
      <div className="stage-head">
        <h4 className="stage-title">{t("pipeline.orientationTitle")}</h4>
        <div className="stage-head-right">
          {execution !== undefined && <PipelineRunStatus execution={execution} />}
          <Badge tone={summary.completionStatus === "complete" ? "success" : "info"}>{statusText(t, completionStatusLabelKeys, summary.completionStatus)}</Badge>
        </div>
      </div>
      {summary.projectType !== "" && (
        <p className="stage-lede">
          {summary.projectType} <Badge tone={verdictTone(summary.projectTypeStatus)}>{statusText(t, claimStatusLabelKeys, summary.projectTypeStatus)}</Badge>
        </p>
      )}
      {summary.purpose !== "" && (
        <p className="stage-lede">
          {summary.purpose} <Badge tone={verdictTone(summary.purposeStatus)}>{statusText(t, claimStatusLabelKeys, summary.purposeStatus)}</Badge>
        </p>
      )}
      {summary.components.length > 0 && (
        <>
          <span className="stage-section-label">{t("pipeline.components", { count: (summary.components.length) })}</span>
          <div className="stage-rows">
            {summary.components.map((component) => (
              <div className="stage-row" key={component.name}>
                <div className="stage-row-main">
                  <span className="mono stage-path">{component.name}</span>
                  {component.responsibility !== "" && <> — {component.responsibility}</>}
                </div>
                <span className="stage-row-side"><Badge tone={verdictTone(component.status)}>{statusText(t, claimStatusLabelKeys, component.status)}</Badge></span>
              </div>
            ))}
          </div>
        </>
      )}
      {summary.startingPoints.length > 0 && (
        <>
          <span className="stage-section-label">{t("pipeline.startingPoints", { count: (summary.startingPoints.length) })}</span>
          <div className="stage-rows">
            {summary.startingPoints.map((point, index) => (
              <div className="stage-row" key={`${point.fileId}-${index}`}>
                <div className="stage-row-main">
                  <span className="mono stage-path">{point.fileId}</span>
                  <div className="stage-row-sub">{point.reason}</div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
      {summary.uncertainties.length > 0 && (
        <>
          <span className="stage-section-label">{t("pipeline.uncertainties", { count: (summary.uncertainties.length) })}</span>
          <div className="stage-rows">
            {summary.uncertainties.map((item, index) => (
              <div className="stage-row" key={index}>
                <div className="stage-row-main">{item}</div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function DiagramColorLegend() {
  const { t } = useTranslation("projects")
  const architect: Array<[string, string]> = [
    ["#dbeafe", t("status.legendArchitect.supported")],
    ["#fef3c7", t("status.legendArchitect.hypothesis")],
    ["#e5e7eb", t("status.legendArchitect.unresolved")],
  ]
  const semantic: Array<[string, string]> = [
    ["#15803d", t("status.legendSemantic.supported")],
    ["#c2410c", t("status.legendSemantic.overstated")],
    ["#b91c1c", t("status.legendSemantic.contradicted")],
    ["#64748b", t("status.legendSemantic.insufficientEvidence")],
    ["#94a3b8", t("status.legendSemantic.notReviewed")],
  ]
  return <div className="architecture-diagram-legend">
    <span className="stage-section-label">{t("pipeline.colorLegend")}</span>
    <p className="stage-row-sub">{t("pipeline.legendHint")}</p>
    <div className="architecture-diagram-key"><strong>{t("pipeline.architectFill")}</strong>{architect.map(([color, label]) => <span key={label}><i style={{ backgroundColor: color }} />{label}</span>)}</div>
    <div className="architecture-diagram-key"><strong>{t("pipeline.semanticBorder")}</strong>{semantic.map(([color, label]) => <span key={label}><i style={{ border: `3px ${label === t("status.legendSemantic.insufficientEvidence") ? "dashed" : "solid"} ${color}` }} />{label}</span>)}</div>
    <p className="stage-row-sub">{t("pipeline.legendArrows")}</p>
  </div>
}

export function ProjectArchitectureResultView({ summary, execution }: { summary: ProjectArchitectureSummary; execution?: AgentExecution }) {
  const { t } = useTranslation("projects")
  return (
    <div className="stage-view">
      <div className="stage-head">
        <h4 className="stage-title">{t("pipeline.architectureTitle")}</h4>
        <div className="stage-head-right">
          {execution !== undefined && <PipelineRunStatus execution={execution} />}
          <Badge tone={summary.completionStatus === "complete" ? "success" : "info"}>{statusText(t, completionStatusLabelKeys, summary.completionStatus)}</Badge>
          {summary.pattern !== "" && <Badge tone="info">{summary.pattern}</Badge>}
        </div>
      </div>
      {summary.patternAssessment !== "" && (
        <p className="stage-lede">{summary.patternAssessment}</p>
      )}
      {summary.explanation !== "" && <>
        <span className="stage-section-label">{t("pipeline.architecturalExplanation")}</span>
        <p className="stage-lede">{summary.explanation}</p>
      </>}
      {summary.supportingFindings.length > 0 && <>
        <span className="stage-section-label">{t("pipeline.supportingFindings", { count: (summary.supportingFindings.length) })}</span>
        <div className="stage-rows">
          {summary.supportingFindings.map((finding, index) => <div className="stage-row" key={index}>
            <div className="stage-row-main">
              {finding.statement}
              {finding.scope !== "" && <div className="stage-row-sub">{t("pipeline.scopeLabel", { scope: finding.scope })}</div>}
              {finding.limitations.map((limitation, item) => <div className="stage-row-sub" key={item}>{limitation}</div>)}
            </div>
            <span className="stage-row-side"><Badge tone={verdictTone(finding.status)}>{statusText(t, claimStatusLabelKeys, finding.status)}</Badge></span>
          </div>)}
        </div>
      </>}
      {summary.contrastQuestion !== "" && <>
        <span className="stage-section-label">{t("pipeline.patternContrast")}</span>
        <p className="stage-lede">{summary.contrastQuestion}</p>
        {summary.contrastResult !== "" && <p className="stage-lede">{summary.contrastResult}</p>}
      </>}
      {summary.units.length > 0 && (
        <>
          <span className="stage-section-label">{t("pipeline.organization", { count: (summary.units.length) })}</span>
          <div className="stage-rows">
            {summary.units.map((unit) => (
              <div className="stage-row" key={unit.name}>
                <div className="stage-row-main">
                  <span className="mono stage-path">{unit.name}</span>
                  {unit.responsibility !== "" && <> — {unit.responsibility}</>}
                </div>
                <span className="stage-row-side"><Badge tone={verdictTone(unit.status)}>{statusText(t, claimStatusLabelKeys, unit.status)}</Badge></span>
              </div>
            ))}
          </div>
        </>
      )}
      {summary.connections.length > 0 && (
        <>
          <span className="stage-section-label">{t("pipeline.connections", { count: (summary.connections.length) })}</span>
          <div className="stage-rows">
            {summary.connections.map((connection, index) => (
              <div className="stage-row" key={index}>
                <div className="stage-row-main">
                  <span className="mono stage-path">{connection.from} → {connection.to}</span>
                  <div className="stage-row-sub">{connection.description}</div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
      {summary.relationshipCoverage.length > 0 && <>
        <span className="stage-section-label">{t("pipeline.relationshipCoverage", { count: (summary.relationshipCoverage.length) })}</span>
        <div className="stage-rows">{summary.relationshipCoverage.map((item) => <div className="stage-row" key={item.unit}>
          <div className="stage-row-main"><span className="mono stage-path">{item.unit}</span>
            <div className="stage-row-sub">{item.reason}</div>
            {item.blockerReason !== "" && <div className="stage-row-sub">{t("pipeline.resolutionBlocker", { blocker: item.blocker, blockerReason: item.blockerReason })}</div>}
            {item.pendingPaths.length > 0 && <div className="stage-row-sub">{t("pipeline.pendingEndpoints", { count: (item.pendingPaths.length), paths: item.pendingPaths.slice(0, 8).join(", ") })}{item.pendingPaths.length > 8 ? "…" : ""}</div>}
          </div>
          <span className="stage-row-side"><Badge tone={item.status === "connected" || item.status === "isolated" ? "success" : "info"}>{item.status}</Badge></span>
        </div>)}</div>
      </>}
      {summary.deviations.length > 0 && (
        <>
          <span className="stage-section-label">{t("pipeline.deviations", { count: (summary.deviations.length) })}</span>
          <div className="stage-rows">
            {summary.deviations.map((deviation, index) => (
              <div className="stage-row" key={index}>
                <div className="stage-row-main">
                  {deviation.decision}
                  <div className="stage-row-sub">{t("pipeline.deviationDetail", { expectation: deviation.expectation, explanation: deviation.explanation })}</div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
      {summary.infrastructure.length > 0 && (
        <>
          <span className="stage-section-label">{t("pipeline.infrastructure", { count: (summary.infrastructure.length) })}</span>
          <div className="stage-rows">
            {summary.infrastructure.map((item) => (
              <div className="stage-row" key={`${item.kind}-${item.name}`}>
                <div className="stage-row-main"><span className="mono stage-path">{item.name}</span></div>
                <span className="stage-row-side"><Badge tone="neutral">{item.kind}</Badge></span>
              </div>
            ))}
          </div>
        </>
      )}
      {summary.diagramViews.length > 0 ? (
        <>
          <span className="stage-section-label">
            {summary.diagramOrigin !== "" ? t("pipeline.diagramWithOrigin", { origin: summary.diagramOrigin }) : t("pipeline.diagram")}
          </span>
          {summary.diagramViews.map((view, index) => <section className="architecture-diagram-view" key={index} aria-label={view.title}>
            <h5>{view.title}</h5>
            {view.scope !== "" && <p className="stage-row-sub">{t("pipeline.scopeLabel", { scope: view.scope })}</p>}
            <MermaidDiagram chart={view.mermaid} label={view.title} />
            {view.colorLegend && <DiagramColorLegend />}
            {view.deviations.length > 0 && <div className="stage-rows">
              {view.deviations.map((note) => <div className="stage-row" key={note.id}>
                <div className="stage-row-main"><strong>{note.id}: </strong>{note.observation}
                  <div className="stage-row-sub">{t("pipeline.expectedLabel", { expectation: note.expectation })}</div>
                  <div className="stage-row-sub">{note.explanation}</div>
                </div>
              </div>)}
            </div>}
            {view.limitations.map((item, limitation) => <p className="stage-footnote" key={limitation}>{item}</p>)}
          </section>)}
        </>
      ) : (
        summary.diagramTitle !== "" && (
          <span className="stage-footnote">
            {t("pipeline.diagramFallback", { title: summary.diagramTitle, nodes: formatNumber(summary.diagramNodes), edges: formatNumber(summary.diagramEdges) })}
          </span>
        )
      )}
      {summary.uncertainties.length > 0 && (
        <>
          <span className="stage-section-label">{t("pipeline.uncertainties", { count: (summary.uncertainties.length) })}</span>
          <div className="stage-rows">
            {summary.uncertainties.map((item, index) => (
              <div className="stage-row" key={index}>
                <div className="stage-row-main">{item}</div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

export function SemanticValidationResultView({ summary, execution }: { summary: SemanticValidationSummary; execution?: AgentExecution }) {  const { t } = useTranslation("projects")
  return (
    <div className="stage-view">
      <div className="stage-head">
        <h4 className="stage-title">{t("pipeline.semanticTitle")}</h4>
        <div className="stage-head-right">
          {execution !== undefined && <PipelineRunStatus execution={execution} />}
          <Badge tone={verdictTone(summary.verdict)}>{statusText(t, reviewVerdictLabelKeys, summary.verdict)}</Badge>
          <Badge tone={summary.completionStatus === "complete" ? "success" : "info"}>{statusText(t, completionStatusLabelKeys, summary.completionStatus)}</Badge>
        </div>
      </div>
      {summary.findings.length > 0 && (
        <>
          <span className="stage-section-label">{t("pipeline.findings", { count: (summary.findings.length) })}</span>
          <div className="stage-rows">
            {summary.findings.map((finding) => (
              <div className="stage-row" key={finding.targetId}>
                <div className="stage-row-main">
                  <span className="mono stage-path">{finding.targetId}</span>: {finding.statement}{" "}
                  <Badge tone={verdictTone(finding.verdict)}>{statusText(t, findingVerdictLabelKeys, finding.verdict)}</Badge>
                  {finding.reason !== "" && <div className="stage-row-sub">{finding.reason}</div>}
                  {finding.correction !== "" && (
                    <div className="stage-correction">{t("pipeline.proposedCorrection", { correction: finding.correction })}</div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
      {summary.pending.length > 0 && (
        <>
          <span className="stage-section-label">{t("pipeline.pending", { count: (summary.pending.length) })}</span>
          <div className="stage-rows">
            {summary.pending.map((target) => (
              <div className="stage-row" key={target}>
                <div className="stage-row-main"><span className="mono stage-path">{target}</span></div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

/** Middle fallback between a rich stage view and a bare run status: shows
 *  the completion status plus the run's own issues and limitations, so failed
 *  runs without a report still explain themselves. */
export function StageStatusView({ title, result, execution }: { title: string; result: string | null; execution?: AgentExecution }) {
  const { t } = useTranslation("projects")
  const summary = parseStageStatus(result)
  if (summary === null) {
    return execution === undefined ? null : <PipelineRunStatus execution={execution} />
  }
  return (
    <div className="stage-view">
      <div className="stage-head">
        <h4 className="stage-title">{title}</h4>
        <div className="stage-head-right">
          {execution !== undefined && <PipelineRunStatus execution={execution} />}
          <Badge tone={summary.completionStatus === "complete" ? "success" : summary.completionStatus === "failed" ? "warning" : "info"}>
            {statusText(t, completionStatusLabelKeys, summary.completionStatus)}
          </Badge>
        </div>
      </div>
      {summary.issues.length > 0 && (
        <>
          <span className="stage-section-label">{t("pipeline.issues", { count: (summary.issues.length) })}</span>
          <div className="stage-rows">
            {summary.issues.map((issue, index) => (
              <div className="stage-row" key={index}>
                <div className="stage-row-main">
                  <span className="mono stage-path">{issue.category}</span>
                  <div className="stage-row-sub">{issue.message}</div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
      {summary.limitations.length > 0 && (
        <>
          <span className="stage-section-label">{t("pipeline.limitations", { count: (summary.limitations.length) })}</span>
          <div className="stage-rows">
            {summary.limitations.map((item, index) => (
              <div className="stage-row" key={index}>
                <div className="stage-row-main">{item}</div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
