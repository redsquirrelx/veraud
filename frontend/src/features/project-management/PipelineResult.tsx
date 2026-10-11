import { Badge, ItemList } from "../../shared/ui-kit/index.ts"
import type { AgentExecution } from "../../infrastructure/http-client/httpClient.ts"
import {
  auditTone,
  confidenceTone,
  kindTone,
  type AnalyzerSummary,
  type ArchitectureSummary,
} from "./pipelineResult.ts"

function Evidence({ paths }: { paths: string[] }) {
  if (paths.length === 0) {
    return null
  }
  return (
    <span className="audit-evidence">
      evidence: {paths.map((path, index) => (
        <span key={`${path}-${index}`}>
          {index > 0 ? ", " : ""}
          <span className="mono audit-path">{path}</span>
        </span>
      ))}
    </span>
  )
}

/** One pipeline row: analyzer or architect, with its error when it failed. */
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

export function AnalyzerResultView({ summary, execution }: { summary: AnalyzerSummary; execution?: AgentExecution }) {
  return (
    <div className="audit-block">
      <div className="audit-head">
        <h4 className="audit-title">Analysis</h4>
        <div className="audit-head-right">
          {execution !== undefined && <PipelineRunStatus execution={execution} />}
          <div className="audit-status-row">
            <span className="label">Type</span>
            <Badge tone={kindTone(summary.kind)}>{summary.kind}</Badge>
            {summary.primaryLanguage !== "" && (
              <>
                <span className="label">Language</span>
                <Badge tone="neutral">{summary.primaryLanguage}</Badge>
              </>
            )}
            <span className="label">Confidence</span>
            <Badge tone={confidenceTone(summary.confidence)}>{summary.confidence}</Badge>
          </div>
        </div>
      </div>
      {summary.summary !== "" && (
        <p className="audit-text">{summary.summary}</p>
      )}
      {summary.filesRead !== null && (
        <span className="label">
          {summary.filesRead} file(s) read{summary.hypothesisConfirmed === true ? ", hypothesis confirmed" : ""}
        </span>
      )}
      {summary.entrypoints.length > 0 && (
        <>
          <span className="label">Entrypoints ({summary.entrypoints.length})</span>
          <ul className="audit-list">
            {summary.entrypoints.map((path) => (
              <li key={path}><span className="mono audit-path">{path}</span></li>
            ))}
          </ul>
        </>
      )}
      {summary.keyComponents.length > 0 && (
        <>
          <span className="label">Key components ({summary.keyComponents.length})</span>
          <ul className="audit-list">
            {summary.keyComponents.map((path) => (
              <li key={path}><span className="mono audit-path">{path}</span></li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

export function ArchitectureResultView({ description, execution }: { description: ArchitectureSummary; execution?: AgentExecution }) {
  return (
    <div className="audit-block">
      <div className="audit-head">
        <h4 className="audit-title">Architecture</h4>
        <div className="audit-head-right">
          {execution !== undefined && <PipelineRunStatus execution={execution} />}
          <div className="audit-status-row">
            <span className="label">Style</span>
            <Badge tone={kindTone(description.style)}>{description.style}</Badge>
            <span className="label">Intended</span>
            <Badge tone={kindTone(description.intendedStyle)}>{description.intendedStyle}</Badge>
            <span className="label">Confidence</span>
            <Badge tone={confidenceTone(description.confidence)}>{description.confidence}</Badge>
          </div>
        </div>
      </div>
      {description.deviations.length > 0 && (
        <>
          <span className="label">Deviations ({description.deviations.length})</span>
          <ul className="audit-list">
            {description.deviations.map((deviation, index) => (
              <li key={`${deviation.observation}-${index}`}>
                {deviation.observation} <Evidence paths={deviation.evidence} />
              </li>
            ))}
          </ul>
        </>
      )}
      {description.components.length > 0 && (
        <>
          <span className="label">Components ({description.components.length})</span>
          <ul className="audit-list">
            {description.components.map((component) => (
              <li key={component.path}>
                <span className="mono audit-path">{component.path}</span>
                {component.responsibility !== "" ? `: ${component.responsibility}` : ": (not described)"}
              </li>
            ))}
          </ul>
        </>
      )}
      {description.dataFlow !== "" && (
        <>
          <span className="label">Data flow</span>
          <p className="audit-text">{description.dataFlow}</p>
        </>
      )}
      {description.thirdParty.length > 0 && (
        <>
          <span className="label">Third-party ({description.thirdParty.length})</span>
          <ItemList
            items={description.thirdParty.map((name) => ({ id: name, name }))}
            selectedIds={[]}
            onSelectionChange={() => {}}
          />
        </>
      )}
      {description.cycles.length > 0 && (
        <>
          <span className="label">Cycles ({description.cycles.length})</span>
          <ul className="audit-list">
            {description.cycles.map((group, index) => (
              <li key={index}><span className="mono audit-path">{group.join(" ↔ ")}</span></li>
            ))}
          </ul>
        </>
      )}
      {description.qualityNotes.length > 0 && (
        <>
          <span className="label">Quality notes ({description.qualityNotes.length})</span>
          <ul className="audit-list">
            {description.qualityNotes.map((note, index) => (
              <li key={`${note.characteristic}-${index}`}>
                [{note.characteristic}] {note.observation} <Evidence paths={note.evidence} />
              </li>
            ))}
          </ul>
        </>
      )}
      {description.risks.length > 0 && (
        <>
          <span className="label">Risks ({description.risks.length})</span>
          <ul className="audit-list">
            {description.risks.map((risk, index) => (
              <li key={index}>{risk}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
