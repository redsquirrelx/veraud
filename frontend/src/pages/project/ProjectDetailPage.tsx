import { useEffect, useState } from "react"
import { useParams } from "react-router-dom"
import { ApiError } from "../../infrastructure/http-client/httpClient.ts"
import { DirectoryTree, Badge, Button, Card, FolderIcon, Sidebar, Spinner } from "../../shared/ui-kit/index.ts"
import { statusTone } from "../../features/project-management/projectStatus.ts"
import { useVersionSelector } from "../../features/project-management/useVersionSelector.ts"
import { useProjectTree } from "../../features/project-management/useProjectTree.ts"
import { VersionSelector } from "../../features/project-management/VersionSelector.tsx"
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
  const refreshFiles = files.refresh
  const versionKey = `${version.applied?.branch ?? ""}:${version.applied?.commitHash ?? ""}:${version.detached ?? ""}`

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
      refreshFiles()
    }
  }, [section, versionKey, refreshFiles])

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
              <VersionSelector selection={version} />
            </Card>
            <Card>
              <div className="project-header">
                <div className="project-header-info">
                  <span className="mono">
                    {project.repositoryOwner}/{project.repositoryName}
                  </span>
                  <span className="project-date">
                    Registered {new Date(project.registeredAt).toLocaleDateString()}
                  </span>
                  <span className="project-date">
                    {project.lastSyncedAt === null
                      ? "Never synced"
                      : `Last synced ${new Date(project.lastSyncedAt).toLocaleDateString()}`}
                  </span>
                  <Badge tone={statusTone(project.status)}>{project.status}</Badge>
                </div>
                <Button loading={syncing} loadingText="Syncing" disabled={syncing} onClick={() => void handleSync()}>
                  Sync
                </Button>
              </div>
            </Card>
            {section === "files" && (
              <Card>
                {files.loading && files.tree === null ? (
                  <div className="files-loading" role="status" aria-label="Loading">
                    <Spinner />
                    <span className="label">Loading project files</span>
                  </div>
                ) : files.error !== "" ? (
                  <p className="files-error">{files.error}</p>
                ) : files.tree === null ? (
                  <p className="label">No files to show</p>
                ) : (
                  <DirectoryTree tree={files.tree} onRefresh={files.refresh} />
                )}
              </Card>
            )}
            {section === "audits" && (
              <p className="label">audits coming in the next HU</p>
            )}
          </>
        )}
      </div>
    </section>
  )
}
