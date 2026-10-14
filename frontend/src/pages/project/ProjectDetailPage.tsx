import { useEffect, useRef, useState } from "react"
import { Link, Navigate, useNavigate, useParams } from "react-router-dom"
import { ApiError, listProjects, syncProject, type AgentExecution, type ProjectSummary, type VersionAnalysisSummary } from "../../infrastructure/http-client/httpClient.ts"
import { useAgentExecutions } from "../../shared/agent-monitor/useAgentExecutions.ts"
import { useTasks } from "../../shared/task-manager/useTasks.ts"
import { isSyncActive } from "../../shared/task-manager/taskVisibility.ts"
import {
  AnalyzerResultView,
  ArchitectureResultView,
  OrientationResultView,
  PipelineRunStatus,
  ProjectArchitectureResultView,
  SemanticValidationResultView,
  StageStatusView,
} from "../../features/project-management/PipelineResult.tsx"
import {
  confidenceTone,
  kindTone,
  parseAnalyzerResult,
  parseArchitectureResult,
  parseOrientationResult,
  parseProjectArchitectureResult,
  parseSemanticValidationResult,
  verdictTone,
} from "../../features/project-management/pipelineResult.ts"
import { CodeViewer, DirectoryTree, Badge, Button, Card, FolderIcon, MermaidDiagram, Spinner, ExternalIcon, SplitView } from "../../shared/ui-kit/index.ts"
import { localStorage } from "../../infrastructure/storage/LocalStorage.ts"
import { ProjectSidebar } from "./ProjectSidebar.tsx"
import { ProjectHeader } from "./ProjectHeader.tsx"
import { githubRepoUrl } from "../../features/project-management/github.ts"
import { useVersionSelector } from "../../features/project-management/useVersionSelector.ts"
import { useAnalyzedVersions } from "../../features/project-management/useAnalyzedVersions.ts"
import { useAnalysis } from "../../features/project-management/useAnalysis.ts"
import { useProjectFile } from "../../features/project-management/useProjectFile.ts"
import { useProjectTree } from "../../features/project-management/useProjectTree.ts"
import type { VersionMode } from "../../features/project-management/VersionSelector.tsx"
import { useToasts } from "../../app/use-toasts.ts"
import "./ProjectDetailPage.css"

const sectionItems = [
  { id: "overview", label: "Overview", icon: <FolderIcon /> },
  { id: "analysis", label: "Analysis", icon: <FolderIcon /> },
  { id: "audits", label: "Audits", icon: <FolderIcon /> },
  { id: "files", label: "Files", icon: <FolderIcon /> },
]

const VALID_SECTIONS = new Set(sectionItems.map((item) => item.id))

