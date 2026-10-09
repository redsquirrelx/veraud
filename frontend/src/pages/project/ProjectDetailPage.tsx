import { useEffect, useRef, useState } from "react"
import { useParams } from "react-router-dom"
import { ApiError } from "../../infrastructure/http-client/httpClient.ts"
import { CodeViewer, DirectoryTree, Badge, Button, Card, FolderIcon, Sidebar, Spinner, ExternalIcon, SplitView } from "../../shared/ui-kit/index.ts"
import { statusTone } from "../../features/project-management/projectStatus.ts"
import { githubRepoUrl } from "../../features/project-management/github.ts"
import { useVersionSelector } from "../../features/project-management/useVersionSelector.ts"
import { useAnalyzedVersions } from "../../features/project-management/useAnalyzedVersions.ts"
import { useAnalysis } from "../../features/project-management/useAnalysis.ts"
import { useProjectFile } from "../../features/project-management/useProjectFile.ts"
import { useProjectTree } from "../../features/project-management/useProjectTree.ts"
import { VersionSelector, type VersionMode } from "../../features/project-management/VersionSelector.tsx"
import { useToasts } from "../../app/use-toasts.ts"
import { listProjects, syncProject, type ProjectSummary } from "../../infrastructure/http-client/httpClient.ts"
import "./ProjectDetailPage.css"

const sectionItems = [
  { id: "overview", label: "Overview", icon: <FolderIcon /> },
  { id: "audits", label: "Audits", icon: <FolderIcon /> },
  { id: "files", label: "Files", icon: <FolderIcon /> },
]

export function ProjectDetailPage() {
  const { id } = useParams()
  const [section, setSection] = useState("overview")
  const [project, setProject] = useState<ProjectSummary | null>(null)
  const [loading, setLoading] = useState(true)
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
  const analysisSummary = analysis.execution === null || analysis.execution.result === null
    ? null
    : parseAnalysisResult(analysis.execution.result)
  const versionKey = `${version.applied?.branch ?? ""}:${version.applied?.commitHash ?? ""}:${version.detached ?? ""}`
  const activeHash = version.detached ?? version.applied?.commitHash ?? null
  const activeBranch = version.applied?.branch ?? selectedAnalyzed?.branch ?? null
  const canAnalyze = activeHash !== null && activeBranch !== null && !version.applying && !version.loadingCommits

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
          setLoading(false)
        }
      },
      () => {
        if (alive) {
          setProject(null)
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
    if (section === "files") {
      clearPreview()
      refreshFiles()
    }
  }, [section, versionKey, refreshFiles, clearPreview])

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

  function handleAnalyze() {
    if (activeBranch === null || activeHash === null) {
      return
    }
    void analysis.start(activeBranch, activeHash)
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
    analysis.show(target.execution)
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

  return (
    <section className="project-page">
      <Sidebar title="Project" items={sectionItems} activeId={section} storageKey="sidebar.expanded" onSelect={setSection} />
      <div className="project-content">
        {loading ? (
          <p className="label">Loading project</p>
        ) : project === null ? (
          <p>Project not found</p>
        ) : (
          <>
            <Card>
              <VersionSelector
                selection={gitSelection}
                analysis={{ canAnalyze, analyzing: analysis.analyzing, onAnalyze: handleAnalyze }}
                mode={versionMode}
                onModeChange={handleModeChange}
                analyzed={{
                  versions: analyzedVersions,
                  loading: analyzed.loading,
                  error: analyzed.error,
                  selectedId: analyzedId,
                  onSelect: (id) => void selectAnalyzed(id),
                  onRefresh: () => void analyzed.refresh(),
                }}
              />
            </Card>
            <Card>
              <div className="project-header">
                <div className="project-header-info">
                  <span className="project-name-row">
                    <span className="mono">
                      {project.repositoryOwner}/{project.repositoryName}
                    </span>
                    <Badge tone={statusTone(project.status)}>{project.status}</Badge>
                    {analysisSummary !== null && (
                      <>
                        <span className="label">Type</span>
                        <Badge tone={kindTone(analysisSummary.kind)}>{analysisSummary.kind}</Badge>
                        <span className="label">Confidence</span>
                        <Badge tone={confidenceTone(analysisSummary.confidence)}>{analysisSummary.confidence}</Badge>
                      </>
                    )}
                    {analysisSummary === null && analysis.analyzing && (
                      <Badge tone="info">Analyzing</Badge>
                    )}
                    <a
                      className="project-link"
                      href={githubRepoUrl(project.repositoryOwner, project.repositoryName)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Open on GitHub<ExternalIcon size={12} />
                    </a>
                  </span>
                  <span className="project-dates-row">
                    <span className="project-date">
                      Registered {new Date(project.registeredAt).toLocaleDateString()}
                    </span>
                    <span className="project-date">
                      {project.lastSyncedAt === null
                        ? "Never synced"
                        : `Last synced ${new Date(project.lastSyncedAt).toLocaleDateString()}`}
                    </span>
                  </span>
                  {analysisSummary !== null && analysisSummary.summary !== "" && (
                    <span className="project-summary">{analysisSummary.summary}</span>
                  )}
                </div>
                <Button loading={syncing} loadingText="Syncing" disabled={syncing} onClick={() => void handleSync()}>
                  Sync
                </Button>
              </div>
              {analysis.analyzing && (
                <div className="files-loading" role="status" aria-label="Loading">
                  <Spinner />
                  <span className="label">Analyzing the project</span>
                </div>
              )}
            </Card>
            {section === "files" && (
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
            {section === "audits" && (
              analysis.execution === null ? (
                <p className="label">No analysis yet — pick a version and press Analyze</p>
              ) : (
                <Card>
                  <div className="audit-status-row">
                    <Badge tone={auditTone(analysis.execution.status)}>{analysis.execution.status}</Badge>
                    <span className="label">
                      {analysis.execution.agentType} run #{analysis.execution.id}
                    </span>
                  </div>
                </Card>
              )
            )}
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

function auditTone(status: string): "success" | "warning" | "info" {
  if (status === "Completed") {
    return "success"
  }
  if (status === "Failed") {
    return "warning"
  }
  return "info"
}

const ANALYSIS_KINDS = new Set([
  "cli",
  "library",
  "web_service",
  "desktop_app",
  "data_pipeline",
  "script",
  "unknown",
])

const ANALYSIS_CONFIDENCES = new Set(["low", "medium", "high"])

interface AnalysisSummary {
  kind: string
  confidence: string
  summary: string
}

/** The analyzer's verdict parsed out of its raw JSON result, if usable. */
function parseAnalysisResult(result: string | null): AnalysisSummary | null {
  if (result === null || result.trim() === "") {
    return null
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(result) as unknown
  } catch {
    return null
  }
  if (typeof parsed !== "object" || parsed === null) {
    return null
  }
  const record = parsed as Record<string, unknown>
  const kind = typeof record["kind"] === "string" ? record["kind"] : ""
  const confidence = typeof record["confidence"] === "string" ? record["confidence"] : ""
  if (!ANALYSIS_KINDS.has(kind) || !ANALYSIS_CONFIDENCES.has(confidence)) {
    return null
  }
  const summary = typeof record["summary"] === "string" ? record["summary"].trim() : ""
  return { kind, confidence, summary }
}

function kindTone(kind: string): "info" | "neutral" {
  return kind === "unknown" ? "neutral" : "info"
}

function confidenceTone(confidence: string): "success" | "info" | "warning" {
  if (confidence === "high") {
    return "success"
  }
  if (confidence === "medium") {
    return "info"
  }
  return "warning"
}
