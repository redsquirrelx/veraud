import { useState } from "react"
import { useTranslation } from "react-i18next"
import { Button, Card, FolderIcon, Sidebar, TextInput, Toast } from "../../shared/ui-kit/index.ts"
import "./TestSidebarPage.css"

const menuItemKeys = [
  { id: "projects", labelKey: "testPages.sidebar.sections.projects" },
  { id: "audits", labelKey: "testPages.sidebar.sections.audits" },
  { id: "reports", labelKey: "testPages.sidebar.sections.reports" },
] as const

export function TestSidebarPage() {
  const { t } = useTranslation("common")
  const [active, setActive] = useState("projects")
  const menuItems = menuItemKeys.map((item) => ({ id: item.id, label: t(item.labelKey), icon: <FolderIcon /> }))

  return (
    <section className="test-sidebar-page">
      <Sidebar title={t("testPages.sidebar.workspace")} items={menuItems} activeId={active} storageKey="sidebar.expanded" onSelect={setActive} />
      <div className="test-sidebar-content">
        <h1>{t("testPages.sidebar.title")}</h1>
        <Card>
          <span className="label">{t("testPages.sidebar.activeSection")}</span>
          <p className="mono">{active}</p>
        </Card>
        <div className="test-sidebar-row">
          <TextInput value="" placeholder={t("testPages.sidebar.searchPlaceholder")} onChange={() => {}} />
          <Button>{t("testPages.sidebar.apply")}</Button>
        </div>
        <Toast kind="success" message={t("testPages.sidebar.sidebarReady")} />
      </div>
    </section>
  )
}
