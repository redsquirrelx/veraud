import { useState } from "react"
import { Link } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { Card, DropdownMenu, type DropdownMenuItem } from "../../shared/ui-kit/index.ts"
import "./TestDropdownPage.css"

export function TestDropdownPage() {
  const { t } = useTranslation("common")
  const pipelineItems: DropdownMenuItem[] = [
    { id: "architecture-audit", label: t("testPages.dropdown.pipelines.classic.title"), description: t("testPages.dropdown.pipelines.classic.description") },
    { id: "project-architecture", label: t("testPages.dropdown.pipelines.projectArchitecture.title"), description: t("testPages.dropdown.pipelines.projectArchitecture.description") },
    { id: "coming-soon", label: t("testPages.dropdown.pipelines.comingSoon.title"), description: t("testPages.dropdown.pipelines.comingSoon.description"), disabled: true },
  ]
  const [selectedId, setSelectedId] = useState<string | null>("architecture-audit")
  const [lastChosen, setLastChosen] = useState<string | null>(null)

  return (
    <section className="test-dropdown-page">
      <h1>{t("testPages.dropdown.title")}</h1>
      <p className="label">
        <Link to="/test">{t("testPages.allPlaygrounds")}</Link>
      </p>
      <Card>
        <span className="label">{t("testPages.dropdown.actionMenu")}</span>
        <DropdownMenu
          label={t("testPages.dropdown.analyze")}
          items={pipelineItems}
          selectedId={selectedId}
          onSelect={(id) => {
            setSelectedId(id)
            setLastChosen(id)
          }}
        />
      </Card>
      <Card>
        <span className="label">{t("testPages.dropdown.lastChosen")}</span>
        <p className="mono">{lastChosen ?? t("testPages.none")}</p>
      </Card>
      <Card>
        <span className="label">{t("testPages.dropdown.loadingTrigger")}</span>
        <DropdownMenu label={t("testPages.dropdown.analyze")} items={pipelineItems} loading loadingText={t("testPages.dropdown.analyzing")} onSelect={() => {}} />
      </Card>
      <Card>
        <span className="label">{t("testPages.dropdown.disabledEmpty")}</span>
        <div className="test-dropdown-row">
          <DropdownMenu label={t("testPages.dropdown.disabled")} items={pipelineItems} disabled onSelect={() => {}} />
          <DropdownMenu label={t("testPages.dropdown.emptyMenu")} items={[]} emptyText={t("testPages.dropdown.noPipelines")} onSelect={() => {}} />
        </div>
      </Card>
    </section>
  )
}