export function ProjectDetailPage() {
  const { id, section } = useParams()
  const navigate = useNavigate()
  const activeSection = section !== undefined && VALID_SECTIONS.has(section) ? section : "overview"
  const [project, setProject] = useState<ProjectSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState("")
  const [syncing, setSyncing] = useState(false)
  const { pushToast } = useToasts()
  const version = useVersionSelector(project?.id ?? null, {
    onApplied: (applied) => {
      pushToast("success", `Version ${applied.branch} at ${applied.commitHash.slice(0, 7)} applied`)
    },
  })
  const files = useProjectTree(project?.id ?? null, project?.repositoryName ?? "")
  const preview = useProjectFile(project?.id ?? null)
  const analysis = useAnalysis(project?.id ?? null)
  const analyzed = useAnalyzedVersions(project?.id ?? null)
  const [versionMode, setVersionMode] = useState<VersionMode>("git")
  const [analyzedId, setAnalyzedId] = useState<number | null>(null)
  const notifiedExecution = useRef<number | null>(null)
  const refreshedExecution = useRef<number | null>(null)
  const analyzedVersions = analyzed.versions.filter((item) => item.evaluationId !== null)
  const selectedAnalyzed = analyzedVersions.find((item) => item.id === analyzedId) ?? null
  const refreshFiles = files.refresh
  const clearPreview = preview.clear
  const refreshAnalyzed = analyzed.refresh
  // The tracked run is the one that finishes last for the running pipeline,
  // so its companions are the other rows of the same evaluation: live first,
  // then the stored versions once they refresh. Old single-row versions only
  // ever yield the analyzer.
  const tracked = analysis.execution
  const liveExecutions = useAgentExecutions()
  const liveTasks = useTasks()
  const analyzerExec = stageExecution("analyzer", tracked, liveExecutions, analyzedVersions, analysis.initialExecutions)
  const architectExec = stageExecution("architect", tracked, liveExecutions, analyzedVersions, analysis.initialExecutions)
  const orientationExec = stageExecution("orientation", tracked, liveExecutions, analyzedVersions, analysis.initialExecutions)
  const projectArchitectureExec = stageExecution("architecture", tracked, liveExecutions, analyzedVersions, analysis.initialExecutions)
  const semanticValidationExec = stageExecution("semantic_validation", tracked, liveExecutions, analyzedVersions, analysis.initialExecutions)
  const analysisSummary = analyzerExec === null ? null : parseAnalyzerResult(analyzerExec.result)
  const architectureSummary = architectExec === null ? null : parseArchitectureResult(architectExec.result)
  const orientationSummary = orientationExec === null ? null : parseOrientationResult(orientationExec.result)
  const projectArchitectureSummary = projectArchitectureExec === null ? null : parseProjectArchitectureResult(projectArchitectureExec.result)
  const semanticValidationSummary = semanticValidationExec === null ? null : parseSemanticValidationResult(semanticValidationExec.result)
  const summaryConfidence = architectureSummary?.confidence ?? analysisSummary?.confidence ?? null
  const versionKey = `${version.applied?.branch ?? ""}:${version.applied?.commitHash ?? ""}:${version.detached ?? ""}`
  const activeHash = version.detached ?? version.applied?.commitHash ?? null
  const activeBranch = version.applied?.branch ?? selectedAnalyzed?.branch ?? null
  // Sync and analysis exclude each other: a sync rewrites the checkout the
  // pipeline reads. Local clicks flip immediately; a sync started elsewhere
  // shows up through the live tasks and through the backend 422.
  const syncActive = syncing || isSyncActive(liveTasks, project?.id ?? null)
  const canAnalyze = activeHash !== null && activeBranch !== null && !version.applying && !version.loadingCommits && !syncActive

  function openFile(path: string) {
    const root = project?.repositoryName ?? ""
    const relative = root !== "" && path.startsWith(`${root}/`) ? path.slice(root.length + 1) : path
    preview.open(relative)
  }

  async function handleSync() {
    if (project === null || syncing) {
      return
    }
    setSyncing(true)
    try {
      const updated = await syncProject(project.id)
      setProject(updated)
      pushToast("success", `Project ${updated.repositoryOwner}/${updated.repositoryName} synced`)
      await version.refresh()
      clearPreview()
      refreshFiles()

    } catch (error) {
      if (error instanceof ApiError) {
        pushToast("error", error.message)
      } else {
        pushToast("error", "Could not sync the project")
      }
    } finally {
      setSyncing(false)
    }
  }

  useEffect(() => {
    let alive = true
    listProjects().then(
      (rows) => {
        if (alive) {
          setProject(rows.find((row) => row.id === Number(id)) ?? null)
          setLoadError("")
          setLoading(false)
        }
      },
      () => {
        if (alive) {
          setProject(null)
          setLoadError("Could not load the project")
          setLoading(false)
        }
      }
    )
    return () => {
      alive = false
    }
  }, [id])

  // single driver: entering the files section and any version change refetch the tree
  useEffect(() => {
    if (activeSection === "files") {
      clearPreview()
      refreshFiles()
    }
  }, [activeSection, versionKey, refreshFiles, clearPreview])

  // analyzed versions load lazily when their tab opens
  useEffect(() => {
    if (versionMode === "analyzed") {
      refreshAnalyzed()
    }
  }, [versionMode, refreshAnalyzed])

  useEffect(() => {
    if (analysis.phase === "error" && analysis.message !== "") {
      pushToast("error", analysis.message)
    }
  }, [analysis.phase, analysis.message, pushToast])

  useEffect(() => {
    const finished = analysis.execution
    if (analysis.phase !== "done" || finished === null || !analysis.tracked || notifiedExecution.current === finished.id) {
      return
    }
    notifiedExecution.current = finished.id
    if (finished.status === "Completed") {
      pushToast("success", "Analysis completed")
    } else {
      pushToast("error", finished.error ?? "Analysis failed")
    }
  }, [analysis.phase, analysis.execution, analysis.tracked, pushToast])

  useEffect(() => {
    const finished = analysis.execution
    if (analysis.phase !== "done" || finished === null || refreshedExecution.current === finished.id) {
      return
    }
    refreshedExecution.current = finished.id
    void refreshAnalyzed()
  }, [analysis.phase, analysis.execution, refreshAnalyzed])

  function handleAnalyze(pipelineId: string) {
    if (activeBranch === null || activeHash === null) {
      return
    }
    void analysis.start(activeBranch, activeHash, pipelineId)
  }

  /** Picks an analyzed version: checks out its commit, then shows its run. */
  async function selectAnalyzed(id: number) {
    const target = analyzedVersions.find((item) => item.id === id) ?? null
    if (target === null || target.commitHash === null) {
      return
    }
    const landed = await version.stageCommit(target.commitHash)
    if (!landed) {
      return
    }
    setAnalyzedId(id)
    // The semantic_validation row carries the final verdict; fall back to the
    // architect, then to the analyzer when an old version only has those rows.
    analysis.show(
      target.executions.find((execution) => execution.agentType === "semantic_validation")
        ?? target.executions.find((execution) => execution.agentType === "architect")
        ?? target.executions.find((execution) => execution.agentType === "analyzer")
        ?? null,
    )
  }

  function handleModeChange(next: VersionMode) {
    setVersionMode(next)
    if (next === "git") {
      setAnalyzedId(null)
      analysis.show(null)
    }
  }

  const gitSelection = {
    ...version,
    changeBranch: (name: string) => {
      setAnalyzedId(null)
      analysis.show(null)
      return version.changeBranch(name)
    },
    stageCommit: (hash: string) => {
      setAnalyzedId(null)
      analysis.show(null)
      return version.stageCommit(hash)
    },
  }

  const runStatuses = (
    <>
      {analyzerExec !== null && <PipelineRunStatus execution={analyzerExec} />}
      {architectExec !== null && <PipelineRunStatus execution={architectExec} />}
      {orientationExec !== null && <PipelineRunStatus execution={orientationExec} />}
      {projectArchitectureExec !== null && <PipelineRunStatus execution={projectArchitectureExec} />}
      {semanticValidationExec !== null && <PipelineRunStatus execution={semanticValidationExec} />}
    </>
  )

  if (section !== undefined && !VALID_SECTIONS.has(section)) {
    return <Navigate to={`/projects/${id}/overview`} replace />
  }

  return (
    <section className="project-page">
      <ProjectSidebar items={sectionItems} activeId={activeSection} onSelect={(next) => void navigate(`/projects/${id}/${next}`)} />
      <div className="project-content">
        {loading ? (
          <p className="label" role="status">Loading project</p>
        ) : loadError !== "" ? (
          <p role="alert">{loadError}</p>
        ) : project === null ? (
          <p>Project not found</p>
        ) : (
          <>
            <ProjectHeader
              project={project}
              analysis={{ canAnalyze, analyzing: analysis.analyzing, onAnalyze: handleAnalyze }}
              syncing={syncActive}
              onSync={() => void handleSync()}
              versionSelector={{
                selection: gitSelection,
                mode: versionMode,
                onModeChange: handleModeChange,
                analyzed: {
                  versions: analyzedVersions,
                  loading: analyzed.loading,
                  error: analyzed.error,
                  selectedId: analyzedId,
                  onSelect: (id) => void selectAnalyzed(id),
                  onRefresh: () => void analyzed.refresh(),
                },
              }}
            />
            <div className="project-body">
            {activeSection === "overview" && <Card>
              <section className="project-overview" aria-label="Project overview">
                <h2>Overview</h2>
                <div className="project-dates-row">
                  <span className="project-date">
                    Registered {new Date(project.registeredAt).toLocaleDateString()}
                  </span>
                  <span className="project-date">
                    {project.lastSyncedAt === null
                      ? "Never synced"
                      : `Last synced ${new Date(project.lastSyncedAt).toLocaleDateString()}`}
                  </span>
                </div>
                <a
                  className="project-link"
                  href={githubRepoUrl(project.repositoryOwner, project.repositoryName)}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open on GitHub<ExternalIcon size={12} />
                </a>
                {analysisSummary !== null && <div className="project-overview-analysis">
                  <h3>Analysis summary</h3>
                  <div className="project-name-row">
                    <span className="label">Type</span>
                    <Badge tone={kindTone(analysisSummary.kind)}>{analysisSummary.kind}</Badge>
                    <span className="label">Confidence</span>
                    <Badge tone={confidenceTone(analysisSummary.confidence)}>{analysisSummary.confidence}</Badge>
                  </div>
                  {analysisSummary.summary !== "" && (
                    <p className="project-summary">{analysisSummary.summary}</p>
                  )}
                </div>}
              {analysis.analyzing && (
                <div className="files-loading" role="status" aria-label="Loading">
                  <Spinner />
                  <span className="label">Analyzing the project</span>
                </div>
              )}
              </section>
            </Card>}
            {activeSection === "overview" && analysis.execution !== null
              && (analysisSummary !== null || architectureSummary !== null
                || orientationSummary !== null || projectArchitectureSummary !== null
                || semanticValidationSummary !== null) && (
              <Card>
                <div className="audit-block">
                  <div className="audit-head">
                    <h4 className="audit-title">Summary</h4>
                    <div className="audit-head-right">
                      <div className="audit-status-row">
                        {analysisSummary !== null && (
                          <>
                            <span className="label">Type</span>
                            <Badge tone={kindTone(analysisSummary.kind)}>{analysisSummary.kind}</Badge>
                          </>
                        )}
                        {architectureSummary !== null && (
                          <>
                            <span className="label">Style</span>
                            <Badge tone={kindTone(architectureSummary.style)}>{architectureSummary.style}</Badge>
                          </>
                        )}
                        {orientationSummary !== null && orientationSummary.projectType !== "" && (
                          <>
                            <span className="label">Project type</span>
                            <Badge tone="info">{orientationSummary.projectType}</Badge>
                          </>
                        )}
                        {projectArchitectureSummary !== null && projectArchitectureSummary.pattern !== "" && (
                          <>
                            <span className="label">Pattern</span>
                            <Badge tone="info">{projectArchitectureSummary.pattern}</Badge>
                          </>
                        )}
                        {semanticValidationSummary !== null && (
                          <>
                            <span className="label">Review</span>
                            <Badge tone={verdictTone(semanticValidationSummary.verdict)}>{semanticValidationSummary.verdict}</Badge>
                          </>
                        )}
                        {summaryConfidence !== null && (
                          <>
                            <span className="label">Confidence</span>
                            <Badge tone={confidenceTone(summaryConfidence)}>{summaryConfidence}</Badge>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                  {analysisSummary !== null && analysisSummary.summary !== "" && (
                    <p className="audit-text">{analysisSummary.summary}</p>
                  )}
                  {architectureSummary !== null && architectureSummary.dataFlow !== "" && (
                    <p className="audit-text">{architectureSummary.dataFlow}</p>
                  )}
                  <span className="label">{summaryCounts(analysisSummary, architectureSummary)}</span>
                  <div className="audit-button-row">
                    <Button onClick={() => void navigate(`/projects/${id}/analysis`)}>
                      View full analysis
                    </Button>
                  </div>
                </div>
              </Card>
            )}
            {activeSection === "analysis" && analysis.execution !== null && (
              <>
                {analyzerExec !== null && (
                  <Card>
                    {analysisSummary !== null
                      ? <AnalyzerResultView summary={analysisSummary} execution={analyzerExec} />
                      : <PipelineRunStatus execution={analyzerExec} />}
                  </Card>
                )}
                {architectExec !== null && (
                  <Card>
                    {architectureSummary !== null
                      ? <ArchitectureResultView description={architectureSummary} execution={architectExec} />
                      : <PipelineRunStatus execution={architectExec} />}
                  </Card>
                )}
                {orientationExec !== null && (
                  <Card>
                    {orientationSummary !== null
                      ? <OrientationResultView summary={orientationSummary} execution={orientationExec} />
                      : <StageStatusView title="Orientation" result={orientationExec.result} execution={orientationExec} />}
                  </Card>
                )}
                {projectArchitectureExec !== null && (
                  <Card>
                    {projectArchitectureSummary !== null
                      ? <ProjectArchitectureResultView summary={projectArchitectureSummary} execution={projectArchitectureExec} />
                      : <StageStatusView title="Architecture" result={projectArchitectureExec.result} execution={projectArchitectureExec} />}
                  </Card>
                )}
                {semanticValidationExec !== null && (
                  <Card>
                    {semanticValidationSummary !== null
                      ? <SemanticValidationResultView summary={semanticValidationSummary} execution={semanticValidationExec} />
                      : <StageStatusView title="Semantic validation" result={semanticValidationExec.result} execution={semanticValidationExec} />}
                  </Card>
                )}
                {architectureSummary !== null
                  && (architectureSummary.diagramContainers !== "" || architectureSummary.diagramComponents !== "") && (
                  <Card>
                    <div className="audit-block">
                      <h4 className="audit-title">Diagrams</h4>
                      {architectureSummary.diagramContainers !== "" && (
                        <>
                          <span className="label">Containers</span>
                          <MermaidDiagram chart={architectureSummary.diagramContainers} label="Containers diagram" />
                        </>
                      )}
                      {architectureSummary.diagramComponents !== "" && (
                        <>
                          <span className="label">Components</span>
                          <MermaidDiagram chart={architectureSummary.diagramComponents} label="Components diagram" />
                        </>
                      )}
                    </div>
                  </Card>
                )}
              </>
            )}
            {activeSection === "files" && (
              <Card>
                <SplitView
                  label="Resize file preview and directories"
                  right={
                    preview.loading && preview.file === null ? (
                      <div className="files-loading" role="status" aria-label="Loading">
                        <Spinner />
                        <span className="label">Loading file</span>
                      </div>
                    ) : preview.error !== "" ? (
                      <p className="files-error">{preview.error}</p>
                    ) : preview.file === null ? (
                      <p className="label files-empty">Select a file to preview</p>
                    ) : (
                      <CodeViewer code={preview.file.content} language={fileLanguage(preview.file.path)} highlight />
                    )
                  }
                  left={
                    files.loading && files.tree === null ? (
                      <div className="files-loading" role="status" aria-label="Loading">
                        <Spinner />
                        <span className="label">Loading project files</span>
                      </div>
                    ) : files.error !== "" ? (
                      <p className="files-error">{files.error}</p>
                    ) : files.tree === null ? (
                      <p className="label">No files to show</p>
                    ) : (
                      <DirectoryTree tree={files.tree} onRefresh={files.refresh} onSelectFile={openFile} />
                    )
                  }
                />
              </Card>
            )}
            {activeSection === "audits" && (
              analysis.execution === null ? (
                <p className="label">No analysis yet — pick a version and press Analyze</p>
              ) : (
                <Card>
                  {runStatuses}
                  {[analyzerExec, architectExec].filter((execution) => execution?.configuration).map((execution) => execution && <div className="audit-configuration" key={execution.id}>
                    <h3>Configuration used</h3>
                    <p className="label">Captured for {execution.agentType} #{execution.id}</p>
                    <dl>
                      <dt>Model</dt><dd>{execution.configuration!.model.name}</dd>
                      <dt>Provider</dt><dd>{execution.configuration!.model.providerName}</dd>
                      <dt>Credential</dt><dd>{execution.configuration!.credential.name} (#{execution.configuration!.credential.id})</dd>
                      <dt>Temperature</dt><dd>{execution.configuration!.temperature}</dd>
                      <dt>Maximum tokens</dt><dd>{execution.configuration!.maxTokens}</dd>
                    </dl>
                    <p className="label">Captured when this execution started. Later Settings changes apply to new executions.</p>
                  </div>)}
                </Card>
              )
            )}
            {analysis.phase === "error" && <Card>
              <p role="alert">{analysis.message}</p>
             <Link to="/settings" onClick={() => localStorage.set("settings.activeTab", "agents")}>Review agent configuration</Link>
            </Card>}
            </div>
          </>
        )}
      </div>
    </section>
  )
}

function fileLanguage(path: string): string {
  const dot = path.lastIndexOf(".")
  return dot < 0 ? "" : path.slice(dot + 1).toLowerCase()
}

/** One line of counts for the overview summary card. */
function summaryCounts(
  analysis: { keyComponents: string[] } | null,
  architecture: { components: unknown[]; risks: unknown[]; qualityNotes: unknown[] } | null,
): string {
  const parts: string[] = []
  if (analysis !== null && analysis.keyComponents.length > 0) {
    parts.push(`${analysis.keyComponents.length} key component(s)`)
  }
  if (architecture !== null) {
    parts.push(`${architecture.components.length} component(s)`)
    parts.push(`${architecture.risks.length} risk(s)`)
    parts.push(`${architecture.qualityNotes.length} quality note(s)`)
  }
  return parts.join(" · ")
}

/** One pipeline row of the tracked evaluation, if it is known. */
function stageExecution(
  stage: string,
  tracked: AgentExecution | null,
  live: AgentExecution[],
  versions: VersionAnalysisSummary[],
  initial: AgentExecution[],
): AgentExecution | null {
  if (tracked?.agentType === stage) {
    return tracked
  }
  if (tracked === null || tracked.evaluationId === null) {
    return initial.find((item) => item?.agentType === stage) ?? null
  }
  const clean = (rows: AgentExecution[]): AgentExecution[] =>
    rows.filter((item): item is AgentExecution => item !== null && typeof item === "object")
  const match = (rows: AgentExecution[]): AgentExecution | null => clean(rows).find(
    (item) => item.evaluationId === tracked.evaluationId && item.agentType === stage,
  ) ?? null
  const current = match(live)
  const stored = match(versions.flatMap((version) => version.executions)) ?? match(initial)
  if (current === null) {
    return stored
  }
  return { ...current, configuration: current.configuration ?? stored?.configuration ?? null }
}
