import { useEffect, useState } from "react"
import { useParams } from "react-router-dom"
import { ApiError } from "../../infrastructure/http-client/httpClient.ts"
import { Badge, Button, Card, FolderIcon, Sidebar } from "../../shared/ui-kit/index.ts"
import { statusTone } from "../../features/project-management/projectStatus.ts"
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

  async function handleSync() {
    if (project === null || syncing) {
      return
    }
    setSyncing(true)
    try {
      const updated = await syncProject(project.id)
      setProject(updated)
      pushToast("success", `Project ${updated.repositoryOwner}/${updated.repositoryName} synced`)
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
            {section !== "overview" && (
              <p className="label">{section} coming in the next HU</p>
            )}
          </>
        )}
      </div>
    </section>
  )
}
