import { useNavigate } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { Badge, Button, Card, FolderIcon, ArrowRightIcon, PinIcon, ExternalIcon } from "../../shared/ui-kit/index.ts"
import { formatDate } from "../../shared/i18n/format.ts"
import type { ProjectSummary } from "../../infrastructure/http-client/httpClient.ts"
import { projectStatusLabelKey, statusTone } from "./projectStatus.ts"
import { githubRepoUrl } from "./github.ts"
import "./ProjectCard.css"

export function ProjectCard({ project, pinned, onTogglePin }: { project: ProjectSummary, pinned: boolean, onTogglePin: (id: number) => void }) {
  const { t } = useTranslation("projects")
  const navigate = useNavigate()
  const ready = project.status === "READY"
  const repository = `${project.repositoryOwner}/${project.repositoryName}`
  const statusKey = projectStatusLabelKey(project.status)
  const pinLabel = pinned ? t("card.unpin") : t("card.pin")

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
              {repository}
            </button>
            <a
              className="project-github"
              href={githubRepoUrl(project.repositoryOwner, project.repositoryName)}
              target="_blank"
              rel="noreferrer"
              aria-label={t("card.openOnGitHubLabel", { repo: repository })}
              title={t("card.openOnGitHub")}
            >
              <ExternalIcon size={13} />
            </a>
            <Badge tone={statusTone(project.status)}>{statusKey === null ? project.status : t(statusKey)}</Badge>
            <Badge tone="neutral">{project.cloneProtocol.toUpperCase()}</Badge>
          </span>
          <span className="project-date">
            {formatDate(project.registeredAt)}
          </span>
        </span>
        <button
          type="button"
          className={pinned ? "project-pin project-pin-active" : "project-pin"}
          aria-pressed={pinned}
          aria-label={pinLabel}
          title={pinLabel}
          onClick={() => onTogglePin(project.id)}
        >
          <PinIcon size={14} />
        </button>
        <Button disabled={!ready} onClick={() => void navigate(`/projects/${project.id}`)}>
          {t("card.inspect")}<ArrowRightIcon />
        </Button>
      </div>
    </Card>
  )
}
