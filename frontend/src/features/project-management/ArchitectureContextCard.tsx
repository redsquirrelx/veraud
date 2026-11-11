import { useState } from "react"
import { useTranslation } from "react-i18next"
import type { ParseKeys, TFunction } from "i18next"
import { Accordion, Badge, Card, Spinner } from "../../shared/ui-kit/index.ts"
import { formatDateTime } from "../../shared/i18n/format.ts"
import { completionStatusLabelKeys, statusLabelKey } from "./projectStatus.ts"
import { ArchitectureContextCoverage } from "./ArchitectureContextCoverage.tsx"
import { ArchitectureContextKnowledgeExplorer } from "./ArchitectureContextKnowledgeExplorer.tsx"
import type { ArchitectureContextState } from "./useArchitectureContext.ts"
import {
  architectureContextCategoryLabelKeys,
  architectureContextCoverageLabelKeys,
  architectureContextIssueKindLabelKeys,
  architectureContextReasonLabelKeys,
  parseArchitectureContext,
} from "./architectureContextView.ts"
import "./PipelineStage.css"

function enumText(
  t: TFunction<"projects", undefined>,
  keys: Record<string, ParseKeys<"projects">>,
  value: string,
): string {
  const key = statusLabelKey(keys, value)
  return key === null ? value : t(key)
}

function issueKindTone(value: string): "warning" | "info" | "neutral" {
  if (value === "discrepancy") return "warning"
  if (value === "ambiguity") return "info"
  return "neutral"
}

function shortHash(hash: string): string {
  return hash.length > 12 ? `${hash.slice(0, 12)}…` : hash
}

/** Full, self-ordering architecture-context card; uses the same row/badge
 *  language as the other pipeline result views. */
export function ArchitectureContextCard({ state, versionLoading = false, versionApplying = false, repositoryName = "" }: { state: ArchitectureContextState; versionLoading?: boolean; versionApplying?: boolean; repositoryName?: string }) {
  const { t } = useTranslation("projects")
  const [documentsOpen, setDocumentsOpen] = useState(false)
  const showVersionLoading = versionLoading || versionApplying
  const summary = !showVersionLoading && state.status === "ready" && state.context !== null ? parseArchitectureContext(state.context.data) : null

  return (
    <Card className="project-body-card" layout="stack" gap="sm" align="stretch" padding="responsive">
      <div className="stage-view">
        <div className="stage-head">
          <h4 className="stage-title stage-title--lg">{t("detail.overview.architectureContext.title")}</h4>
          {!showVersionLoading && state.status === "ready" && state.context !== null && (
            <div className="stage-head-right">
              <Badge tone={state.context.executionStatus === "complete" ? "success" : "warning"}>
                {enumText(t, completionStatusLabelKeys, state.context.executionStatus)}
              </Badge>
              <Badge tone="neutral">v{state.context.schemaVersion}</Badge>
              {summary !== null && summary.coverageAssessmentStatus !== "" && summary.coverageAssessmentStatus !== "completed" && (
                <Badge tone={summary.coverageAssessmentStatus === "failed" ? "warning" : "info"}>
                  {enumText(t, architectureContextCoverageLabelKeys, summary.coverageAssessmentStatus)}
                </Badge>
              )}
              <span className="label"><time dateTime={state.context.createdAt}>{formatDateTime(state.context.createdAt)}</time></span>
            </div>
          )}
        </div>

        {showVersionLoading ? (
          <div className="files-loading" role="status" aria-label={t("detail.files.loading")}>
            <Spinner /><span className="label">{versionLoading ? t("version.loadingVersion") : t("version.applying")}</span>
          </div>
        ) : (
          <>
            {state.status === "loading" && (
              <div className="files-loading" role="status" aria-label={t("detail.files.loading")}>
                <Spinner /><span className="label">{t("detail.overview.architectureContext.loading")}</span>
              </div>
            )}
            {state.status === "error" && <p className="files-error">{t("detail.overview.architectureContext.error")}</p>}
            {state.status === "idle" && <p className="label">{t("detail.overview.architectureContext.empty")}</p>}
            {state.status === "ready" && state.context === null && <p className="label">{t("detail.overview.architectureContext.empty")}</p>}
          </>
        )}

        {summary !== null && (
          <>
            {summary.finalizationReason !== "" && (
              <p className="stage-lede">{enumText(t, architectureContextReasonLabelKeys, summary.finalizationReason)}</p>
            )}

            <ArchitectureContextCoverage summary={summary} projectId={state.status === "ready" && state.context !== null ? state.context.projectId : null} repositoryName={repositoryName} />

            {summary.consultedDocuments.length > 0 && (
              <Accordion title={t("detail.overview.architectureContext.documents")} open={documentsOpen} onOpenChange={setDocumentsOpen}>
                <div className="stage-rows">
                  {summary.consultedDocuments.map((document) => (
                    <div className="stage-row" key={document.path}>
                      <div className="stage-row-main">
                        <span className="mono stage-path">{document.path}</span>
                        {(document.lineCount !== null || document.contentHash !== "") && (
                          <div className="stage-row-sub">
                            {document.lineCount !== null && t("detail.overview.architectureContext.lines", { count: document.lineCount })}
                            {document.lineCount !== null && document.contentHash !== "" && " · "}
                            {document.contentHash !== "" && <span className="mono" title={document.contentHash}>{shortHash(document.contentHash)}</span>}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </Accordion>
            )}

            {summary.knowledge.length > 0 && (
              <ArchitectureContextKnowledgeExplorer
                summary={summary}
                projectId={state.status === "ready" && state.context !== null ? state.context.projectId : null}
                repositoryName={repositoryName}
              />
            )}

            {summary.issues.length > 0 && (
              <>
                <span className="stage-section-label">{t("detail.overview.architectureContext.issues")}</span>
                <div className="stage-rows">
                  {summary.issues.map((issue, index) => {
                    const refs = [...new Set([...issue.sectionIds, ...issue.documentReferences])]
                    return (
                      <div className="stage-row" key={index}>
                        <div className="stage-row-main">
                          <span className="mono stage-path">{enumText(t, architectureContextCategoryLabelKeys, issue.category)}</span>
                          {`: ${issue.question}`}
                          {refs.length > 0 && <div className="stage-row-sub">{refs.join(" · ")}</div>}
                        </div>
                        {issue.kind !== "" && (
                          <span className="stage-row-side">
                            <Badge tone={issueKindTone(issue.kind)}>
                              {enumText(t, architectureContextIssueKindLabelKeys, issue.kind)}
                            </Badge>
                          </span>
                        )}
                      </div>
                    )
                  })}
                </div>
              </>
            )}

            {summary.validationErrors.length > 0 && (
              <>
                <span className="stage-section-label">{t("detail.overview.architectureContext.validationErrors")}</span>
                <div className="stage-rows">
                  {summary.validationErrors.map((diagnostic, index) => (
                    <div className="stage-row" key={index}>
                      <div className="stage-row-main">
                        {diagnostic.target !== "" && <span className="mono stage-path">{diagnostic.target}</span>}
                        {diagnostic.target !== "" ? `: ${diagnostic.reason}` : diagnostic.reason}
                        {(diagnostic.position !== null || diagnostic.sectionIds.length > 0) && (
                          <div className="stage-row-sub">
                            {diagnostic.position !== null && `#${diagnostic.position}`}
                            {diagnostic.position !== null && diagnostic.sectionIds.length > 0 && " · "}
                            {diagnostic.sectionIds.join(" · ")}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </>
        )}
      </div>
    </Card>
  )
}
