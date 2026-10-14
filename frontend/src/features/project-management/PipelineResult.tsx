import { Badge } from "../../shared/ui-kit/index.ts"
import type { AgentExecution } from "../../infrastructure/http-client/httpClient.ts"
import "./PipelineStage.css"
import {
  auditTone,
  parseStageStatus,
  verdictTone,
  type OrientationSummary,
  type ProjectArchitectureSummary,
  type SemanticValidationSummary,
} from "./pipelineResult.ts"

/** One pipeline row, with its error when it failed. */
export function PipelineRunStatus({ execution }: { execution: AgentExecution }) {
  return (
    <div className="audit-status-row">
      <Badge tone={auditTone(execution.status)}>{execution.status}</Badge>
      <span className="label">
        {execution.agentType} run #{execution.id}
      </span>
      {execution.status === "Failed" && execution.error !== null && execution.error !== "" && (
        <span className="audit-error">{execution.error}</span>
      )}
    </div>
  )
}

export function OrientationResultView({ summary, execution }: { summary: OrientationSummary; execution?: AgentExecution }) {
  return (
    <div className="stage-view">
      <div className="stage-head">
        <h4 className="stage-title">Orientation</h4>
        <div className="stage-head-right">
          {execution !== undefined && <PipelineRunStatus execution={execution} />}
          <Badge tone={summary.completionStatus === "complete" ? "success" : "info"}>{summary.completionStatus}</Badge>
        </div>
      </div>
      {summary.projectType !== "" && (
        <p className="stage-lede">
          {summary.projectType} <Badge tone={verdictTone(summary.projectTypeStatus)}>{summary.projectTypeStatus}</Badge>
        </p>
      )}
      {summary.purpose !== "" && (
        <p className="stage-lede">
          {summary.purpose} <Badge tone={verdictTone(summary.purposeStatus)}>{summary.purposeStatus}</Badge>
        </p>
      )}
      {summary.components.length > 0 && (
        <>
          <span className="stage-section-label">Components ({summary.components.length})</span>
          <div className="stage-rows">
            {summary.components.map((component) => (
              <div className="stage-row" key={component.name}>
                <div className="stage-row-main">
                  <span className="mono stage-path">{component.name}</span>
                  {component.responsibility !== "" && <> — {component.responsibility}</>}
                </div>
                <span className="stage-row-side"><Badge tone={verdictTone(component.status)}>{component.status}</Badge></span>
              </div>
            ))}
          </div>
        </>
      )}
      {summary.startingPoints.length > 0 && (
        <>
          <span className="stage-section-label">Starting points ({summary.startingPoints.length})</span>
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
          <span className="stage-section-label">Uncertainties ({summary.uncertainties.length})</span>
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

export function ProjectArchitectureResultView({ summary, execution }: { summary: ProjectArchitectureSummary; execution?: AgentExecution }) {
  return (
    <div className="stage-view">
      <div className="stage-head">
        <h4 className="stage-title">Architecture</h4>
        <div className="stage-head-right">
          {execution !== undefined && <PipelineRunStatus execution={execution} />}
          <Badge tone={summary.completionStatus === "complete" ? "success" : "info"}>{summary.completionStatus}</Badge>
          {summary.pattern !== "" && <Badge tone="info">{summary.pattern}</Badge>}
        </div>
      </div>
      {summary.patternAssessment !== "" && (
        <p className="stage-lede">{summary.patternAssessment}</p>
      )}
      {summary.units.length > 0 && (
        <>
          <span className="stage-section-label">Organization ({summary.units.length})</span>
          <div className="stage-rows">
            {summary.units.map((unit) => (
              <div className="stage-row" key={unit.name}>
                <div className="stage-row-main">
                  <span className="mono stage-path">{unit.name}</span>
                  {unit.responsibility !== "" && <> — {unit.responsibility}</>}
                </div>
                <span className="stage-row-side"><Badge tone={verdictTone(unit.status)}>{unit.status}</Badge></span>
              </div>
            ))}
          </div>
        </>
      )}
      {summary.connections.length > 0 && (
        <>
          <span className="stage-section-label">Connections ({summary.connections.length})</span>
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
      {summary.deviations.length > 0 && (
        <>
          <span className="stage-section-label">Deviations ({summary.deviations.length})</span>
          <div className="stage-rows">
            {summary.deviations.map((deviation, index) => (
              <div className="stage-row" key={index}>
                <div className="stage-row-main">
                  {deviation.decision}
                  <div className="stage-row-sub">Expected: {deviation.expectation} · {deviation.explanation}</div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
      {summary.infrastructure.length > 0 && (
        <>
          <span className="stage-section-label">Infrastructure ({summary.infrastructure.length})</span>
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
      {summary.diagramTitle !== "" && (
        <span className="stage-footnote">
          Diagram “{summary.diagramTitle}”: {summary.diagramNodes} node(s), {summary.diagramEdges} edge(s)
        </span>
      )}
      {summary.uncertainties.length > 0 && (
        <>
          <span className="stage-section-label">Uncertainties ({summary.uncertainties.length})</span>
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

export function SemanticValidationResultView({ summary, execution }: { summary: SemanticValidationSummary; execution?: AgentExecution }) {  return (
    <div className="stage-view">
      <div className="stage-head">
        <h4 className="stage-title">Semantic validation</h4>
        <div className="stage-head-right">
          {execution !== undefined && <PipelineRunStatus execution={execution} />}
          <Badge tone={verdictTone(summary.verdict)}>{summary.verdict}</Badge>
          <Badge tone={summary.completionStatus === "complete" ? "success" : "info"}>{summary.completionStatus}</Badge>
        </div>
      </div>
      {summary.findings.length > 0 && (
        <>
          <span className="stage-section-label">Findings ({summary.findings.length})</span>
          <div className="stage-rows">
            {summary.findings.map((finding) => (
              <div className="stage-row" key={finding.targetId}>
                <div className="stage-row-main">
                  <span className="mono stage-path">{finding.targetId}</span>: {finding.statement}{" "}
                  <Badge tone={verdictTone(finding.verdict)}>{finding.verdict}</Badge>
                  {finding.reason !== "" && <div className="stage-row-sub">{finding.reason}</div>}
                  {finding.correction !== "" && (
                    <div className="stage-correction">Proposed correction: {finding.correction}</div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
      {summary.pending.length > 0 && (
        <>
          <span className="stage-section-label">Pending ({summary.pending.length})</span>
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
            {summary.completionStatus}
          </Badge>
        </div>
      </div>
      {summary.issues.length > 0 && (
        <>
          <span className="stage-section-label">Issues ({summary.issues.length})</span>
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
          <span className="stage-section-label">Limitations ({summary.limitations.length})</span>
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
