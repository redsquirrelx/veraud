import { useEffect, useState } from "react"
import { useParams } from "react-router-dom"
import { ApiError } from "../../infrastructure/http-client/httpClient.ts"
import { CodeViewer, DirectoryTree, Badge, Button, Card, FolderIcon, Sidebar, Spinner, ExternalIcon, SplitView } from "../../shared/ui-kit/index.ts"
import { statusTone } from "../../features/project-management/projectStatus.ts"
import { githubRepoUrl } from "../../features/project-management/github.ts"
import { useVersionSelector } from "../../features/project-management/useVersionSelector.ts"
import { useAnalysis } from "../../features/project-management/useAnalysis.ts"
import { useProjectFile } from "../../features/project-management/useProjectFile.ts"
import { useProjectTree } from "../../features/project-management/useProjectTree.ts"
import { VersionSelector } from "../../features/project-management/VersionSelector.tsx"
import { useToasts } from "../../app/use-toasts.ts"
import { listProjects, syncProject, type AgentExecution, type ProjectSummary } from "../../infrastructure/http-client/httpClient.ts"
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
  const refreshFiles = files.refresh
  const clearPreview = preview.clear
  const versionKey = `${version.applied?.branch ?? ""}:${version.applied?.commitHash ?? ""}:${version.detached ?? ""}`
  const canAnalyze = version.applied !== null && version.detached === null && !version.applying

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

  useEffect(() => {
    if (analysis.phase === "error" && analysis.message !== "") {
      pushToast("error", analysis.message)
    }
  }, [analysis.phase, analysis.message, pushToast])

  function handleAnalyze() {
    if (version.applied === null) {
      return
    }
    void analysis.start(version.applied.branch, version.applied.commitHash)
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
                selection={version}
                analysis={{ canAnalyze, analyzing: analysis.analyzing, onAnalyze: handleAnalyze }}
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
                </div>
                <Button loading={syncing} loadingText="Syncing" disabled={syncing} onClick={() => void handleSync()}>
                  Sync
                </Button>
              </div>
            </Card>
            {section === "overview" && analysis.execution !== null && (
              <AnalysisResultCard execution={analysis.execution} />
            )}
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
                <AnalysisResultCard execution={analysis.execution} />
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

function AnalysisResultCard({ execution }: { execution: AgentExecution }) {
  return (
    <Card>
      <div className="audit-status-row">
        <Badge tone={auditTone(execution.status)}>{execution.status}</Badge>
        <span className="label">
          {execution.agentType} run #{execution.id}
        </span>
      </div>
      {execution.status === "Failed" ? (
        <p className="files-error">{execution.error ?? "Analysis failed"}</p>
      ) : execution.result === null ? (
        <div className="files-loading" role="status" aria-label="Loading">
          <Spinner />
          <span className="label">Analyzing the project</span>
        </div>
      ) : (
        <CodeViewer code={execution.result} language="json" highlight />
      )}
    </Card>
  )
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
