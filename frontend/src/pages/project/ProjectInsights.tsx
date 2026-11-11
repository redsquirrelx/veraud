import { Link } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { Card, ChevronRightIcon, LockIcon } from "../../shared/ui-kit/index.ts"
import { ProjectArchitectureContextIcon, ProjectGraphIcon } from "./projectSectionIcons.tsx"
import "./ProjectInsights.css"

export function ProjectInsights({ projectId, architectureContextAvailable, graphAvailable }: {
  projectId: number
  architectureContextAvailable: boolean
  graphAvailable: boolean
}) {
  const { t } = useTranslation("projects")
  const insights = [
    { id: "architecture-context", available: architectureContextAvailable, icon: <ProjectArchitectureContextIcon />, href: `/projects/${projectId}/architecture-context` },
    { id: "graph", available: graphAvailable, icon: <ProjectGraphIcon />, href: `/projects/${projectId}/graph` },
  ] as const
  const noneAvailable = !architectureContextAvailable && !graphAvailable

  return <Card className="project-body-card project-insights-card" layout="stack" gap="sm" align="stretch">
    <section aria-labelledby="project-insights-title">
      <h2 id="project-insights-title" className="project-insights-title">{t("detail.overview.insights.title")}</h2>
      <div className="project-insights-grid">
        {insights.map((item) => <div className="project-insight-cell" key={item.id}>
          {item.available ? <Link className="project-insight" to={item.href}>
            <span className="project-insight-icon">{item.icon}</span>
            <span className="project-insight-copy">
              <span className="project-insight-name">{t(`detail.overview.insights.${item.id}.title`)}</span>
              <span className="project-insight-description">{t(`detail.overview.insights.${item.id}.description`)}</span>
            </span>
            <ChevronRightIcon size={16} />
          </Link> : <div className="project-insight project-insight-disabled" aria-disabled="true">
            <span className="project-insight-icon">{item.icon}</span>
            <span className="project-insight-copy">
              <span className="project-insight-name">{t(`detail.overview.insights.${item.id}.title`)}</span>
              <span className="project-insight-description">{t(`detail.overview.insights.${item.id}.description`)}</span>
            </span>
            <LockIcon size={15} />
          </div>}
        </div>)}
      </div>
      {noneAvailable && <p className="project-insights-empty" role="status">{t("detail.overview.insights.notAnalyzed")}</p>}
    </section>
  </Card>
}
