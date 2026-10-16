import type { ComponentProps } from "react"
import { useTranslation } from "react-i18next"
import { Badge, Button } from "../../shared/ui-kit/index.ts"
import { projectStatusLabelKey, statusTone } from "../../features/project-management/projectStatus.ts"
import { AnalyzeMenu } from "../../features/project-management/AnalyzeMenu.tsx"
import { VersionLocation, VersionSelector, type AnalysisAction } from "../../features/project-management/VersionSelector.tsx"
import type { ProjectSummary } from "../../infrastructure/http-client/httpClient.ts"
import "./ProjectHeader.css"

interface ProjectHeaderProps {
  project: ProjectSummary
  versionSelector: Omit<ComponentProps<typeof VersionSelector>, "analysis">
  analysis: AnalysisAction
  syncing: boolean
  onSync: () => void
}

export function ProjectHeader({ project, versionSelector, analysis, syncing, onSync }: ProjectHeaderProps) {
  const { t } = useTranslation("projects")
  const statusKey = projectStatusLabelKey(project.status)
  return <header className="project-context-header" aria-label={t("detail.contextLabel")}>
    <div className="project-context-top-row">
      <div className="project-context-identity">
        <h1 className="mono">{project.repositoryOwner}/{project.repositoryName}</h1>
        <Badge tone={statusTone(project.status)}>{statusKey === null ? project.status : t(statusKey)}</Badge>
        <Badge tone="neutral">{project.cloneProtocol.toUpperCase()}</Badge>
        {analysis.analyzing && <Badge tone="info">{t("detail.analyzingBadge")}</Badge>}
        <VersionLocation selection={versionSelector.selection} />
      </div>
      <div className="project-context-actions" role="group" aria-label={t("detail.actionsLabel")}>
        <Button onClick={onSync} disabled={syncing || analysis.analyzing} loading={syncing} loadingText={t("detail.syncing")}>{t("detail.syncLabel")}</Button>
        <AnalyzeMenu canAnalyze={analysis.canAnalyze} analyzing={analysis.analyzing} onAnalyze={analysis.onAnalyze} />
      </div>
    </div>
    <div className="project-context-controls">
      <VersionSelector {...versionSelector} showLocation={false} />
    </div>
  </header>
}
