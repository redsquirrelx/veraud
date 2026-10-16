import { Link } from "react-router-dom"
import { useTranslation } from "react-i18next"
import { ArrowRightIcon } from "../../shared/ui-kit/index.ts"
import "./TestIndexPage.css"

const testPageKeys = [
  { path: "/test/components", titleKey: "testPages.index.pages.components.title", descriptionKey: "testPages.index.pages.components.description" },
  { path: "/test/selector", titleKey: "testPages.index.pages.selectors.title", descriptionKey: "testPages.index.pages.selectors.description" },
  { path: "/test/dropdown", titleKey: "testPages.index.pages.dropdowns.title", descriptionKey: "testPages.index.pages.dropdowns.description" },
  { path: "/test/stage-showcase", titleKey: "testPages.index.pages.stageShowcase.title", descriptionKey: "testPages.index.pages.stageShowcase.description" },
  { path: "/test/controls", titleKey: "testPages.index.pages.controls.title", descriptionKey: "testPages.index.pages.controls.description" },
  { path: "/test/form-controls", titleKey: "testPages.index.pages.formControls.title", descriptionKey: "testPages.index.pages.formControls.description" },
  { path: "/test/directory", titleKey: "testPages.index.pages.directory.title", descriptionKey: "testPages.index.pages.directory.description" },
  { path: "/test/file-viewer", titleKey: "testPages.index.pages.fileViewer.title", descriptionKey: "testPages.index.pages.fileViewer.description" },
  { path: "/test_sidebar", titleKey: "testPages.index.pages.sidebar.title", descriptionKey: "testPages.index.pages.sidebar.description" },
] as const

export function TestIndexPage() {
  const { t } = useTranslation("common")
  return (
    <section className="page test-index-page">
      <h1>{t("testPages.index.title")}</h1>
      <p className="label">{t("testPages.index.subtitle")}</p>
      <nav className="test-index-links" aria-label={t("testPages.index.navLabel")}>
        {testPageKeys.map((page) => (
          <Link key={page.path} to={page.path} className="test-index-link">
            <span className="test-index-info">
              <span className="mono">{t(page.titleKey)}</span>
              <span className="label">{t(page.descriptionKey)}</span>
            </span>
            <ArrowRightIcon />
          </Link>
        ))}
      </nav>
    </section>
  )
}
