import type { ComponentProps } from "react"
import { useTranslation } from "react-i18next"
import { Badge, Button } from "../../shared/ui-kit/index.ts"
import { projectStatusLabelKey, statusTone } from "../../features/project-management/projectStatus.ts"
import { VersionLocation, VersionSelector, type AnalysisAction } from "../../features/project-management/VersionSelector.tsx"
import type { ProjectSummary } from "../../infrastructure/http-client/httpClient.ts"
import "./ProjectHeader.css"

interface ProjectHeaderProps {
  project: ProjectSummary
  versionSelector: Omit<ComponentProps<typeof VersionSelector>, "analysis">
  showVersionSelector?: boolean
  analysis: AnalysisAction
  syncing: boolean
  onSync: () => void
  onExtractGraph: () => void
  graphRunning: boolean
  canExtractGraph: boolean
}

export function ProjectHeader({ project, versionSelector, showVersionSelector = true, analysis, syncing, onSync, onExtractGraph, graphRunning, canExtractGraph }: ProjectHeaderProps) {
  const { t } = useTranslation("projects")
  const statusKey = projectStatusLabelKey(project.status)
  return <header className="project-context-header" aria-label={t("detail.contextLabel")}>
    <div className="project-context-top-row">
      <div className="project-context-identity">
        <h1 className="mono">{project.repositoryOwner}/{project.repositoryName}</h1>
        <div className="project-context-badges">
        <Badge tone={statusTone(project.status)}>{statusKey === null ? project.status : t(statusKey)}</Badge>
        <Badge tone="neutral">{project.cloneProtocol.toUpperCase()}</Badge>
        {analysis.analyzing && <Badge tone="info">{t("detail.analyzingBadge")}</Badge>}
        </div>
        <VersionLocation selection={versionSelector.selection} />
      </div>
      <div className="project-context-actions" role="group" aria-label={t("detail.actionsLabel")}>
        <Button variant="secondary" onClick={onSync} disabled={syncing || analysis.analyzing || graphRunning} loading={syncing} loadingText={t("detail.syncing")}>{t("detail.syncLabel")}</Button>
        <Button onClick={onExtractGraph} disabled={!canExtractGraph || graphRunning} loading={graphRunning} loadingText={t("analyze.label")}>{t("analyze.label")}</Button>
      </div>
    </div>
    {showVersionSelector && <div className="project-context-controls">
      <VersionSelector {...versionSelector} showLocation={false} size="compact" />
    </div>}
  </header>
}
