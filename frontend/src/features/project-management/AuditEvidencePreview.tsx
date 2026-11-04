import { useId, useState } from "react"
import { useTranslation } from "react-i18next"
import { Badge, CodeViewer } from "../../shared/ui-kit/index.ts"
import "./AuditEvidencePreview.css"

/** Presentation fixtures only. No audit data, repository access or API requests. */
const examples = [
  { id: "example-file", kind: "file", source: "example/src/services/ProjectService.ts", start: 1, end: 7,
    code: `import type { ProjectRepository } from "../repositories/ProjectRepository"

export class ProjectService {
  constructor(private repository: ProjectRepository) {}

  findById(id: number) {
    return this.repository.findById(id)
  }

  listProjects() {
    return this.repository.findAll()
  }
}` },
  { id: "example-symbol", kind: "symbol", symbol: "ProjectController.findProject", source: "example/src/controllers/ProjectController.ts", start: 8, end: 10,
    code: `import type { ProjectService } from "../services/ProjectService"

export class ProjectController {
  constructor(private projectService: ProjectService) {}

  // Delegate project retrieval to the application service.

  async findProject(id: number) {
    return this.projectService.findById(id)
  }

  async listProjects() {
    return this.projectService.listProjects()
  }
}` },
  { id: "example-snippet", kind: "snippet", source: "example/src/application/container.ts", start: 9, end: 11,
    code: `import { ProjectRepository } from "../repositories/ProjectRepository"
import { ProjectService } from "../services/ProjectService"
import { ProjectController } from "../controllers/ProjectController"
import { database } from "./database"

const projectRepository = new ProjectRepository(database)

// Register the application service with its repository.
const projectService = new ProjectService(
  projectRepository,
)

export const projectController = new ProjectController(projectService)

export const services = { projectService }
` },
] as const

export function AuditEvidencePreview() {
  const { t } = useTranslation("auditEvidence")
  const [selectedId, setSelectedId] = useState<string>(examples[0].id)
  const selected = examples.find((item) => item.id === selectedId) ?? examples[0]
  const id = useId()

  return <section className="audit-evidence-preview" aria-labelledby={`${id}-title`}>
    <header><h3 id={`${id}-title`}>{t("mockupTitle")}</h3><Badge tone="warning">{t("mockupBadge")}</Badge></header>
    <p role="note">{t("mockupNotice")}</p>
    <div className="audit-evidence-preview-layout">
      <ul className="audit-evidence-preview-list" aria-label={t("mockupList")}>
        {examples.map((evidence) => <li key={evidence.id}>
          <button type="button" className="audit-evidence-preview-choice" aria-pressed={selected.id === evidence.id}
            aria-controls={`${id}-viewer`} onClick={() => setSelectedId(evidence.id)}>
            <span className="audit-evidence-preview-choice-head"><Badge tone="neutral">{t(evidence.kind)}</Badge><span>{t("mockupBadge")}</span></span>
            {"symbol" in evidence && <strong>{evidence.symbol}</strong>}
            <code>{evidence.source}</code>
            <span>{t("lines", { start: evidence.start, end: evidence.end })}</span>
          </button>
        </li>)}
      </ul>
      <section id={`${id}-viewer`} className="audit-evidence-preview-viewer" aria-label={t("viewerTitle")}>
        <header><h4>{t("viewerTitle")}</h4><Badge tone="neutral">{t(selected.kind)}</Badge></header>
        <code>{selected.source}</code>
        <p>{t("lines", { start: selected.start, end: selected.end })}</p>
        <CodeViewer code={selected.code} language="ts" highlight
          marks={[{ id: t("evidenceRange"), from: selected.start, to: selected.end, tone: "info" }]} />
      </section>
    </div>
  </section>
}
