import type { ComponentProps } from "react"
import { Badge, Button } from "../../shared/ui-kit/index.ts"
import { statusTone } from "../../features/project-management/projectStatus.ts"
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
  return <header className="project-context-header" aria-label="Project context">
    <div className="project-context-top-row">
      <div className="project-context-identity">
        <h1 className="mono">{project.repositoryOwner}/{project.repositoryName}</h1>
        <Badge tone={statusTone(project.status)}>{project.status}</Badge>
        <Badge tone="neutral">{project.cloneProtocol.toUpperCase()}</Badge>
        {analysis.analyzing && <Badge tone="info">Analyzing</Badge>}
        <VersionLocation selection={versionSelector.selection} />
      </div>
      <div className="project-context-actions" role="group" aria-label="Project actions">
        <Button onClick={onSync} disabled={syncing || analysis.analyzing} loading={syncing} loadingText="Syncing">Sync</Button>
        <AnalyzeMenu canAnalyze={analysis.canAnalyze} analyzing={analysis.analyzing} onAnalyze={analysis.onAnalyze} />
      </div>
    </div>
    <div className="project-context-controls">
      <VersionSelector {...versionSelector} showLocation={false} />
    </div>
  </header>
}
