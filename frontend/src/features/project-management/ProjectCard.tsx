import { useNavigate } from "react-router-dom"
import { Badge, Button, Card, FolderIcon, ArrowRightIcon, PinIcon, ExternalIcon } from "../../shared/ui-kit/index.ts"
import type { ProjectSummary } from "../../infrastructure/http-client/httpClient.ts"
import { statusTone } from "./projectStatus.ts"
import { githubRepoUrl } from "./github.ts"
import "./ProjectCard.css"

export function ProjectCard({ project, pinned, onTogglePin }: { project: ProjectSummary, pinned: boolean, onTogglePin: (id: number) => void }) {
  const navigate = useNavigate()
  const ready = project.status === "READY"

  return (
    <Card>
      <div className="project-row">
        <span className="project-icon">
          <FolderIcon size={16} />
        </span>
        <span className="project-titles">
          <span className="project-title-row">
            <button
              type="button"
              className="project-title"
              disabled={!ready}
              onClick={() => void navigate(`/projects/${project.id}`)}
            >
              {`${project.repositoryOwner}/${project.repositoryName}`}
            </button>
            <a
              className="project-github"
              href={githubRepoUrl(project.repositoryOwner, project.repositoryName)}
              target="_blank"
              rel="noreferrer"
              aria-label={`Open ${project.repositoryOwner}/${project.repositoryName} on GitHub`}
              title="Open on GitHub"
            >
              <ExternalIcon size={13} />
            </a>
            <Badge tone={statusTone(project.status)}>{project.status}</Badge>
          </span>
          <span className="project-date">
            {new Date(project.registeredAt).toLocaleDateString()}
          </span>
        </span>
        <button
          type="button"
          className={pinned ? "project-pin project-pin-active" : "project-pin"}
          aria-pressed={pinned}
          aria-label={pinned ? "Unpin project" : "Pin project"}
          title={pinned ? "Unpin project" : "Pin project"}
          onClick={() => onTogglePin(project.id)}
        >
          <PinIcon size={14} />
        </button>
        <Button disabled={!ready} onClick={() => void navigate(`/projects/${project.id}`)}>
          Inspect<ArrowRightIcon />
        </Button>
      </div>
    </Card>
  )
}
