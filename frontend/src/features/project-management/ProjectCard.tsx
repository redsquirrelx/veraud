import { useNavigate } from "react-router-dom"
import { Badge, Button, Card, FolderIcon } from "../../shared/ui-kit/index.ts"
import type { ProjectSummary } from "../../infrastructure/http-client/httpClient.ts"
import "./ProjectCard.css"

function statusTone(status: string): "success" | "warning" | "info" {
  if (status === "READY") {
    return "success"
  }
  if (status === "SYNCING") {
    return "info"
  }
  return "warning"
}

export function ProjectCard({ project }: { project: ProjectSummary }) {
  const navigate = useNavigate()
  const ready = project.status === "READY"

  return (
    <Card>
      <div className="project-row">
        <span className="project-icon">
          <FolderIcon size={16} />
        </span>
        <span className="project-titles">
          <button
            type="button"
            className="project-title"
            disabled={!ready}
            onClick={() => void navigate(`/projects/${project.id}`)}
          >
            {`${project.repositoryOwner}/${project.repositoryName}`}
          </button>
          <span className="project-date">
            {new Date(project.registeredAt).toLocaleDateString()}
          </span>
        </span>
        <Badge tone={statusTone(project.status)}>{project.status}</Badge>
        <Button disabled={!ready} onClick={() => void navigate(`/projects/${project.id}`)}>
          Inspect ΓåÆ
        </Button>
      </div>
    </Card>
  )
}
